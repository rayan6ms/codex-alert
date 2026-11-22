"""Shared configuration helpers for the Agents Alert desktop companion."""

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path


APP_NAME = "Agents Alert"
HOME = Path.home()
CONFIG_DIR = HOME / ".config/codex-alert"
PHONE_FILE = CONFIG_DIR / "phone.json"
TOKEN_FILE = CONFIG_DIR / "phone-token"
CERTIFICATE_FILE = CONFIG_DIR / "phone-cert.pem"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
STATE_DIR = HOME / ".local/state/codex-notify"
T3_STATE_DIR = HOME / ".t3/userdata"
T3_SCRATCH_DIR = HOME / ".t3/scratch"
T3_CURRENT_DB = T3_STATE_DIR / "statev2.sqlite"
T3_LEGACY_DB = T3_STATE_DIR / "state.sqlite"
T3_SETTINGS_FILE = T3_STATE_DIR / "settings.json"
MAX_SESSION_INDEX_BYTES = 16 * 1024 * 1024


def clean_title(value, limit=120):
    text = " ".join(str(value or "").split())
    if not text or text.lower() == "new thread":
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def is_t3_scratch_path(path, scratch_dir=None):
    raw = str(path or "").strip()
    if not raw:
        return False
    candidate = Path(raw)
    parts = candidate.parts
    if any(parts[index : index + 2] == (".t3", "scratch") for index in range(len(parts) - 1)):
        return True
    base = T3_SCRATCH_DIR if scratch_dir is None else Path(scratch_dir)
    try:
        resolved = candidate.resolve(strict=False)
        resolved_base = base.resolve(strict=False)
        return resolved == resolved_base or resolved_base in resolved.parents
    except OSError:
        return False


def load_json(path, default=None):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else (default or {})
    except (OSError, ValueError):
        return default or {}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def questions_text(questions):
    if not isinstance(questions, list):
        return ""
    return "\n".join(
        question.get("question") or question.get("title") or ""
        for question in questions
        if isinstance(question, dict)
        and isinstance(question.get("question") or question.get("title") or "", str)
    ).strip()


def settings():
    return load_json(SETTINGS_FILE, {"t3_integration": False})


def t3_enabled():
    return settings().get("t3_integration") is True


def set_t3_enabled(enabled):
    value = settings()
    value["t3_integration"] = bool(enabled)
    atomic_json(SETTINGS_FILE, value)


def open_t3_db(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)


def t3_session(session_id, driver=None, current_db=T3_CURRENT_DB, legacy_db=T3_LEGACY_DB):
    """Return the T3 thread and provider instance for a native provider session."""
    if not session_id:
        return None
    queries = []
    if current_db is not None and current_db.is_file():
        if driver:
            queries.append((
                current_db,
                """
                SELECT thread_id, provider_instance_id
                FROM orchestration_v2_projection_provider_threads
                WHERE driver = ? AND thread_id IS NOT NULL
                  AND json_extract(payload_json, '$.nativeThreadRef.nativeId') = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (driver, session_id),
            ))
        else:
            queries.append((
                current_db,
                """
                SELECT thread_id, provider_instance_id
                FROM orchestration_v2_projection_provider_threads
                WHERE thread_id IS NOT NULL
                  AND json_extract(payload_json, '$.nativeThreadRef.nativeId') = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (session_id,),
            ))
    if legacy_db is not None and legacy_db.is_file() and driver in (None, "codex"):
        queries.append((
            legacy_db,
            """
            SELECT thread_id, provider_instance_id FROM provider_session_runtime
            WHERE lower(provider_name) = 'codex' AND json_valid(resume_cursor_json)
              AND json_extract(resume_cursor_json, '$.threadId') = ?
            ORDER BY last_seen_at DESC LIMIT 1
            """,
            (session_id,),
        ))
    for path, query, parameters in queries:
        try:
            with closing(open_t3_db(path)) as connection:
                match = connection.execute(query, parameters).fetchone()
            if match:
                return match
        except (OSError, sqlite3.Error):
            continue
    return None


def t3_codex_session(session_id, current_db=T3_CURRENT_DB, legacy_db=T3_LEGACY_DB):
    """Return the T3 thread and provider instance for a native Codex session."""
    return t3_session(session_id, driver="codex", current_db=current_db, legacy_db=legacy_db)


def t3_thread_metadata(thread_id, current_db=T3_CURRENT_DB, legacy_db=T3_LEGACY_DB):
    """Return the normalized title and project metadata for a T3 thread."""
    if not thread_id:
        return None
    attempts = (
        (
            current_db,
            (
                """
                SELECT COALESCE(NULLIF(trim(thread.title), ''),
                                json_extract(thread.payload_json, '$.title')),
                       project.title,
                       project.workspace_root,
                       json_extract(thread.payload_json, '$.worktreePath')
                FROM orchestration_v2_projection_threads AS thread
                LEFT JOIN projection_projects AS project ON project.project_id = thread.project_id
                WHERE thread.thread_id = ? AND thread.deleted_at IS NULL
                LIMIT 1
                """,
                """
                SELECT json_extract(thread.payload_json, '$.title'),
                       NULL,
                       project.workspace_root,
                       json_extract(thread.payload_json, '$.worktreePath')
                FROM orchestration_v2_projection_threads AS thread
                LEFT JOIN projection_projects AS project ON project.project_id = thread.project_id
                WHERE thread.thread_id = ? AND thread.deleted_at IS NULL
                LIMIT 1
                """,
            ),
        ),
        (
            legacy_db,
            (
                """
                SELECT thread.title,
                       project.title,
                       project.workspace_root,
                       thread.worktree_path
                FROM projection_threads AS thread
                LEFT JOIN projection_projects AS project ON project.project_id = thread.project_id
                WHERE thread.thread_id = ? AND thread.deleted_at IS NULL
                LIMIT 1
                """,
            ),
        ),
    )
    for path, queries in attempts:
        if path is None or not path.is_file():
            continue
        try:
            with closing(open_t3_db(path)) as connection:
                match = None
                for query in queries:
                    try:
                        match = connection.execute(query, (thread_id,)).fetchone()
                        break
                    except sqlite3.OperationalError:
                        continue
            if not match:
                continue
            raw_title, project_title, workspace_root, worktree_path = match
            normalized_project = clean_title(project_title)
            is_scratch = (
                normalized_project.lower() == "no project"
                or is_t3_scratch_path(workspace_root)
                or is_t3_scratch_path(worktree_path)
            )
            project = ""
            if not is_scratch:
                project = normalized_project or (
                    Path(str(workspace_root)).name if workspace_root else ""
                )
            return {
                "title": clean_title(raw_title),
                "project": project,
                "is_scratch": is_scratch,
            }
        except (OSError, sqlite3.Error):
            continue
    return None


def codex_session_title(session_id, homes=None):
    """Return the latest Codex thread title from session_index.jsonl if present."""
    if not session_id:
        return ""
    candidates = []
    if homes is None:
        if os.environ.get("CODEX_HOME"):
            candidates.append(Path(os.environ["CODEX_HOME"]))
        candidates.extend(codex_homes())
    else:
        candidates.extend(Path(home) for home in homes)

    seen = set()
    for home in candidates:
        index_path = home / "session_index.jsonl"
        try:
            resolved = index_path.resolve(strict=True)
            status = resolved.stat()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file() or status.st_size > MAX_SESSION_INDEX_BYTES:
            continue
        seen.add(resolved)
        try:
            lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if session_id not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("id") == session_id:
                title = clean_title(entry.get("thread_name"))
                if title:
                    return title
    return ""


def t3_account(instance_id, fallback, settings_file=T3_SETTINGS_FILE):
    instances = load_json(settings_file).get("providerInstances")
    instance = instances.get(instance_id) if isinstance(instances, dict) else None
    config = instance.get("config") if isinstance(instance, dict) else None
    if isinstance(config, dict):
        configured_home = config.get("shadowHomePath") or config.get("homePath")
        if configured_home:
            name = Path(str(configured_home)).name.lstrip(".")
            if name:
                return name
    if instance_id == "codex":
        return "codex"
    prefix = "codex_account"
    if instance_id and instance_id.startswith(prefix) and instance_id[len(prefix):].isdigit():
        return "codex" + instance_id[len(prefix):]
    return fallback


def phone():
    return load_json(PHONE_FILE)


def phone_configured():
    return PHONE_FILE.is_file() and TOKEN_FILE.is_file() and CERTIFICATE_FILE.is_file()


def codex_homes():
    candidates = []
    configured = os.environ.get("CODEX_ALERT_CODEX_HOMES", "")
    if configured:
        candidates.extend(Path(value) for value in configured.split(os.pathsep) if value)
    if os.environ.get("CODEX_HOME"):
        candidates.append(Path(os.environ["CODEX_HOME"]))
    try:
        candidates.extend(HOME.iterdir())
    except OSError:
        pass

    homes = []
    seen = set()
    for candidate in candidates:
        if not candidate.is_dir() or not (candidate / "auth.json").is_file():
            continue
        try:
            identity = candidate.resolve()
        except OSError:
            identity = candidate.absolute()
        if identity not in seen:
            seen.add(identity)
            homes.append(candidate)
    return sorted(homes, key=lambda path: (path.name != ".codex", path.name))
