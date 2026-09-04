import importlib.machinery
import json
import os
import sqlite3
import sys
import tempfile
import unittest
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
                    "(provider_instance_id TEXT, provider_name TEXT, resume_cursor_json TEXT)"
                )
                connection.execute(
                    "INSERT INTO provider_session_runtime VALUES (?, ?, ?)",
                    ("codex_account6", "codex", '{"threadId":"session-1"}'),
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

            self.assertEqual(calls, ["first", "second", "third"])


if __name__ == "__main__":
    unittest.main()
