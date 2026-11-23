"""Install and normalize the native hooks used by Claude Code and Antigravity."""

import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from codex_alert_common import (
    T3_CURRENT_DB,
    open_t3_db,
    questions_text,
    t3_enabled,
    t3_watcher_active,
)


CLAUDE = "claude-code"
ANTIGRAVITY = "antigravity"
PROVIDER_NAMES = {CLAUDE: "Claude Code", ANTIGRAVITY: "Antigravity"}
PROVIDER_LABELS = {
    **PROVIDER_NAMES,
    "opencode": "OpenCode",
    "cursor": "Cursor",
}
T3_PROVIDERS = {"claudeAgent": CLAUDE, "antigravity": ANTIGRAVITY}
ANTIGRAVITY_HOOK_NAME = "agents-alert"


def provider_config(provider):
    if provider == CLAUDE:
        root = os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"
        return Path(root).expanduser() / "settings.json"
    return Path.home() / ".gemini/config/hooks.json"


def provider_installed(provider):
    if provider_config(provider).is_file():
        return True
    if provider == CLAUDE:
        return shutil.which("claude") is not None
    gemini = Path.home() / ".gemini"
    return any(
        (gemini / directory).is_dir()
        for directory in ("antigravity", "antigravity-cli", "antigravity-ide")
    ) or any(shutil.which(binary) for binary in ("agy", "antigravity", "antigravity-ide"))


def add_hook(container, event, command, matcher=None):
    groups = container.setdefault(event, [])
    if not isinstance(groups, list):
        raise RuntimeError(f"invalid {event} hook list")
    handler = {"type": "command", "command": command, "timeout": 5}
    for group in groups:
        if not isinstance(group, dict) or group.get("matcher", "") != (matcher or ""):
            continue
        hooks = group.get("hooks")
        if isinstance(hooks, list) and any(
            isinstance(hook, dict) and hook.get("command") == command for hook in hooks
        ):
            return
    group = {"hooks": [handler]}
    if matcher:
        group["matcher"] = matcher
    groups.append(group)


def add_provider_hooks(config, provider, notifier):
    command = f"{shlex.quote(notifier)} --provider {provider}"
    if provider == CLAUDE:
        hooks = config.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise RuntimeError("invalid Claude Code hooks")
        for event in ("Stop", "StopFailure", "PermissionRequest"):
            add_hook(hooks, event, command)
        add_hook(hooks, "PreToolUse", command, "^AskUserQuestion$")
    else:
        hooks = config.setdefault(ANTIGRAVITY_HOOK_NAME, {})
        if not isinstance(hooks, dict):
            raise RuntimeError(f"invalid Antigravity hook group {ANTIGRAVITY_HOOK_NAME}")
        add_hook(hooks, "Stop", f"{command} --hook-event Stop")
        add_hook(hooks, "PreToolUse", f"{command} --hook-event PreToolUse", "^ask_question$")


def claude_event(payload):
    if payload.get("agent_id"):
        return None
    event = payload.get("hook_event_name")
    turn_id = payload.get("prompt_id") or payload.get("turn_id") or ""
    alert = {
        "session_id": payload.get("session_id"),
        "turn_id": turn_id,
        "cwd": payload.get("cwd"),
        "model": payload.get("model"),
    }
    if event == "Stop":
        alert["last_assistant_message"] = payload.get("last_assistant_message")
    elif event == "StopFailure":
        alert["error"] = (
            payload.get("last_assistant_message") or payload.get("error_details")
            or payload.get("error") or "The Claude Code task failed."
        )
    elif event in ("PreToolUse", "PermissionRequest"):
        tool = payload.get("tool_name")
        tool_input = payload.get("tool_input")
        tool_input = tool_input if isinstance(tool_input, dict) else {}
        if event == "PreToolUse" and tool == "AskUserQuestion":
            message = questions_text(tool_input.get("questions")) or "Claude Code needs your input."
        elif event == "PermissionRequest" and isinstance(tool, str) and tool != "AskUserQuestion":
            message = f"Claude Code requests approval for {tool}."
        else:
            return None
        request_id = payload.get("tool_use_id")
        if not request_id and turn_id:
            arguments = json.dumps([turn_id, tool, tool_input], sort_keys=True)
            request_id = hashlib.sha256(arguments.encode()).hexdigest()
        alert.update(request_id=request_id or uuid.uuid4().hex, input_message=message)
    else:
        return None
    return alert


def antigravity_event(payload, event):
    workspaces = payload.get("workspacePaths")
    if not isinstance(workspaces, list):
        workspaces = []
    cwd = next((path for path in workspaces if isinstance(path, str) and path), "")
    execution = payload.get("executionNum")
    alert = {
        "session_id": payload.get("conversationId"),
        "turn_id": str(execution) if type(execution) is int else "",
        "cwd": cwd,
        "model": payload.get("modelName"),
    }
    reason = payload.get("terminationReason")
    if event == "Stop" and reason in ("error", "max_steps_exceeded"):
        fallback = (
            "Antigravity reached its step limit." if reason == "max_steps_exceeded"
            else "The Antigravity task failed."
        )
        alert["error"] = payload.get("error") or fallback
    elif event == "Stop" and reason == "model_stop" and payload.get("fullyIdle") is True:
        alert["last_assistant_message"] = "Antigravity finished the task."
    elif event == "PreToolUse":
        tool = payload.get("toolCall")
        if not isinstance(tool, dict) or tool.get("name") != "ask_question":
            return None
        arguments = tool.get("args")
        questions = arguments.get("questions") if isinstance(arguments, dict) else None
        step = payload.get("stepIdx")
        alert.update(
            request_id=f"question-{step}" if type(step) is int else uuid.uuid4().hex,
            input_message=questions_text(questions) or "Antigravity needs your input.",
        )
    else:
        return None
    return alert


def t3_handles_session(provider, session_id, database=T3_CURRENT_DB, require_watcher=True):
    """Use the T3 event stream for its own runs when integration is enabled."""
    if not session_id or not t3_enabled() or not database.is_file():
        return False
    if require_watcher and not t3_watcher_active():
        return False
    driver = next((key for key, name in T3_PROVIDERS.items() if name == provider), provider)
    try:
        with closing(open_t3_db(database)) as connection:
            return connection.execute(
                """
                SELECT 1 FROM orchestration_v2_projection_provider_threads AS provider_thread
                JOIN orchestration_v2_projection_runs AS run USING (provider_thread_id)
                WHERE provider_thread.driver = ?
                  AND json_extract(provider_thread.payload_json, '$.nativeThreadRef.nativeId') = ?
                  AND (run.status IN ('starting', 'running', 'waiting')
                       OR datetime(run.completed_at) > datetime('now', '-10 seconds'))
                LIMIT 1
                """,
                (driver, session_id),
            ).fetchone() is not None
    except (OSError, sqlite3.Error):
        return False
