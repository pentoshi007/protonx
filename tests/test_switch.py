import json
import os
import socket
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from tests.test_helper import helper, variant


class FakeSystem:
    def __init__(self, test):
        self.test = test

    def interface_name(self):
        return "utun9" if self.test.active else None

    def interface_exists(self, name):
        self.test.events.append(("interface-check", name))
        self.test.linger, lingering = False, self.test.linger
        return self.test.active or lingering

    def interface_address(self, name):
        return "10.2.0.2"

    def remove_interface(self, name):
        pass

    def check_bypass(self, address):
        pass

    def add_bypass(self, address):
        pass

    def remove_bypass(self):
        pass

    def current_bypass(self):
        return None

    def apply_dns(self, dns):
        if not dns:
            return
        self.test.dns_state.write_text(json.dumps({"servers": self.test.dns, "applied": dns}))
        self.test.write_dns(dns.split(", "))

    def restore_dns(self):
        if not self.test.dns_state.exists():
            return
        saved = json.loads(self.test.dns_state.read_text())
        self.test.write_dns([item for item in saved["servers"] if not item.startswith("10.2.")])
        self.test.dns_state.unlink()

    def applied_dns(self):
        if not self.test.dns_state.exists():
            return None
        return json.loads(self.test.dns_state.read_text())["applied"]


class SwitchTests(unittest.TestCase):
    def setUp(self):
        resources = ExitStack()
        self.addCleanup(resources.close)
        directory = Path(resources.enter_context(tempfile.TemporaryDirectory()))
        self.config = directory / "protonx.conf"
        self.dns_state = directory / "dns.json"
        self.active = False
        self.endpoint = None
        self.dns = ["192.168.1.1"]
        self.fail_endpoint = None
        self.linger = False
        self.events = []
        resources.enter_context(patch.object(helper, "SOCKET_DIR", str(directory)))
        resources.enter_context(patch.object(helper, "CONFIG_PATH", str(self.config)))
        resources.enter_context(patch.object(helper, "system", FakeSystem(self)))
        resources.enter_context(patch.object(helper, "tool", lambda name: name))
        resources.enter_context(patch.object(helper, "run", side_effect=self.run_tool))
        resources.enter_context(patch.object(helper, "status", side_effect=self.status))
        resources.enter_context(patch.object(helper, "flow_problem", return_value=None))
        resources.enter_context(patch.object(helper, "_start_watchdog"))
        self.resolve = resources.enter_context(patch.object(socket, "getaddrinfo", side_effect=self.resolve_host))

    def write_dns(self, servers):
        self.events.append(("dns", servers))
        self.dns = list(servers)

    def resolve_host(self, host, *_args, **_kwargs):
        self.events.append(("resolve", host))
        if host == "unavailable.invalid" or (not self.active and self.dns == ["10.2.0.1"]):
            raise socket.gaierror("resolver unavailable")
        return [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.25", 51820))]

    def run_tool(self, args, check=True):
        action = args[1]
        self.events.append((action, None))
        if action == "down":
            self.active = False
            return subprocess.CompletedProcess(args, 0, "", "")
        return self.start_tunnel(args)

    def start_tunnel(self, args):
        endpoint = next(line for line in self.config.read_text().splitlines() if line.startswith("Endpoint"))
        host = endpoint.split(" = ", 1)[1].split(":", 1)[0]
        if self.linger or host == self.fail_endpoint:
            return subprocess.CompletedProcess(args, 1, "", "route or peer setup failed")
        self.endpoint = host
        self.active = True
        return subprocess.CompletedProcess(args, 0, "", "")

    def status(self):
        return {"up": self.active, "interface": "utun9" if self.active else None}

    def test_switch_resolves_before_retiring_old_tunnel_and_drains_interface(self):
        helper.up(variant(endpoint_host="192.0.2.1"))
        self.events.clear()
        self.linger = True
        self.assertTrue(helper.up(variant(endpoint_host="next.example"))["up"])
        self.assertEqual(self.endpoint, "192.0.2.25")
        self.assertEqual(self.events[:3], [("resolve", "next.example"), ("down", None), ("interface-check", "utun9")])
        self.assertEqual(json.loads(self.dns_state.read_text())["servers"], ["192.168.1.1"])
        helper.down()
        self.assertEqual(self.dns, ["192.168.1.1"])

    def test_missing_dns_answer_does_not_touch_working_tunnel(self):
        helper.up(variant(endpoint_host="192.0.2.1"))
        with self.assertRaises(helper.HelperError):
            helper.up(variant(endpoint_host="unavailable.invalid"))
        self.assertTrue(self.active)
        self.assertEqual(self.endpoint, "192.0.2.1")
        self.assertEqual(self.dns, ["10.2.0.1"])

    def test_failed_replacement_restores_working_tunnel_and_original_dns(self):
        helper.up(variant(endpoint_host="192.0.2.1"))
        self.fail_endpoint = "192.0.2.25"
        with self.assertRaisesRegex(helper.HelperError, "previous tunnel restored"):
            helper.up(variant(endpoint_host=self.fail_endpoint))
        self.assertTrue(self.active)
        self.assertEqual(self.endpoint, "192.0.2.1")
        self.resolve.assert_not_called()
        helper.down()
        self.assertEqual(self.dns, ["192.168.1.1"])

    def test_failed_first_connection_leaves_no_config_or_tunnel_dns(self):
        self.fail_endpoint = "192.0.2.25"
        with self.assertRaises(helper.HelperError):
            helper.up(variant(endpoint_host=self.fail_endpoint))
        self.assertFalse(os.path.exists(helper.CONFIG_PATH))
        self.assertFalse(self.dns_state.exists())
        self.assertEqual(self.dns, ["192.168.1.1"])

    def test_switch_to_no_dns_restores_system_resolver(self):
        helper.up(variant(endpoint_host="192.0.2.1"))
        self.assertTrue(helper.up(variant(endpoint_host="192.0.2.25", dns=None))["up"])
        self.assertEqual(self.dns, ["192.168.1.1"])
        self.assertFalse(self.dns_state.exists())

    def test_a_tunnel_that_carries_no_traffic_is_never_reported_connected(self):
        dead = helper.NO_TRAFFIC + " (api.proton.me:443 failed: timed out)"
        with patch.object(helper, "flow_problem", return_value=dead):
            with self.assertRaisesRegex(helper.HelperError, "normal network settings"):
                helper.up(variant(endpoint_host="192.0.2.1"))
        self.assertFalse(self.active)
        self.assertFalse(os.path.exists(helper.CONFIG_PATH))
        self.assertEqual(self.dns, ["192.168.1.1"])

    def test_watchdog_tears_down_a_tunnel_that_stops_forwarding(self):
        helper.up(variant(endpoint_host="192.0.2.1"))
        generation = helper._watchdog["generation"]
        with patch.object(helper, "FLOW_WATCH", (0,)), patch.object(helper, "FLOW_RECHECK", 0), patch.object(
            helper, "flow_problem", return_value=helper.NO_TRAFFIC + " (dead)"
        ), patch.object(helper, "_stop_tunnel") as stop, patch.object(helper, "_record_flow_failure") as record:
            helper._watch_flow("utun9", generation)
        stop.assert_called_once()
        record.assert_called_once()
        self.assertNotEqual(helper._watchdog["generation"], generation)
