import importlib.machinery
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "codex-notify-stop"
sys.path.insert(0, str(SCRIPT.parent))
_LOADER = importlib.machinery.SourceFileLoader("codex_notify_stop", str(SCRIPT))
_SPEC = importlib.util.spec_from_loader("codex_notify_stop", _LOADER)
MODULE = importlib.util.module_from_spec(_SPEC)
_LOADER.exec_module(MODULE)


class HookWrapperTests(unittest.TestCase):
    def test_ephemeral_codex_exec_is_ignored(self):
        self.assertTrue(MODULE.is_ephemeral_codex_exec([
            ["/usr/lib/codex", "exec", "--ephemeral", "--model", "gpt-5.6-luna"],
            ["/usr/bin/t3-code"],
        ]))

    def test_interactive_and_persistent_exec_are_not_ignored(self):
        self.assertFalse(MODULE.is_ephemeral_codex_exec([
            ["/usr/lib/codex", "app-server"],
            ["/usr/bin/t3-code"],
        ]))
        self.assertFalse(MODULE.is_ephemeral_codex_exec([
            ["/usr/lib/codex", "exec", "--model", "gpt-5.6-luna"],
        ]))

    def test_process_ancestry_reads_parent_chain(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            (proc / "42").mkdir()
            (proc / "42" / "cmdline").write_bytes(b"codex\0exec\0--ephemeral\0")
            (proc / "42" / "status").write_text("Name:\tcodex\nPPid:\t7\n", encoding="utf-8")
            (proc / "7").mkdir()
            (proc / "7" / "cmdline").write_bytes(b"t3-code\0")
            (proc / "7" / "status").write_text("Name:\tt3-code\nPPid:\t1\n", encoding="utf-8")

            self.assertEqual(
                MODULE.process_ancestry(parent_pid=42, proc_root=proc),
                [["codex", "exec", "--ephemeral"], ["t3-code"]],
            )

    def test_dispatch_claim_deduplicates_before_delivery_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            with (
                patch.object(MODULE, "STATE_DIR", state),
                patch.object(MODULE, "RECENT_EVENTS_FILE", state / "recent"),
                patch.object(MODULE, "EVENT_LOCK_FILE", state / "lock"),
            ):
                self.assertTrue(MODULE.remember_dispatch("event-1"))
                self.assertFalse(MODULE.remember_dispatch("event-1"))
                self.assertTrue(MODULE.remember_dispatch("event-2"))

    def test_main_launches_each_delivery_path_only_once_for_duplicate_stop(self):
        payload = (
            '{"session_id":"session-1","turn_id":"turn-1","cwd":"/tmp/project",'
            '"model":"gpt-5.6-sol","last_assistant_message":"Done"}'
        )
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            with (
                patch.object(MODULE, "STATE_DIR", state),
                patch.object(MODULE, "RECENT_EVENTS_FILE", state / "recent"),
                patch.object(MODULE, "EVENT_LOCK_FILE", state / "lock"),
                patch.object(MODULE, "LOG_FILE", state / "log"),
                patch.object(MODULE, "LOG_LOCK_FILE", state / "log-lock"),
                patch.object(MODULE, "is_ephemeral_codex_exec", return_value=False),
                patch.object(MODULE, "t3_thread_target", return_value=None),
                patch.object(MODULE, "phone_configured", return_value=True),
                patch.object(MODULE, "launch", return_value=True) as launch,
                patch("sys.argv", [str(SCRIPT)]),
            ):
                with patch("sys.stdin", io.StringIO(payload)):
                    self.assertEqual(MODULE.main(), 0)
                with patch("sys.stdin", io.StringIO(payload)):
                    self.assertEqual(MODULE.main(), 0)

        self.assertEqual(launch.call_count, 2)

    def test_failure_and_completion_for_same_turn_are_mutually_deduplicated(self):
        failure = (
            '{"session_id":"session-1","turn_id":"turn-1","cwd":"/tmp/project",'
            '"model":"gpt-5.6-sol","error":"upstream unavailable"}'
        )
        completion = (
            '{"session_id":"session-1","turn_id":"turn-1","cwd":"/tmp/project",'
            '"model":"gpt-5.6-sol","last_assistant_message":"Done"}'
        )
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            with (
                patch.object(MODULE, "STATE_DIR", state),
                patch.object(MODULE, "RECENT_EVENTS_FILE", state / "recent"),
                patch.object(MODULE, "EVENT_LOCK_FILE", state / "lock"),
                patch.object(MODULE, "LOG_FILE", state / "log"),
                patch.object(MODULE, "LOG_LOCK_FILE", state / "log-lock"),
                patch.object(MODULE, "is_ephemeral_codex_exec", return_value=False),
                patch.object(MODULE, "t3_thread_target", return_value=None),
                patch.object(MODULE, "phone_configured", return_value=True),
                patch.object(MODULE, "launch", return_value=True) as launch,
            ):
                with (
                    patch("sys.argv", [str(SCRIPT), "--failure"]),
                    patch("sys.stdin", io.StringIO(failure)),
                ):
                    self.assertEqual(MODULE.main(), 0)
                with (
                    patch("sys.argv", [str(SCRIPT)]),
                    patch("sys.stdin", io.StringIO(completion)),
                ):
                    self.assertEqual(MODULE.main(), 0)

        self.assertEqual(launch.call_count, 2)
        self.assertTrue(any(
            value.startswith("Failed ❌")
            for value in launch.call_args_list[0].args[0]
        ))

    def test_claude_hooks_send_completion_failure_and_input_to_both_receivers(self):
        cases = [
            ({"hook_event_name": "Stop", "last_assistant_message": "Fixed it."},
             "Finished", "Fixed it."),
            ({"hook_event_name": "StopFailure", "error": "rate_limit",
              "error_details": "Quota exhausted"}, "Failed", "Quota exhausted"),
            ({"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
              "tool_use_id": "question-1", "tool_input": {"questions": [{"question": "Which target?"}]}},
             "Input", "Which target?"),
            ({"hook_event_name": "PermissionRequest", "tool_name": "ExitPlanMode"},
             "Input", "Claude Code requests approval for ExitPlanMode."),
        ]
        for event, status, message in cases:
            with self.subTest(event=event["hook_event_name"]):
                payload = {"session_id": "session-1", "prompt_id": "prompt-1", "cwd": "/tmp/project", **event}
                with (
                    patch.object(MODULE, "launch", return_value=True) as launch,
                    patch.object(MODULE, "remember_dispatch", return_value=True) as remember,
                    patch.object(MODULE, "t3_handles_session", return_value=False),
                    patch.object(MODULE, "t3_thread_target", return_value=None),
                    patch.object(MODULE, "phone_configured", return_value=True),
                    patch.object(MODULE, "log"),
                    patch("sys.argv", [str(SCRIPT), "--provider", "claude-code"]),
                    patch("sys.stdin", io.StringIO(json.dumps(payload))),
                    patch("sys.stdout", io.StringIO()) as stdout,
                ):
                    self.assertEqual(MODULE.main(), 0)
                    self.assertEqual(json.loads(stdout.getvalue()), {})
                    self.assertIsNotNone(remember.call_args.args[0])
                    self.assertEqual(launch.call_count, 2)
                    for call in launch.call_args_list:
                        command = call.args[0]
                        self.assertTrue(command[command.index("--title") + 1].startswith(status))
                        self.assertEqual(command[command.index("--body") + 1], f"Claude Code\n{message}")

    def test_antigravity_hooks_report_questions_and_terminal_outcomes(self):
        cases = [
            ("Stop", {"fullyIdle": True, "terminationReason": "model_stop"}, "stop", "completion"),
            ("Stop", {"fullyIdle": False, "terminationReason": "model_stop"}, "stop", None),
            ("Stop", {"terminationReason": "interrupted"}, "stop", None),
            ("Stop", {"terminationReason": "error", "error": "Service unavailable"}, "stop", "failure"),
            ("Stop", {"terminationReason": "max_steps_exceeded"}, "stop", "failure"),
            ("PreToolUse", {"stepIdx": 0, "toolCall": {
                "name": "ask_question", "args": {"questions": [{"question": "Which file?"}]},
            }}, "allow", "input"),
        ]
        for event, fields, decision, outcome in cases:
            with self.subTest(event=event, fields=fields):
                payload = {
                    "conversationId": "conversation-1", "executionNum": 2, "modelName": "gemini",
                    "workspacePaths": ["/tmp/project"], **fields,
                }
                with (
                    patch.object(MODULE, "dispatch") as dispatch,
                    patch.object(MODULE, "t3_handles_session", return_value=False),
                    patch("sys.argv", [str(SCRIPT), "--provider", "antigravity", "--hook-event", event]),
                    patch("sys.stdin", io.StringIO(json.dumps(payload))),
                    patch("sys.stdout", io.StringIO()) as stdout,
                ):
                    self.assertEqual(MODULE.main(), 0)
                    self.assertEqual(json.loads(stdout.getvalue()), {"decision": decision})
                    if outcome:
                        normalized, account, actual_outcome = dispatch.call_args.args
                        self.assertEqual((account, actual_outcome), ("antigravity", outcome))
                        self.assertEqual(normalized["cwd"], "/tmp/project")
                        self.assertEqual(normalized["turn_id"], "2")
                        if outcome == "input":
                            self.assertEqual(normalized["input_message"], "Which file?")
                            self.assertEqual(normalized["request_id"], "question-0")
                    else:
                        dispatch.assert_not_called()

    def test_native_hook_defers_alerts_for_t3_managed_sessions(self):
        with (
            patch.object(MODULE, "dispatch") as dispatch,
            patch.object(MODULE, "t3_handles_session", return_value=True) as handles,
            patch("sys.argv", [str(SCRIPT), "--provider", "claude-code"]),
            patch("sys.stdin", io.StringIO('{"hook_event_name":"Stop","session_id":"session-1"}')),
            patch("sys.stdout", io.StringIO()) as stdout,
        ):
            self.assertEqual(MODULE.main(), 0)
            self.assertEqual(json.loads(stdout.getvalue()), {})
            handles.assert_called_once_with("claude-code", "session-1")
            dispatch.assert_not_called()

    def test_codex_native_stop_hook_defers_for_t3_managed_sessions(self):
        with (
            patch.object(MODULE, "is_ephemeral_codex_exec", return_value=False),
            patch.object(MODULE, "t3_handles_session", return_value=True) as handles,
            patch.object(MODULE, "dispatch") as dispatch,
            patch.object(MODULE, "log"),
            patch("sys.argv", [str(SCRIPT)]),
            patch("sys.stdin", io.StringIO('{"session_id":"codex-session-1","turn_id":"turn-1"}')),
            patch("sys.stdout", io.StringIO()) as stdout,
        ):
            self.assertEqual(MODULE.main(), 0)
            self.assertEqual(json.loads(stdout.getvalue()), {})
            handles.assert_called_once_with("codex", "codex-session-1")
            dispatch.assert_not_called()

    def test_t3_dispatched_codex_completion_is_not_deferred(self):
        payload = json.dumps({
            "session_id": "codex-session-1",
            "turn_id": "turn-1",
            "t3_thread_id": "t3-thread-1",
            "cwd": "/tmp/project",
            "last_assistant_message": "Done.",
        })
        with (
            patch.object(MODULE, "is_ephemeral_codex_exec", return_value=False),
            patch.object(MODULE, "t3_handles_session", return_value=True) as handles,
            patch.object(MODULE, "dispatch", return_value=0) as dispatch,
            patch("sys.argv", [str(SCRIPT), "--account", "codex"]),
            patch("sys.stdin", io.StringIO(payload)),
            patch("sys.stdout", io.StringIO()),
        ):
            self.assertEqual(MODULE.main(), 0)
            handles.assert_not_called()
            dispatch.assert_called_once()

    def test_t3_handles_session_checks_watcher_and_supports_codex(self):
        import agents_alert_providers as providers
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "statev2.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript("""
                    CREATE TABLE orchestration_v2_projection_provider_threads (
                        provider_thread_id TEXT, driver TEXT, payload_json TEXT
                    );
                    CREATE TABLE orchestration_v2_projection_runs (
                        provider_thread_id TEXT, status TEXT, completed_at TEXT
                    );
                    INSERT INTO orchestration_v2_projection_provider_threads VALUES
                        ('pt-1', 'codex', '{"nativeThreadRef":{"nativeId":"codex-sess"}}');
                    INSERT INTO orchestration_v2_projection_runs VALUES ('pt-1', 'running', NULL);
                """)
            with patch.object(providers, "t3_enabled", return_value=True):
                with patch.object(providers, "t3_watcher_active", return_value=False):
                    self.assertFalse(providers.t3_handles_session("codex", "codex-sess", database))
                with patch.object(providers, "t3_watcher_active", return_value=True):
                    self.assertTrue(providers.t3_handles_session("codex", "codex-sess", database))

    def test_t3_scratch_thread_uses_thread_title_for_desktop_and_phone(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment_file = root / "environment-id"
            environment_file.write_text("env-1\n", encoding="ascii")
            database = root / "statev2.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript("""
                    CREATE TABLE projection_projects (
                        project_id TEXT, title TEXT, workspace_root TEXT
                    );
                    CREATE TABLE orchestration_v2_projection_threads (
                        thread_id TEXT, project_id TEXT, title TEXT, deleted_at TEXT, payload_json TEXT
                    );
                    CREATE TABLE orchestration_v2_projection_provider_threads (
                        thread_id TEXT, driver TEXT, provider_instance_id TEXT,
                        payload_json TEXT, updated_at TEXT
                    );
                """)
                connection.execute(
                    "INSERT INTO projection_projects VALUES (?, ?, ?)",
                    ("scratch-project", "No project", "/home/test/.t3/scratch"),
                )
                connection.execute(
                    "INSERT INTO orchestration_v2_projection_threads VALUES (?, ?, ?, NULL, ?)",
                    (
                        "t3-thread-1",
                        "scratch-project",
                        "Configure Google AI Pro for T3 Code",
                        json.dumps({
                            "title": "Configure Google AI Pro for T3 Code",
                            "worktreePath": "/home/test/.t3/scratch/2026-11-20-i-want-to-setup-my-1e93e584",
                        }),
                    ),
                )
                connection.execute(
                    "INSERT INTO orchestration_v2_projection_provider_threads VALUES (?, ?, ?, ?, ?)",
                    (
                        "t3-thread-1",
                        "codex",
                        "codex",
                        '{"nativeThreadRef":{"nativeId":"codex-session-1"}}',
                        "2026-11-22T19:00:00Z",
                    ),
                )

            payload = {
                "session_id": "codex-session-1",
                "turn_id": "turn-1",
                "cwd": "/home/test/.t3/scratch/2026-11-20-i-want-to-setup-my-1e93e584",
                "model": "gpt-6.2-sol",
                "last_assistant_message": "All set.",
            }
            with (
                patch.object(MODULE, "T3_ENVIRONMENT_ID_FILE", environment_file),
                patch.object(MODULE, "T3_CURRENT_DB", database),
                patch.object(MODULE, "T3_LEGACY_DB", root / "missing.sqlite"),
                patch.object(MODULE, "t3_enabled", return_value=True),
                patch.object(MODULE, "remember_dispatch", return_value=True),
                patch.object(MODULE, "phone_configured", return_value=True),
                patch.object(MODULE, "launch", return_value=True) as launch,
                patch.object(MODULE, "log"),
            ):
                self.assertEqual(MODULE.dispatch(payload, "codex", "completion"), 0)

        self.assertEqual(launch.call_count, 2)
        for call in launch.call_args_list:
            command = call.args[0]
            self.assertEqual(
                command[command.index("--title") + 1],
                "Finished ✅ · Configure Google AI Pro for T3 Code",
            )
            self.assertEqual(
                command[command.index("--body") + 1],
                "codex · gpt-6.2-sol\nAll set.",
            )

    def test_t3_project_thread_shows_thread_title_and_project_in_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment_file = root / "environment-id"
            environment_file.write_text("env-1\n", encoding="ascii")
            database = root / "statev2.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript("""
                    CREATE TABLE projection_projects (
                        project_id TEXT, title TEXT, workspace_root TEXT
                    );
                    CREATE TABLE orchestration_v2_projection_threads (
                        thread_id TEXT, project_id TEXT, title TEXT, deleted_at TEXT, payload_json TEXT
                    );
                """)
                connection.execute(
                    "INSERT INTO projection_projects VALUES (?, ?, ?)",
                    ("project-1", "Aresto", "/home/test/Documents/Projects/aresto"),
                )
                connection.execute(
                    "INSERT INTO orchestration_v2_projection_threads VALUES (?, ?, ?, NULL, ?)",
                    (
                        "t3-thread-2",
                        "project-1",
                        "Refactor   checkout\nflow",
                        json.dumps({"title": "Refactor   checkout\nflow"}),
                    ),
                )

            payload = {
                "t3_thread_id": "t3-thread-2",
                "session_id": "native-1",
                "turn_id": "turn-1",
                "cwd": "/home/test/Documents/Projects/aresto",
                "model": "gemini-4-neon",
                "last_assistant_message": "Done.",
            }
            with (
                patch.object(MODULE, "T3_ENVIRONMENT_ID_FILE", environment_file),
                patch.object(MODULE, "T3_CURRENT_DB", database),
                patch.object(MODULE, "T3_LEGACY_DB", root / "missing.sqlite"),
                patch.object(MODULE, "t3_enabled", return_value=True),
                patch.object(MODULE, "remember_dispatch", return_value=True),
                patch.object(MODULE, "phone_configured", return_value=True),
                patch.object(MODULE, "launch", return_value=True) as launch,
                patch.object(MODULE, "log"),
            ):
                self.assertEqual(MODULE.dispatch(payload, "antigravity", "completion"), 0)

        self.assertEqual(launch.call_count, 2)
        for call in launch.call_args_list:
            command = call.args[0]
            self.assertEqual(
                command[command.index("--title") + 1],
                "Finished ✅ · Refactor checkout flow",
            )
            self.assertEqual(
                command[command.index("--body") + 1],
                "Aresto · Antigravity · gemini-4-neon\nDone.",
            )

    def test_codex_session_index_fallback_uses_latest_thread_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex"
            codex_home.mkdir()
            (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
            (codex_home / "session_index.jsonl").write_text(
                "\n".join([
                    json.dumps({"id": "codex-cli-1", "thread_name": "Initial prompt snippet..."}),
                    json.dumps({"id": "codex-cli-1", "thread_name": "Fix OAuth callback"}),
                ]) + "\n",
                encoding="utf-8",
            )
            payload = {
                "session_id": "codex-cli-1",
                "turn_id": "turn-1",
                "cwd": "/home/test/Documents/Projects/my-app",
                "model": "gpt-6.2-sol",
                "last_assistant_message": "Fixed.",
            }
            with (
                patch.object(MODULE, "T3_CURRENT_DB", root / "missing-v2.sqlite"),
                patch.object(MODULE, "T3_LEGACY_DB", root / "missing-v1.sqlite"),
                patch.object(MODULE, "t3_thread_target", return_value=None),
                patch.object(MODULE, "remember_dispatch", return_value=True),
                patch.object(MODULE, "phone_configured", return_value=True),
                patch.object(MODULE, "launch", return_value=True) as launch,
                patch.object(MODULE, "log"),
                patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False),
            ):
                self.assertEqual(MODULE.dispatch(payload, "codex", "completion"), 0)

        self.assertEqual(launch.call_count, 2)
        command = launch.call_args_list[0].args[0]
        self.assertEqual(command[command.index("--title") + 1], "Finished ✅ · Fix OAuth callback")
        self.assertEqual(command[command.index("--body") + 1], "my-app · codex · gpt-6.2-sol\nFixed.")

    def test_scratch_thread_without_title_never_shows_scratch_folder_slug(self):
        payload = {
            "session_id": "unknown-session",
            "turn_id": "turn-1",
            "cwd": "/home/test/.t3/scratch/2026-11-20-i-want-to-setup-my-1e93e584",
            "model": "gpt-6.2-sol",
            "last_assistant_message": "Done.",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch.object(MODULE, "T3_CURRENT_DB", root / "missing-v2.sqlite"),
                patch.object(MODULE, "T3_LEGACY_DB", root / "missing-v1.sqlite"),
                patch.object(MODULE, "t3_thread_target", return_value=None),
                patch.object(MODULE, "codex_session_title", return_value=""),
                patch.object(MODULE, "remember_dispatch", return_value=True),
                patch.object(MODULE, "phone_configured", return_value=False),
                patch.object(MODULE, "launch", return_value=True) as launch,
                patch.object(MODULE, "log"),
            ):
                self.assertEqual(MODULE.dispatch(payload, "codex", "completion"), 0)

        command = launch.call_args_list[0].args[0]
        self.assertEqual(command[command.index("--title") + 1], "Finished ✅ · Agents Alert")
        self.assertEqual(command[command.index("--body") + 1], "codex · gpt-6.2-sol\nDone.")


if __name__ == "__main__":
    unittest.main()
