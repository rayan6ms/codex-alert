"""Shared configuration helpers for the Codex Alert desktop companion."""

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path


HOME = Path.home()
CONFIG_DIR = HOME / ".config/codex-alert"
PHONE_FILE = CONFIG_DIR / "phone.json"
TOKEN_FILE = CONFIG_DIR / "phone-token"
CERTIFICATE_FILE = CONFIG_DIR / "phone-cert.pem"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
STATE_DIR = HOME / ".local/state/codex-notify"
T3_STATE_DIR = HOME / ".t3/userdata"
T3_CURRENT_DB = T3_STATE_DIR / "statev2.sqlite"
T3_LEGACY_DB = T3_STATE_DIR / "state.sqlite"
T3_SETTINGS_FILE = T3_STATE_DIR / "settings.json"


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


def t3_codex_session(session_id, current_db=T3_CURRENT_DB, legacy_db=T3_LEGACY_DB):
    """Return the T3 thread and provider instance for a native Codex session."""
    for path, query in (
        (current_db, """
            SELECT thread_id, provider_instance_id
            FROM orchestration_v2_projection_provider_threads
            WHERE driver = 'codex' AND thread_id IS NOT NULL
              AND json_extract(payload_json, '$.nativeThreadRef.nativeId') = ?
            ORDER BY updated_at DESC LIMIT 1
        """),
        (legacy_db, """
            SELECT thread_id, provider_instance_id FROM provider_session_runtime
            WHERE lower(provider_name) = 'codex' AND json_valid(resume_cursor_json)
              AND json_extract(resume_cursor_json, '$.threadId') = ?
            ORDER BY last_seen_at DESC LIMIT 1
        """),
    ):
        if path is None or not path.is_file():
            continue
        try:
            with closing(open_t3_db(path)) as connection:
                match = connection.execute(query, (session_id,)).fetchone()
            if match:
                return match
        except (OSError, sqlite3.Error):
            continue
    return None


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
