import importlib.machinery
import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).parents[1] / "codex-alert"
sys.path.insert(0, str(SCRIPT.parent))

import codex_alert_common as common


MODULE = importlib.machinery.SourceFileLoader("codex_alert_cli", str(SCRIPT)).load_module()


class FakePairingResponse:
    status = 200

    def read(self, maximum):
        return json.dumps({
            "status": "paired",
            "token": "a" * 64,
            "device_name": "Test phone",
            "addresses": ["192.168.0.2"],
        }).encode("utf-8")


class FakePairingConnection:
    def __init__(self, certificate, result):
        self.certificate = certificate
        self.result = result
        self.sock = self
        self.closed = False
        self.requests = []

    def connect(self):
        pass

    def getpeercert(self, binary_form=False):
        return self.certificate

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self):
        self.closed = True


class HookSetupTests(unittest.TestCase):
    def test_pairing_retries_a_dropped_success_response_safely(self):
        first = FakePairingConnection(
            b"same-certificate",
            http.client.RemoteDisconnected("closed before response"),
        )
        second = FakePairingConnection(b"same-certificate", FakePairingResponse())
        confirm = Mock(return_value=True)
        with (
            patch.object(MODULE.http.client, "HTTPSConnection", side_effect=[first, second]),
            patch.object(MODULE.time, "sleep") as sleep,
        ):
            result, certificate = MODULE.pair_request("192.168.0.2", "12345678", confirm)

        self.assertEqual(result["status"], "paired")
        self.assertEqual(certificate, b"same-certificate")
        confirm.assert_called_once_with(b"same-certificate")
        sleep.assert_called_once_with(0.25)
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)

    def test_pairing_retry_rejects_a_changed_phone_identity(self):
        first = FakePairingConnection(
            b"first-certificate",
            http.client.RemoteDisconnected("closed before response"),
        )
        second = FakePairingConnection(b"different-certificate", FakePairingResponse())
        confirm = Mock(return_value=True)
        with (
            patch.object(MODULE.http.client, "HTTPSConnection", side_effect=[first, second]),
            patch.object(MODULE.time, "sleep"),
            self.assertRaisesRegex(RuntimeError, "phone identity changed"),
        ):
            MODULE.pair_request("192.168.0.2", "12345678", confirm)

        confirm.assert_called_once_with(b"first-certificate")

    def test_pairing_confirmation_is_authenticated_and_certificate_pinned(self):
        connection = FakePairingConnection(b"phone-certificate", FakePairingResponse())
        with patch.object(MODULE.http.client, "HTTPSConnection", return_value=connection):
            MODULE.confirm_pairing("192.168.0.2", "b" * 64, b"phone-certificate")

        args, kwargs = connection.requests[0]
        self.assertEqual(args[:2], ("POST", "/v1/pair/confirm"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer " + "b" * 64)
        self.assertTrue(connection.closed)

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
            self.assertEqual(value["hooks"]["Stop"][-1], MODULE.hook_definition())
            self.assertEqual(
                value["hooks"]["Stop"][0]["hooks"],
                [{"type": "command", "command": "/usr/bin/other"}],
            )
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
                patch.object(MODULE, "hook_trust_cache_valid", return_value=False),
                patch.object(MODULE, "ensure_hook_trust", return_value=(2, [])) as trust,
            ):
                self.assertEqual(MODULE.sync_hooks(quiet=True), 0)

            sync.assert_called_once_with(main_hooks)
            trust.assert_called_once_with([main_home, shadow_home])
            self.assertTrue((shadow_home / "hooks.json").is_symlink())

    def test_trust_refresh_updates_only_codex_alert_hook_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.toml"
            config.write_text("[hooks.state]\n", encoding="utf-8")
            first = root / ".codex"
            second = root / ".codex2"
            homes = [first, second]
            current_hash = "sha256:" + "a" * 64
            modified = {
                "key": f"{first}/hooks.json:stop:3:0",
                "currentHash": current_hash,
                "trustStatus": "modified",
                "enabled": True,
            }
            trusted = dict(modified, trustStatus="trusted")
            client = Mock()
            context = Mock()
            context.__enter__ = Mock(return_value=client)
            context.__exit__ = Mock(return_value=False)

            with (
                patch.object(MODULE, "homes_by_config", return_value={config: homes}),
                patch.object(MODULE, "CodexAppServer", return_value=context),
                patch.object(MODULE, "codex_alert_hook_metadata", side_effect=[modified, trusted]),
                patch.object(
                    MODULE,
                    "group_hook_keys",
                    return_value={
                        first: f"{first}/hooks.json:stop:3:0",
                        second: f"{second}/hooks.json:stop:3:0",
                    },
                ),
                patch.object(MODULE, "save_hook_trust_cache") as save_cache,
                patch.object(
                    MODULE,
                    "hook_state",
                    side_effect=[{}, {}, {"trusted_hash": current_hash}, {"trusted_hash": current_hash}],
                ),
            ):
                active, failures = MODULE.ensure_hook_trust(homes)

            self.assertEqual((active, failures), (2, []))
            save_cache.assert_called_once()
            write = client.request.call_args.args
            self.assertEqual(write[0], "config/batchWrite")
            value = write[1]["edits"][0]["value"]
            self.assertEqual(
                value,
                {
                    f"{first}/hooks.json:stop:3:0": {
                        "trusted_hash": current_hash,
                        "enabled": True,
                    },
                    f"{second}/hooks.json:stop:3:0": {
                        "trusted_hash": current_hash,
                        "enabled": True,
                    },
                },
            )

    def test_hook_keys_follow_each_accounts_actual_group_position(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / ".codex"
            second = root / ".codex2"
            first.mkdir()
            second.mkdir()
            other = {"hooks": [{"type": "command", "command": "/usr/bin/other"}]}
            (first / "hooks.json").write_text(
                json.dumps({"hooks": {"Stop": [other, MODULE.hook_definition()]}}),
                encoding="utf-8",
            )
            (second / "hooks.json").write_text(
                json.dumps({"hooks": {"Stop": [other, other, MODULE.hook_definition()]}}),
                encoding="utf-8",
            )
            metadata = {"key": f"{first}/hooks.json:stop:1:0"}

            self.assertEqual(
                MODULE.group_hook_keys([first, second], first, metadata),
                {
                    first: f"{first}/hooks.json:stop:1:0",
                    second: f"{second}/hooks.json:stop:2:0",
                },
            )

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

    def test_quiet_timer_uses_valid_trust_cache_without_starting_codex(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / ".codex"
            home.mkdir()
            (home / "hooks.json").write_text(
                json.dumps({"hooks": {"Stop": [MODULE.hook_definition()]}}, indent=2) + "\n",
                encoding="utf-8",
            )
            with (
                patch.object(MODULE, "codex_homes", return_value=[home]),
                patch.object(MODULE, "hook_trust_cache_valid", return_value=True),
                patch.object(MODULE, "ensure_hook_trust") as trust,
            ):
                self.assertEqual(MODULE.sync_hooks(quiet=True), 0)

            trust.assert_not_called()


if __name__ == "__main__":
    unittest.main()
