import importlib.machinery
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "codex-alert"
sys.path.insert(0, str(SCRIPT.parent))

import codex_alert_common as common


MODULE = importlib.machinery.SourceFileLoader("codex_alert_cli", str(SCRIPT)).load_module()


class HookSetupTests(unittest.TestCase):
    def test_decodes_avahi_service_name_escapes_as_utf8(self):
        self.assertEqual(
            MODULE.decode_avahi_field(
                r"Codex\032Alert\032\194\183\032Xiaomi\032M2101K6G"
            ),
            "Codex Alert · Xiaomi M2101K6G",
        )

    def test_decodes_avahi_delimiter_and_backslash_escapes(self):
        self.assertEqual(
            MODULE.decode_avahi_field(r"Phone\059Lab\092One"),
            r"Phone;Lab\One",
        )

    def test_discovery_decodes_the_phone_name(self):
        result = type("Result", (), {
            "returncode": 0,
            "stdout": (
                "=;enp8s0;IPv4;Codex\\032Alert\\032\\194\\183\\032Phone;"
                "_codexalert._tcp;local;phone.local;192.168.0.2;24601;paired=0\n"
            ),
        })()
        with (
            patch.object(MODULE.shutil, "which", return_value="/usr/bin/avahi-browse"),
            patch.object(MODULE, "run", return_value=result),
        ):
            self.assertEqual(
                MODULE.discover_phones(),
                [("Codex Alert · Phone", "192.168.0.2")],
            )

    def test_discovery_uses_auth_marker_not_directory_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authenticated = root / "work-account-any-name"
            misleading = root / ".codex_shadow"
            authenticated.mkdir()
            misleading.mkdir()
            (authenticated / "auth.json").write_text("{}\n", encoding="utf-8")
            (misleading / "config.toml").write_text("model = 'test'\n", encoding="utf-8")
            duplicate = root / ".codex-link"
            duplicate.symlink_to(authenticated, target_is_directory=True)

            with (
                patch.object(common, "HOME", root),
                patch.dict("os.environ", {"CODEX_HOME": "", "CODEX_ALERT_CODEX_HOMES": ""}),
            ):
                homes = common.codex_homes()
                self.assertEqual(len(homes), 1)
                self.assertEqual(homes[0].resolve(), authenticated.resolve())

    def test_sync_preserves_other_hooks_and_deduplicates_ours(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "hooks.json"
            path.write_text(
                json.dumps(
                    {
                        "unrelated": {"keep": True},
                        "hooks": {
                            "Stop": [
                                {
                                    "matcher": "important",
                                    "hooks": [
                                        {"type": "command", "command": "/usr/bin/other"},
                                        {"type": "command", "command": "/old/codex-notify-stop"},
                                    ],
                                },
                                {
                                    "hooks": [
                                        {"type": "command", "command": "/duplicate/codex-notify-stop"}
                                    ]
                                },
                            ],
                            "Start": [{"hooks": [{"command": "/usr/bin/start-hook"}]}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            MODULE.sync_hook_file(path)
            value = json.loads(path.read_text(encoding="utf-8"))
            stop_entries = [
                hook
                for group in value["hooks"]["Stop"]
                for hook in group.get("hooks", [])
                if MODULE.is_codex_alert_hook(hook)
            ]

            self.assertEqual(value["unrelated"], {"keep": True})
            self.assertEqual(value["hooks"]["Start"][0]["hooks"][0]["command"], "/usr/bin/start-hook")
            self.assertEqual(len(stop_entries), 1)
            self.assertEqual(stop_entries[0]["command"], MODULE.HOOK_COMMAND)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_json_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "hooks.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                MODULE.sync_hook_file(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_sync_through_symlink_updates_target_and_preserves_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = root / "main-hooks.json"
            shadow = root / "shadow-hooks.json"
            main.write_text('{"description":"shared"}\n', encoding="utf-8")
            shadow.symlink_to(main)

            MODULE.sync_hook_file(shadow)

            self.assertTrue(shadow.is_symlink())
            self.assertEqual(shadow.resolve(), main)
            value = json.loads(main.read_text(encoding="utf-8"))
            self.assertEqual(value["description"], "shared")
            self.assertEqual(value["hooks"]["Stop"][0]["hooks"][0]["command"], MODULE.HOOK_COMMAND)

            inode = main.stat().st_ino
            self.assertFalse(MODULE.sync_hook_file(shadow))
            self.assertEqual(main.stat().st_ino, inode)
            self.assertTrue(shadow.is_symlink())

    def test_dangling_hook_symlink_fails_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            shadow = Path(temporary) / "hooks.json"
            shadow.symlink_to(Path(temporary) / "missing-hooks.json")
            with self.assertRaises(RuntimeError):
                MODULE.sync_hook_file(shadow)
            self.assertTrue(shadow.is_symlink())

    def test_sync_deduplicates_shared_hook_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main_home = root / ".codex"
            shadow_home = root / ".codex2"
            main_home.mkdir()
            shadow_home.mkdir()
            main_hooks = main_home / "hooks.json"
            main_hooks.write_text("{}\n", encoding="utf-8")
            (shadow_home / "hooks.json").symlink_to(main_hooks)

            with (
                patch.object(MODULE, "codex_homes", return_value=[main_home, shadow_home]),
                patch.object(MODULE, "sync_hook_file", wraps=MODULE.sync_hook_file) as sync,
            ):
                self.assertEqual(MODULE.sync_hooks(quiet=True), 0)

            sync.assert_called_once_with(main_hooks)
            self.assertTrue((shadow_home / "hooks.json").is_symlink())

    def test_cross_desktop_watcher_syncs_immediately(self):
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "watch.lock"
            with (
                patch.object(MODULE, "WATCH_LOCK", lock),
                patch.object(MODULE, "sync_hooks", return_value=0) as sync,
                patch.object(MODULE.time, "sleep", side_effect=KeyboardInterrupt),
                self.assertRaises(KeyboardInterrupt),
            ):
                MODULE.watch_hooks()

            sync.assert_called_once_with(quiet=True)


if __name__ == "__main__":
    unittest.main()
