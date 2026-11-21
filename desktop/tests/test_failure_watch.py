import importlib.machinery
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "codex-alert-failure-watch"
sys.path.insert(0, str(SCRIPT.parent))
MODULE = importlib.machinery.SourceFileLoader(
    "codex_alert_failure_watch", str(SCRIPT)
).load_module()


def context():
    return {
        "path": "/tmp/rollout.jsonl",
        "account": "codex2",
        "session_id": "session-1",
        "cwd": "/tmp/project",
        "originator": "t3code_desktop",
        "source_json": '"vscode"',
        "thread_source": "",
        "history_mode": "paginated",
        "model": "gpt-5.6-sol",
        "model_turn_id": "turn-1",
    }


def row(payload_type, **payload):
    return {
        "type": "event_msg",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"type": payload_type, **payload},
    }


class FailureEventTests(unittest.TestCase):
    def test_terminal_failure_is_dispatched_with_context(self):
        calls = []
        with patch.object(MODULE, "account_for_session", side_effect=lambda _, value: value):
            accepted = MODULE.handle_record(
                context(),
                row("task_complete", turn_id="turn-1", error={"message": "quota exhausted"}),
                lambda payload, account: calls.append((payload, account)) or True,
            )

        self.assertTrue(accepted)
        self.assertEqual(len(calls), 1)
        payload, account = calls[0]
        self.assertEqual(account, "codex2")
        self.assertEqual(payload["session_id"], "session-1")
        self.assertEqual(payload["turn_id"], "turn-1")
        self.assertEqual(payload["model"], "gpt-5.6-sol")
        self.assertEqual(payload["error"], "quota exhausted")

    def test_success_interruption_and_tool_failure_are_ignored(self):
        calls = []
        dispatch = lambda payload, account: calls.append((payload, account)) or True
        self.assertTrue(MODULE.handle_record(
            context(), row("task_complete", turn_id="turn-1", error=None), dispatch
        ))
        self.assertTrue(MODULE.handle_record(
            context(), row("task_complete", turn_id="turn-1", status="interrupted"), dispatch
        ))
        self.assertTrue(MODULE.handle_record(
            context(), row("task_complete", turn_id="turn-1", status="cancelled",
                           error={"message": "cancelled"}), dispatch
        ))
        self.assertTrue(MODULE.handle_record(
            context(), row("item_completed", turn_id="turn-1", status="failed",
                           error={"message": "command failed"}), dispatch
        ))
        self.assertEqual(calls, [])

    def test_subagent_and_explicit_ephemeral_sessions_are_ignored(self):
        calls = []
        dispatch = lambda payload, account: calls.append((payload, account)) or True
        subagent = context()
        subagent["thread_source"] = "subagent"
        ephemeral = context()
        ephemeral["history_mode"] = "ephemeral"
        failure = row("task_complete", turn_id="turn-1", error={"message": "failed"})

        self.assertTrue(MODULE.handle_record(subagent, failure, dispatch))
        self.assertTrue(MODULE.handle_record(ephemeral, failure, dispatch))
        self.assertEqual(calls, [])

    def test_turn_model_is_not_reused_for_a_different_turn(self):
        calls = []
        with patch.object(MODULE, "account_for_session", side_effect=lambda _, value: value):
            MODULE.handle_record(
                context(),
                row("task_complete", turn_id="turn-2", error={"message": "failed"}),
                lambda payload, account: calls.append(payload) or True,
            )
        self.assertEqual(calls[0]["model"], "")

    def test_t3_provider_instance_maps_shared_sessions_to_numbered_account(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "state.sqlite"
            settings = root / "settings.json"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE provider_session_runtime "
                    "(thread_id TEXT, provider_instance_id TEXT, provider_name TEXT, "
                    "resume_cursor_json TEXT, last_seen_at TEXT)"
                )
                connection.execute(
                    "INSERT INTO provider_session_runtime VALUES (?, ?, ?, ?, ?)",
                    ("t3-thread", "codex_account6", "codex", '{"threadId":"session-1"}', "2026"),
                )
            settings.write_text(json.dumps({
                "providerInstances": {
                    "codex_account6": {
                        "config": {"shadowHomePath": "/home/test/.codex6"}
                    }
                }
            }), encoding="utf-8")

            self.assertEqual(
                MODULE.account_for_session(
                    "session-1", "codex", state_db=database, settings_file=settings
                ),
                "codex6",
            )


class OffsetTests(unittest.TestCase):
    @staticmethod
    def records(session="session-1", turn="turn-1", error="failed"):
        return [
            {
                "type": "session_meta",
                "payload": {
                    "id": session,
                    "cwd": "/tmp/project",
                    "originator": "t3code_desktop",
                    "source": "vscode",
                    "history_mode": "paginated",
                },
            },
            {
                "type": "turn_context",
                "payload": {"turn_id": turn, "cwd": "/tmp/project", "model": "model-1"},
            },
            row("task_complete", turn_id=turn, error={"message": error}),
        ]

    @staticmethod
    def append(path, records, final_newline=True):
        rendered = "\n".join(json.dumps(record) for record in records)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(rendered + ("\n" if final_newline else ""))

    def test_offsets_make_failure_delivery_exactly_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = root / "rollout.jsonl"
            rollout.touch()
            calls = []
            with MODULE.connect_db(root / "state.sqlite3") as connection:
                self.append(rollout, self.records())
                MODULE.process_file(
                    connection, rollout, "codex",
                    lambda payload, account: calls.append((payload, account)) or True,
                )
                MODULE.process_file(
                    connection, rollout, "codex",
                    lambda payload, account: calls.append((payload, account)) or True,
                )

            self.assertEqual(len(calls), 1)

    def test_partial_record_waits_for_newline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = root / "rollout.jsonl"
            records = self.records()
            self.append(rollout, records[:2])
            self.append(rollout, records[2:], final_newline=False)
            calls = []
            with MODULE.connect_db(root / "state.sqlite3") as connection:
                MODULE.process_file(
                    connection, rollout, "codex",
                    lambda payload, account: calls.append(payload) or True,
                )
                self.assertEqual(calls, [])
                with rollout.open("a", encoding="utf-8") as stream:
                    stream.write("\n")
                MODULE.process_file(
                    connection, rollout, "codex",
                    lambda payload, account: calls.append(payload) or True,
                )
            self.assertEqual(len(calls), 1)

    def test_replacement_inode_and_truncation_restart_at_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = root / "rollout.jsonl"
            calls = []
            with MODULE.connect_db(root / "state.sqlite3") as connection:
                self.append(rollout, self.records(error="first"))
                MODULE.process_file(
                    connection, rollout, "codex",
                    lambda payload, account: calls.append(payload["error"]) or True,
                )

                replacement = root / "replacement.jsonl"
                self.append(replacement, self.records(session="session-2", error="second"))
                os.replace(replacement, rollout)
                MODULE.process_file(
                    connection, rollout, "codex",
                    lambda payload, account: calls.append(payload["error"]) or True,
                )

                rollout.write_text("", encoding="utf-8")
                self.append(rollout, self.records(session="session-3", error="third"))
                MODULE.process_file(
                    connection, rollout, "codex",
                    lambda payload, account: calls.append(payload["error"]) or True,
                )

            self.assertEqual(calls, ["first"])

    def test_reboot_rebases_offsets_and_only_new_failures_alert(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = root / "rollout.jsonl"
            self.append(rollout, self.records())
            connection = MODULE.connect_db(root / "state.sqlite3")
            try:
                MODULE.initialize(connection, [(root, "codex")], force=True)
                connection.execute('UPDATE rollout_files SET device = -1, offset = 0')
                connection.commit()
                MODULE.initialize(connection, [(root, "codex")], force=True)
                calls = []
                deliver = lambda payload, account: calls.append(payload) or True
                MODULE.process_file(connection, rollout, "codex", deliver)
                self.assertEqual(calls, [])
                self.append(rollout, [row('task_complete', turn_id='new', error={'message':'new failure'})])
                MODULE.process_file(connection, rollout, "codex", deliver)
                self.assertEqual(len(calls), 1)
            finally:
                connection.close()

    def test_old_discovered_file_does_not_alert(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = self.records()
            records[-1]['timestamp'] = '2026-01-01T00:00:00Z'
            rollout = root / 'old.jsonl'
            self.append(rollout, records)
            connection = MODULE.connect_db(root / 'state.sqlite3')
            try:
                calls = []
                MODULE.process_file(connection, rollout, 'codex', lambda p,a: calls.append(p) or True)
                self.assertEqual(calls, [])
            finally:
                connection.close()

    def test_explicit_input_request(self):
        calls = []
        ctx = context()
        ctx['originator'] = 'codex_cli'
        request = {'type':'response_item', 'payload':{'type':'function_call',
            'name':'request_user_input', 'call_id':'question-1',
            'arguments':json.dumps({'questions':[{'question':'Which environment?'}]})}}
        MODULE.handle_record(ctx, request, lambda p,a: calls.append(p) or True)
        self.assertEqual(calls[0]['request_id'], 'question-1')
        self.assertEqual(calls[0]['input_message'], 'Which environment?')

    def test_async_user_message_and_status_only_failure_are_read_from_rollout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = root / "rollout.jsonl"
            records = self.records()[:2]
            records.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "send_message_to_user_async",
                    "call_id": "call-1",
                    "arguments": '{"message":"Please check the provider settings."}',
                },
            })
            records.append(row("task_complete", turn_id="turn-1", status="failed"))
            self.append(rollout, records)
            calls = []
            with closing(MODULE.connect_db(root / "state.sqlite3")) as connection:
                MODULE.process_file(
                    connection, rollout, "codex",
                    lambda payload, account: calls.append(payload) or True,
                )
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["request_id"], "call-1")
            self.assertEqual(calls[0]["input_message"], "Please check the provider settings.")
            self.assertEqual(calls[1]["error"], "The Codex task failed.")


class T3EventTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "statev2.sqlite"
        self.connection = sqlite3.connect(self.database)
        self.addCleanup(self.connection.close)
        self.connection.executescript("""
            CREATE TABLE orchestration_events (
                sequence INTEGER PRIMARY KEY, stream_id TEXT, aggregate_kind TEXT,
                occurred_at TEXT, event_type TEXT, payload_json TEXT
            );
            CREATE TABLE orchestration_v2_projection_threads (
                thread_id TEXT, project_id TEXT, active_provider_thread_id TEXT, deleted_at TEXT,
                provider_instance_id TEXT, default_provider TEXT, payload_json TEXT
            );
            CREATE TABLE projection_projects (project_id TEXT, workspace_root TEXT);
            CREATE TABLE orchestration_v2_projection_runs (
                run_id TEXT, provider_instance_id TEXT, payload_json TEXT
            );
            CREATE TABLE orchestration_v2_projection_provider_turns (
                provider_turn_id TEXT, provider_thread_id TEXT, payload_json TEXT
            );
            CREATE TABLE orchestration_v2_projection_provider_threads (
                provider_thread_id TEXT, provider_instance_id TEXT, driver TEXT, payload_json TEXT
            );
            CREATE TABLE orchestration_v2_projection_turn_items (
                turn_item_id TEXT, thread_id TEXT, run_id TEXT, node_id TEXT, type TEXT,
                status TEXT, updated_at TEXT, ordinal INTEGER, provider_turn_id TEXT,
                payload_json TEXT, provider_thread_id TEXT
            );
            INSERT INTO projection_projects VALUES ('project', '/tmp/project');
            INSERT INTO orchestration_v2_projection_threads VALUES
                ('t3-thread', 'project', 'provider-thread', NULL, 'opencode', 'opencode', '{}');
            INSERT INTO orchestration_v2_projection_provider_threads VALUES
                ('provider-thread', 'opencode', 'opencode',
                 '{"nativeThreadRef":{"nativeId":"native-session"}}');
            INSERT INTO orchestration_v2_projection_provider_turns VALUES
                ('provider-turn', 'provider-thread', '{"nativeTurnRef":{"nativeId":"native-turn"}}');
            INSERT INTO orchestration_v2_projection_runs VALUES
                ('run-1', 'opencode', '{"modelSelection":{"model":"model-1"}}');
        """)
        settings = patch.object(MODULE, "T3_SETTINGS_FILE", self.database.with_name("settings.json"))
        settings.start()
        self.addCleanup(settings.stop)
        self.events = MODULE.T3Events()
        self.calls = []

    def publish(self, event_type, payload, stamp=None):
        stamp = stamp or datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            "INSERT INTO orchestration_events VALUES (NULL, 't3-thread', 'thread', ?, ?, ?)",
            (stamp, event_type, json.dumps(payload)),
        )
        self.connection.commit()

    def request(self, kind, status="waiting", **details):
        item_id = f"{kind}-{status}"
        self.connection.execute(
            "INSERT INTO orchestration_v2_projection_turn_items "
            "(turn_item_id, status) VALUES (?, ?)", (item_id, status),
        )
        self.publish("turn-item.updated", {
            "id": item_id, "type": kind, "status": "waiting",
            "runId": "run-1", "providerTurnId": "provider-turn", **details,
        })

    def poll(self):
        self.events.poll(self.database, lambda payload, account: self.calls.append((payload, account)) or True)

    def test_only_new_pending_requests_and_terminal_failures_are_forwarded(self):
        self.request("approval_request", prompt="Old approval")
        self.poll()
        self.assertEqual(self.calls, [])
        self.connection.execute("DELETE FROM orchestration_v2_projection_turn_items")

        self.request("approval_request", requestId="approval-1", prompt="Allow this command?")
        self.request("user_input_request", status="completed", requestId="answered")
        self.request("user_input_request", nativeItemRef={"nativeId": "call-1"},
                     questions=[{"question": "Which environment?"}])
        self.publish("run.updated", {"id": "run-1", "status": "cancelled"})
        self.connection.execute(
            "INSERT INTO orchestration_v2_projection_turn_items VALUES "
            "('error-1', 't3-thread', 'run-1', 'root-node', 'error', 'failed', '', 1, "
            " 'provider-turn', ?, 'provider-thread')",
            ('{"failure":{"message":"Provider unavailable"}}',),
        )
        self.publish("run.updated", {
            "id": "run-1", "status": "failed", "rootNodeId": "root-node",
        })
        self.poll()
        self.poll()

        self.assertEqual(len(self.calls), 3)
        approval, question, failure = [payload for payload, _ in self.calls]
        self.assertEqual((approval["request_id"], approval["input_message"]),
                         ("approval-1", "Allow this command?"))
        self.assertEqual((question["request_id"], question["input_message"]),
                         ("call-1", "Which environment?"))
        self.assertEqual(failure, {
            "session_id": "native-session", "turn_id": "native-turn", "t3_thread_id": "t3-thread",
            "cwd": "/tmp/project", "model": "model-1", "error": "Provider unavailable",
        })
        self.assertTrue(all(account == "opencode" for _, account in self.calls))

    def test_failed_forward_is_retried_and_old_events_stay_silent(self):
        self.poll()
        self.publish("run.updated", {"id": "run-1", "status": "failed"}, "2026-01-01T00:00:00Z")
        self.request("approval_request", prompt="Allow?")
        self.events.poll(self.database, lambda _payload, _account: False)
        self.poll()
        self.poll()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0]["input_message"], "Allow?")

    def test_t3_sends_completions_for_claude_and_antigravity(self):
        self.poll()
        self.connection.execute(
            "INSERT INTO orchestration_v2_projection_turn_items VALUES "
            "('assistant-1', 't3-thread', 'run-1', 'root-node', 'assistant_message', "
            "'completed', '', 1, 'provider-turn', ?, 'provider-thread')",
            ('{"text":"Implemented the fix."}',),
        )
        for driver in ("opencode", "codex", "antigravity", "claudeAgent"):
            self.connection.execute(
                "UPDATE orchestration_v2_projection_provider_threads SET driver = ?", (driver,),
            )
            self.publish("run.updated", {
                "id": "run-1", "status": "completed", "providerThreadId": "provider-thread",
            })
            self.poll()

        self.assertEqual([account for _, account in self.calls], ["antigravity", "claude-code"])
        for payload, _ in self.calls:
            self.assertEqual(payload["last_assistant_message"], "Implemented the fix.")
            self.assertEqual(payload["t3_thread_id"], "t3-thread")
            self.assertEqual(payload["turn_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
