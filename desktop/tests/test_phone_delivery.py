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
            "PRESENCE_FILE": state / "presence-stamp",
            "STATUS_NOTIFICATION_ID_FILE": state / "notification-id",
            "WAKE_SOCKET": state / "worker.sock",
        }
        self.patchers = [patch.object(MODULE, name, value) for name, value in replacements.items()]
        for patcher in self.patchers:
            patcher.start()
        MODULE.PRESENCE_FILE.write_text("100\n", encoding="ascii")

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
    @patch.object(MODULE, "save_active_alert")
    @patch.object(MODULE, "deliver", return_value=(True, "lan-direct", ""))
    def test_worker_removes_only_acknowledged_event(self, _deliver, _save_active, _clear):
        with patch.object(MODULE, "activate_worker", return_value=True):
            MODULE.enqueue(self.args("event-3"))
        self.assertEqual(MODULE.worker(), 0)
        _save_active.assert_called_once_with("event-3", 100)
        with closing(MODULE.connect_db()) as connection:
            self.assertEqual(MODULE.queue_depth(connection), 0)
        self.assertEqual(MODULE.load_status()["last_success_transport"], "lan-direct")

        with patch.object(MODULE, "activate_worker") as activate:
            self.assertEqual(MODULE.enqueue(self.args("event-3")), 0)
            activate.assert_not_called()
        with closing(MODULE.connect_db()) as connection:
            self.assertEqual(MODULE.queue_depth(connection), 0)

    @patch.object(MODULE, "clear_event", return_value=(True, "lan-direct", "cleared"))
    @patch.object(MODULE, "stop_clear_watcher")
    def test_desktop_input_clears_only_after_baseline(self, stop_watcher, clear_event):
        MODULE.ACTIVE_ALERT_FILE.write_text(
            '{"event_id":"event-clear","presence_baseline":100}\n', encoding="utf-8"
        )
        self.assertEqual(MODULE.clear_active_alert(), 0)
        clear_event.assert_not_called()
        self.assertTrue(MODULE.ACTIVE_ALERT_FILE.exists())

        MODULE.PRESENCE_FILE.write_text("101\n", encoding="ascii")
        self.assertEqual(MODULE.clear_active_alert(), 0)
        clear_event.assert_called_once_with("event-clear")
        self.assertFalse(MODULE.ACTIVE_ALERT_FILE.exists())
        stop_watcher.assert_called_once()

    @patch.object(MODULE, "run")
    def test_public_install_needs_no_privileged_input_monitor(self, run):
        MODULE.save_active_alert("event-without-monitor", None)
        self.assertFalse(MODULE.ACTIVE_ALERT_FILE.exists())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
