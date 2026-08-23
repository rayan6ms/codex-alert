"""Shared configuration helpers for the Codex Alert desktop companion."""

import json
import os
from pathlib import Path


HOME = Path.home()
CONFIG_DIR = HOME / ".config/codex-alert"
PHONE_FILE = CONFIG_DIR / "phone.json"
TOKEN_FILE = CONFIG_DIR / "phone-token"
CERTIFICATE_FILE = CONFIG_DIR / "phone-cert.pem"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
STATE_DIR = HOME / ".local/state/codex-notify"


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
