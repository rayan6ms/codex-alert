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

    def test_stale_managed_hook_is_removed_without_touching_other_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "hooks.json"
            path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "Stop": [
                                {
                                    "hooks": [
                                        {"type": "command", "command": MODULE.HOOK_COMMAND},
                                        {"type": "command", "command": "/usr/bin/keep-me"},
                                    ]
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(MODULE.remove_managed_hook(path))
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                value["hooks"]["Stop"][0]["hooks"],
                [{"type": "command", "command": "/usr/bin/keep-me"}],
            )


if __name__ == "__main__":
    unittest.main()
