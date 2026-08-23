import importlib.machinery
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "codex-notify-stop"
sys.path.insert(0, str(SCRIPT.parent))
MODULE = importlib.machinery.SourceFileLoader("codex_notify_stop", str(SCRIPT)).load_module()


class AccountNameTests(unittest.TestCase):
    def test_primary_home(self):
        with patch.dict(os.environ, {"CODEX_HOME": "/home/rayan/.codex"}, clear=False):
            self.assertEqual(MODULE.account_name("fallback"), "codex")

    def test_numbered_home(self):
        with patch.dict(os.environ, {"CODEX_HOME": "/home/rayan/.codex6"}, clear=False):
            self.assertEqual(MODULE.account_name("fallback"), "codex6")

    def test_shadow_home(self):
        with patch.dict(os.environ, {"CODEX_HOME": "/home/rayan/.codex_p3"}, clear=False):
            self.assertEqual(MODULE.account_name("fallback"), "codex_p3")

    def test_completion_id_is_stable_and_account_scoped(self):
        payload = {"session_id": "session", "turn_id": "turn"}
        first = MODULE.completion_id(payload, "codex")
        self.assertEqual(first, MODULE.completion_id(payload, "codex"))
        self.assertNotEqual(first, MODULE.completion_id(payload, "codex2"))

    def test_t3_thread_target_maps_provider_session_without_writing_t3_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            environment_file = state / "environment-id"
            database = state / "state.sqlite"
            environment_file.write_text("environment-1\n", encoding="ascii")
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "CREATE TABLE provider_session_runtime "
                    "(thread_id TEXT, provider_name TEXT, resume_cursor_json TEXT)"
                )
                connection.execute(
                    "CREATE TABLE projection_threads (thread_id TEXT, updated_at TEXT)"
                )
                connection.execute(
                    "INSERT INTO projection_threads VALUES (?, ?)",
                    ("t3-thread-1", "2026-08-21T00:00:00Z"),
                )
                connection.execute(
                    "INSERT INTO provider_session_runtime VALUES (?, ?, ?)",
                    ("t3-thread-1", "codex", '{"threadId":"codex-session-1"}'),
                )
                connection.commit()
            with (
                patch.object(MODULE, "T3_ENVIRONMENT_ID_FILE", environment_file),
                patch.object(MODULE, "T3_STATE_DB", database),
                patch.object(MODULE, "t3_enabled", return_value=True),
            ):
                self.assertEqual(
                    MODULE.t3_thread_target({"session_id": "codex-session-1"}),
                    ("environment-1", "t3-thread-1"),
                )
                self.assertIsNone(MODULE.t3_thread_target({"session_id": "missing"}))


class NotificationTextTests(unittest.TestCase):
    def test_removes_common_inline_markdown(self):
        source = (
            "## **Finished**\n\n"
            "Updated [`server.py`](/tmp/server.py:10) and "
            "[the documentation](https://example.com). ~~Old path removed.~~"
        )
        self.assertEqual(
            MODULE.markdown_to_plain_text(source),
            "Finished\n\nUpdated server.py and the documentation. Old path removed.",
        )

    def test_normalizes_lists_quotes_tasks_and_tables(self):
        source = (
            "> Results\n"
            "- [x] **Desktop** fixed\n"
            "2. _Mobile_ fixed\n\n"
            "| Target | State |\n"
            "| :--- | ---: |\n"
            "| LAN | `working` |"
        )
        self.assertEqual(
            MODULE.markdown_to_plain_text(source),
            "Results\n• Desktop fixed\n• Mobile fixed\n\n"
            "Target · State\nLAN · working",
        )

    def test_removes_fences_html_escapes_and_ansi(self):
        source = (
            "```json\n{\"state\": \"ok\"}\n```\n"
            "Use \\*literal\\* &amp; <strong>safe</strong>.\n"
            "\x1b[31mNo color\x1b[0m"
        )
        self.assertEqual(
            MODULE.markdown_to_plain_text(source),
            '{"state": "ok"}\nUse *literal* & safe.\nNo color',
        )

    def test_preserves_identifiers_and_plain_punctuation(self):
        source = "Keep snake_case, a*b, #tag, x < y, and https://example.com/a_b."
        self.assertEqual(MODULE.markdown_to_plain_text(source), source)


if __name__ == "__main__":
    unittest.main()
