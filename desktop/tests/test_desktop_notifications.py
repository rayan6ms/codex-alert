import importlib.machinery
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "codex-notify-stop-desktop"
sys.path.insert(0, str(SCRIPT.parent))
MODULE = importlib.machinery.SourceFileLoader(
    "codex_notify_stop_desktop", str(SCRIPT)
).load_module()


class DesktopNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        state = Path(self.temporary.name)
        replacements = {
            "STATE_DIR": state,
            "ID_FILE": state / "notification-id",
            "LOCK_FILE": state / "notification.lock",
        }
        self.patchers = [patch.object(MODULE, name, value) for name, value in replacements.items()]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    def test_freedesktop_notification_uses_discovered_tool_and_escapes_markup(self):
        result = subprocess.CompletedProcess([], 0, stdout="42\n", stderr="")
        with (
            patch.object(MODULE.shutil, "which", return_value="/custom/bin/notify-send"),
            patch.object(MODULE.subprocess, "run", return_value=result) as run,
        ):
            returncode, error, notification_id = MODULE.notify("Done <now>", "A & B")

        self.assertEqual((returncode, error, notification_id), (0, "", "42"))
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/custom/bin/notify-send")
        self.assertIn(f"--app-icon={MODULE.APP_ICON}", command)
        self.assertIn(f"--icon={MODULE.APP_ICON}", command)
        self.assertIn("--hint=string:desktop-entry:dev.rayan.codexalert", command)
        self.assertIn("Done &lt;now&gt;", command)
        self.assertIn("A &amp; B", command)
        self.assertEqual(MODULE.ID_FILE.read_text(encoding="ascii"), "42\n")

    def test_missing_notification_tool_returns_a_clear_error(self):
        with patch.object(MODULE.shutil, "which", return_value=None):
            self.assertEqual(
                MODULE.notify("Done", "Body"),
                (1, "notify-send is not installed", ""),
            )

    def test_older_notify_send_falls_back_without_replacement_options(self):
        unsupported = subprocess.CompletedProcess([], 1, stdout="", stderr="unknown option")
        delivered = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with (
            patch.object(MODULE.shutil, "which", return_value="/usr/bin/notify-send"),
            patch.object(MODULE.subprocess, "run", side_effect=(unsupported, delivered)) as run,
        ):
            self.assertEqual(MODULE.notify("Done", "Body"), (0, "", ""))

        fallback = run.call_args_list[1].args[0]
        self.assertNotIn("--print-id", fallback)
        self.assertFalse(any(argument.startswith("--replace-id=") for argument in fallback))
        self.assertIn(f"--app-icon={MODULE.APP_ICON}", fallback)

    def test_sound_falls_back_to_paplay(self):
        sound = Path(self.temporary.name) / "complete.oga"
        sound.write_bytes(b"sound")

        def find_program(name):
            return "/usr/bin/paplay" if name == "paplay" else None

        result = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with (
            patch.object(MODULE, "SOUND_CANDIDATES", (sound,)),
            patch.object(MODULE.shutil, "which", side_effect=find_program),
            patch.object(MODULE.subprocess, "run", return_value=result) as run,
        ):
            self.assertEqual(MODULE.play_sound(), (0, ""))

        self.assertEqual(run.call_args.args[0], ["/usr/bin/paplay", str(sound)])


if __name__ == "__main__":
    unittest.main()
