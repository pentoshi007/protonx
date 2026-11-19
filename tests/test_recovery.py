import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from tests.test_helper import helper, helper_macos, variant
from protonxlib import cli, recovery, service
from protonxlib.errors import TunnelError


class FakeSystem:
    def __init__(self, name="utun9", exists=True):
        self.name = name
        self.exists = exists
        self.calls = []
        self.dns = {"stale": False, "servers": [], "service": "Wi-Fi"}

    def interface_name(self):
        return self.name

    def interface_exists(self, name):
        return self.exists

    def interface_address(self, name):
        return "10.2.0.2"

    def remove_interface(self, name):
        self.calls.append(("remove-interface", name))

    def clear_interface_name(self):
        self.calls.append(("clear-name", None))

    def check_bypass(self, address):
        pass

    def add_bypass(self, address):
        self.calls.append(("add-bypass", address))

    def remove_bypass(self):
        self.calls.append(("remove-bypass", None))

    def current_bypass(self):
        return None

    def apply_dns(self, dns):
        self.calls.append(("apply-dns", dns))

    def restore_dns(self):
        self.calls.append(("restore-dns", None))

    def applied_dns(self):
        return "10.2.0.1"

    def dns_report(self, up):
        return dict(self.dns, stale=(not up) and self.dns.get("stale", False))

    def flush_dns(self):
        self.calls.append(("flush-dns", None))

    def resolves(self, name):
        return True

    def internet(self):
        return True


class MacDnsFailSafeTests(unittest.TestCase):
    def setUp(self):
        self.written = []
        self.saved = {}
        self.directory = tempfile.mkdtemp()
        self.patches = [
            mock.patch.object(helper_macos, "_primary_service", return_value="Wi-Fi"),
            mock.patch.object(helper_macos, "_read_dns", side_effect=lambda service: list(self.saved.get(service, []))),
            mock.patch.object(helper_macos, "_write_dns", side_effect=lambda service, servers: self.written.append((service, list(servers)))),
            mock.patch.object(helper_macos, "DNS_STATE_PATH", os.path.join(self.directory, "dns.json")),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_restore_without_snapshot_clears_stale_tunnel_dns(self):
        self.saved["Wi-Fi"] = ["10.2.0.1"]
        helper_macos.restore_dns()
        self.assertEqual(self.written, [("Wi-Fi", [])])

    def test_restore_without_snapshot_keeps_normal_dns(self):
        self.saved["Wi-Fi"] = ["192.168.31.1"]
        helper_macos.restore_dns()
        self.assertEqual(self.written, [])

    def test_restore_without_snapshot_drops_mixed_tunnel_dns(self):
        self.saved["Wi-Fi"] = ["10.2.0.1", "192.168.31.1"]
        helper_macos.restore_dns()
        self.assertEqual(self.written, [("Wi-Fi", ["192.168.31.1"])])


class LinuxDnsFailSafeTests(unittest.TestCase):
    def setUp(self):
        import helper_linux

        self.linux = helper_linux
        self.directory = tempfile.mkdtemp()
        self.resolv = os.path.join(self.directory, "resolv.conf")
        self.stub = os.path.join(self.directory, "stub-resolv.conf")
        self.patches = [
            mock.patch.object(helper_linux, "RESOLV_CONF", self.resolv),
            mock.patch.object(helper_linux, "RESOLVED_STUB", self.stub),
            mock.patch.object(helper_linux, "DNS_STATE_PATH", os.path.join(self.directory, "dns.json")),
            mock.patch.object(helper_linux, "interface_exists", return_value=False),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_restore_without_snapshot_replaces_protonx_resolv_with_stub(self):
        with open(self.stub, "w") as handle:
            handle.write("nameserver 127.0.0.53\n")
        with open(self.resolv, "w") as handle:
            handle.write(self.linux.RESOLV_HEADER + "nameserver 10.2.0.1\n")
        self.linux.restore_dns()
        self.assertTrue(os.path.islink(self.resolv))
        self.assertEqual(os.readlink(self.resolv), self.stub)

    def test_restore_without_snapshot_leaves_normal_resolv_alone(self):
        with open(self.resolv, "w") as handle:
            handle.write("nameserver 192.168.1.1\n")
        self.linux.restore_dns()
        self.assertFalse(os.path.islink(self.resolv))
        with open(self.resolv) as handle:
            self.assertIn("192.168.1.1", handle.read())


class HelperLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.config = os.path.join(self.directory, "protonx.conf")
        self.system = FakeSystem()
        self.patches = [
            mock.patch.object(helper, "CONFIG_PATH", self.config),
            mock.patch.object(helper, "system", self.system),
            mock.patch.object(helper, "tool", lambda name: name),
            mock.patch.object(helper, "run", return_value=subprocess.CompletedProcess([], 0, "", "")),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_stop_restores_dns_even_when_interface_lingers(self):
        with mock.patch.object(helper, "_wait_for_interface_exit", return_value=False):
            warnings = helper._stop_tunnel()
        self.assertIn(("restore-dns", None), self.system.calls)
        self.assertIn(("clear-name", None), self.system.calls)
        self.assertTrue(any("did not stop" in warning for warning in warnings))

    def test_stop_clears_stale_interface_name(self):
        helper._stop_tunnel()
        self.assertIn(("clear-name", None), self.system.calls)

    def test_status_ignores_stale_interface_name(self):
        self.system.exists = False
        with mock.patch.object(helper, "_read_tunnel", return_value={"server": {"label": "NL"}}):
            report = helper.status()
        self.assertFalse(report["up"])
        self.assertIsNone(report["interface"])
        self.assertIsNone(report["server"])

    def test_status_returns_active_server_from_persistent_record(self):
        self.system.exists = True
        dump = subprocess.CompletedProcess([], 0, "utun9\t\n", "")
        with mock.patch.object(helper, "run", return_value=dump), mock.patch.object(
            helper, "_read_tunnel", return_value={"server": {"label": "NL-FREE#1"}}
        ):
            report = helper.status()
        self.assertTrue(report["up"])
        self.assertEqual(report["server"]["label"], "NL-FREE#1")

    def test_reconcile_cleans_stale_state(self):
        self.system.exists = False
        with mock.patch.object(helper, "_clear_tunnel") as clear:
            helper._reconcile()
        self.assertIn(("restore-dns", None), self.system.calls)
        self.assertIn(("remove-bypass", None), self.system.calls)
        clear.assert_called_once()


class UpRetryTests(unittest.TestCase):
    def setUp(self):
        self.system = FakeSystem()
        self.patches = [
            mock.patch.object(helper, "system", self.system),
            mock.patch.object(helper, "_resolve_ipv4", return_value="192.0.2.1"),
            mock.patch.object(helper, "_previous_tunnel", return_value=None),
            mock.patch.object(helper, "_stop_tunnel", return_value=[]),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_up_retries_once_then_fails_safe(self):
        with mock.patch.object(helper, "_start_tunnel", side_effect=helper.HelperError("route failed")) as start:
            with self.assertRaisesRegex(helper.HelperError, "restored to its normal network settings"):
                helper.up(variant())
        self.assertEqual(start.call_count, 2)

    def test_up_retries_and_succeeds(self):
        report = {"ok": True, "up": True, "interface": "utun9", "address": "10.2.0.2"}
        with mock.patch.object(helper, "_start_tunnel", side_effect=[helper.HelperError("route failed"), report]) as start:
            result = helper.up(variant())
        self.assertTrue(result["retried"])
        self.assertEqual(start.call_count, 2)

    def test_failed_up_restores_previous_tunnel(self):
        previous = {"text": "old", "dns": "10.2.0.1", "bypass": None, "meta": {"label": "old"}}
        report = {"ok": True, "up": True, "interface": "utun9", "address": "10.2.0.2"}
        with mock.patch.object(helper, "_previous_tunnel", return_value=previous), mock.patch.object(
            helper, "_start_tunnel", side_effect=[helper.HelperError("new failed"), helper.HelperError("new failed"), report]
        ) as start:
            with self.assertRaisesRegex(helper.HelperError, "previous tunnel restored"):
                helper.up(variant())
        self.assertEqual(start.call_count, 3)

    def test_failed_up_with_failed_recovery_stops_cleanly(self):
        previous = {"text": "old", "dns": "10.2.0.1", "bypass": None, "meta": None}
        with mock.patch.object(helper, "_previous_tunnel", return_value=previous), mock.patch.object(
            helper, "_start_tunnel", side_effect=helper.HelperError("failed")
        ), mock.patch.object(helper, "_stop_tunnel", return_value=[]) as stop:
            with self.assertRaisesRegex(helper.HelperError, "Recovery failed"):
                helper.up(variant())
        self.assertGreaterEqual(stop.call_count, 2)


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.system = FakeSystem()
        self.patches = [
            mock.patch.object(helper, "system", self.system),
            mock.patch.object(helper, "_stop_tunnel", return_value=["warning"]),
            mock.patch.object(helper, "status", return_value={"ok": True, "up": False, "dns": {"stale": False}}),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_repair_flushes_dns_and_reports_connectivity(self):
        report = helper.repair()
        self.assertIn(("flush-dns", None), self.system.calls)
        self.assertIn(("restore-dns", None), self.system.calls)
        self.assertTrue(report["resolves"])
        self.assertTrue(report["internet"])
        self.assertIn("flushed the DNS cache", report["actions"])

    def test_repair_reports_unreachable_internet(self):
        self.system.internet = lambda: False
        report = helper.repair()
        self.assertFalse(report["internet"])


class RecoveryProbeTests(unittest.TestCase):
    def test_probe_reports_up_from_persistent_record(self):
        record = {"interface": "utun9", "address": "10.2.0.2", "server": {"label": "NL"}}
        with mock.patch.object(recovery, "load_tunnel", return_value=record), mock.patch.object(
            recovery, "interface_exists", return_value=True
        ):
            report = recovery.probe()
        self.assertTrue(report["up"])
        self.assertEqual(report["server"]["label"], "NL")
        self.assertTrue(report["fallback"])

    def test_probe_reports_down_when_interface_is_missing(self):
        record = {"interface": "utun9", "server": {"label": "NL"}}
        with mock.patch.object(recovery, "load_tunnel", return_value=record), mock.patch.object(
            recovery, "interface_exists", return_value=False
        ):
            report = recovery.probe()
        self.assertFalse(report["up"])
        self.assertIsNone(report["server"])


class ServiceFallbackTests(unittest.TestCase):
    def test_status_falls_back_to_probe_when_helper_is_down(self):
        probe = {"ok": True, "up": True, "interface": "utun9", "server": {"label": "NL"}, "dns": {"stale": False}, "fallback": True}
        with mock.patch.object(service.wireguard, "status", side_effect=TunnelError("helper down")), mock.patch.object(
            service.recovery, "probe", return_value=probe
        ):
            report = service.status()
        self.assertTrue(report["up"])
        self.assertTrue(report["fallback"])
        self.assertEqual(report["server"]["label"], "NL")


class CliRepairTests(unittest.TestCase):
    def run_command(self, function, payload):
        output = io.StringIO()
        with mock.patch.object(service, "repair", return_value=payload), contextlib.redirect_stdout(output):
            code = function(mock.Mock(json=False))
        return code, output.getvalue()

    def test_repair_reports_success(self):
        payload = {
            "ok": True,
            "up": False,
            "dns": {"stale": False},
            "internet": True,
            "actions": ["flushed the DNS cache"],
        }
        code, output = self.run_command(cli.cmd_repair, payload)
        self.assertEqual(code, 0)
        self.assertIn("internet  reachable", output)
        self.assertIn("flushed the DNS cache", output)

    def test_repair_returns_failure_when_internet_is_unreachable(self):
        payload = {"ok": True, "up": False, "dns": {"stale": False}, "internet": False, "actions": []}
        code, output = self.run_command(cli.cmd_repair, payload)
        self.assertEqual(code, 1)
        self.assertIn("internet  not reachable", output)

    def test_status_warns_about_stale_dns(self):
        payload = {"up": False, "server": None, "dns": {"stale": True}}
        output = io.StringIO()
        with mock.patch.object(service, "status", return_value=payload), contextlib.redirect_stdout(output):
            code = cli.cmd_status(mock.Mock(json=False))
        self.assertEqual(code, 0)
        self.assertIn("protonx repair", output.getvalue())


if __name__ == "__main__":
    unittest.main()
