import importlib.machinery
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "codex-phone-deliver"
sys.path.insert(0, str(SCRIPT.parent))
MODULE = importlib.machinery.SourceFileLoader("codex_phone_deliver", str(SCRIPT)).load_module()


class PhoneDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        state = Path(self.temporary.name)
        replacements = {
            "STATE_DIR": state,
            "DB_FILE": state / "queue.sqlite3",
            "LOCK_FILE": state / "worker.lock",
            "STATUS_FILE": state / "status.json",
            "LOG_FILE": state / "delivery.log",
            "ACTIVE_ALERT_FILE": state / "active-alert.json",
            "CLEAR_LOCK_FILE": state / "clear-watcher.lock",
            "STATUS_NOTIFICATION_ID_FILE": state / "notification-id",
            "WAKE_SOCKET": state / "worker.sock",
        }
        self.patchers = [patch.object(MODULE, name, value) for name, value in replacements.items()]
        self.patchers.extend((
            patch.object(MODULE, "desktop_activity_stamp", return_value=1_000_000_000),
            patch.object(MODULE, "activate_clear_watcher", return_value=True),
        ))
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    def args(self, event_id):
        return Namespace(
            title="Codex finished · test",
            body="codex2 · Done",
            account="codex2",
            project="test",
            event_id=event_id,
            environment_id="environment-1",
            thread_id="thread-1",
            ttl_hours=1,
        )

    @patch.object(MODULE, "activate_worker", return_value=True)
    def test_enqueue_is_durable_and_idempotent(self, _activate):
        self.assertEqual(MODULE.enqueue(self.args("event-1")), 0)
        self.assertEqual(MODULE.enqueue(self.args("event-1")), 0)
        with closing(MODULE.connect_db()) as connection:
            self.assertEqual(MODULE.queue_depth(connection), 1)
            event = MODULE.next_event(connection)
            self.assertEqual(event["environment_id"], "environment-1")
            self.assertEqual(event["thread_id"], "thread-1")
            self.assertEqual(event["presence_baseline"], 1_000_000_000)

    @patch.object(MODULE, "discover_lan_targets", return_value=[("lan-mdns", "192.168.1.50")])
    @patch.object(
        MODULE,
        "phone",
        return_value={"targets": ["192.168.1.50", "phone.example.ts.net", "100.64.0.42"]},
    )
    def test_direct_targets_are_deduplicated_and_include_tailscale(self, _phone, _discover):
        targets = list(MODULE.direct_targets())
        self.assertEqual(targets.count(("lan-direct", "192.168.1.50")), 1)
        self.assertIn(("tailscale-direct", "phone.example.ts.net"), targets)
        self.assertIn(("tailscale-direct", "100.64.0.42"), targets)
        self.assertNotIn(("lan-mdns", "192.168.1.50"), targets)

    @patch.object(MODULE, "discover_lan_targets")
    @patch.object(MODULE, "phone", return_value={"targets": ["192.168.1.50"]})
    def test_working_fixed_lan_does_not_pay_discovery_cost(self, _phone, discover):
        targets = MODULE.direct_targets()
        self.assertEqual(next(targets), ("lan-direct", "192.168.1.50"))
        discover.assert_not_called()

    @patch.object(MODULE, "discover_lan_targets")
    @patch.object(
        MODULE,
        "phone",
        return_value={"targets": ["192.168.1.50", "phone.example.ts.net"]},
    )
    def test_skip_lan_avoids_discovery(self, _phone, discover):
        targets = list(MODULE.direct_targets(skip_lan=True))
        discover.assert_not_called()
        self.assertTrue(all(transport == "tailscale-direct" for transport, _ in targets))

    @patch.object(MODULE, "clear_delivery_problem")
    @patch.object(MODULE, "deliver", return_value=(True, "lan-direct", ""))
    def test_worker_removes_only_acknowledged_event(self, _deliver, _clear):
        with patch.object(MODULE, "activate_worker", return_value=True):
            MODULE.enqueue(self.args("event-3"))
        self.assertEqual(MODULE.worker(), 0)
        with closing(MODULE.connect_db()) as connection:
            self.assertEqual(MODULE.queue_depth(connection), 0)
        self.assertEqual(MODULE.load_status()["last_success_transport"], "lan-direct")

        with patch.object(MODULE, "activate_worker") as activate:
            self.assertEqual(MODULE.enqueue(self.args("event-3")), 0)
            activate.assert_not_called()
        with closing(MODULE.connect_db()) as connection:
            self.assertEqual(MODULE.queue_depth(connection), 0)

    def test_worker_process_fallback_does_not_require_systemd(self):
        with (
            patch.object(MODULE, "SYSTEMCTL", None),
            patch.object(MODULE.socket, "socket", side_effect=OSError("not running")),
            patch.object(MODULE.subprocess, "Popen") as popen,
        ):
            self.assertTrue(MODULE.activate_worker())

        self.assertEqual(popen.call_args.args[0][-1], "worker")

    def test_new_desktop_input_clears_only_the_matching_phone_alert(self):
        baseline = 1_000_000_000
        self.assertTrue(MODULE.save_active_alert("event-clear", baseline))
        with patch.object(
            MODULE,
            "clear_event",
            return_value=(True, "lan-direct", "cleared"),
        ) as clear:
            self.assertEqual(
                MODULE.clear_active_alert(baseline + MODULE.INPUT_STAMP_TOLERANCE_NS + 1),
                0,
            )

        clear.assert_called_once_with("event-clear")
        self.assertFalse(MODULE.ACTIVE_ALERT_FILE.exists())

    def test_old_desktop_input_does_not_clear_phone_alert(self):
        baseline = 1_000_000_000
        self.assertTrue(MODULE.save_active_alert("event-wait", baseline))
        with patch.object(MODULE, "clear_event") as clear:
            self.assertEqual(MODULE.clear_active_alert(baseline), 0)

        clear.assert_not_called()
        self.assertEqual(MODULE.load_active_alert()["event_id"], "event-wait")

    def test_clear_response_cannot_remove_a_newer_completion(self):
        baseline = 1_000_000_000
        self.assertTrue(MODULE.save_active_alert("event-old", baseline))

        def replace_with_newer(_event_id):
            MODULE.ACTIVE_ALERT_FILE.write_text(
                '{"event_id":"event-new","presence_baseline":2000000000,'
                '"delivered_at":9999999999}\n',
                encoding="utf-8",
            )
            return True, "lan-direct", "stale"

        with patch.object(MODULE, "clear_event", side_effect=replace_with_newer):
            self.assertEqual(
                MODULE.clear_active_alert(baseline + MODULE.INPUT_STAMP_TOLERANCE_NS + 1),
                0,
            )

        self.assertEqual(MODULE.load_active_alert()["event_id"], "event-new")

if __name__ == "__main__":
    unittest.main()
