import importlib.machinery
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "codex-notify-stop"
MODULE = importlib.machinery.SourceFileLoader("codex_notify_stop", str(SCRIPT)).load_module()


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
            value.startswith("Codex failed")
            for value in launch.call_args_list[0].args[0]
        ))


if __name__ == "__main__":
    unittest.main()
