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


class SwitchTests(unittest.TestCase):
    def setUp(self):
        resources = self.enterContext(ExitStack())
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
        resources.enter_context(patch.object(helper, "DNS_STATE_PATH", str(self.dns_state)))
        resources.enter_context(patch.object(helper, "_interface_name", lambda: "utun9" if self.active else None))
        resources.enter_context(patch.object(helper, "_tool", lambda name: name))
        resources.enter_context(patch.object(helper, "_primary_service", return_value="Wi-Fi"))
        resources.enter_context(patch.object(helper, "_read_dns", side_effect=lambda _: list(self.dns)))
        resources.enter_context(patch.object(helper, "_write_dns", side_effect=self.write_dns))
        resources.enter_context(patch.object(helper, "_run", side_effect=self.run_tool))
        resources.enter_context(patch.object(helper, "status", side_effect=self.status))
        self.resolve = resources.enter_context(patch.object(socket, "getaddrinfo", side_effect=self.resolve_host))

    def write_dns(self, service, servers):
        self.events.append(("dns", servers))
        self.dns = list(servers)

    def resolve_host(self, host, *_args, **_kwargs):
        self.events.append(("resolve", host))
        if host == "unavailable.invalid" or (not self.active and self.dns == ["10.2.0.1"]):
            raise socket.gaierror("resolver unavailable")
        return [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.25", 51820))]

    def run_tool(self, args, check=True):
        if args[0] == "ifconfig":
            self.events.append(("interface-check", args[1]))
            self.linger, lingering = False, self.linger
            return subprocess.CompletedProcess(args, 0 if self.active or lingering else 1, "", "")
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
        if not host[0].isdigit():
            try:
                host = self.resolve_host(host)[0][-1][0]
            except socket.gaierror as error:
                return subprocess.CompletedProcess(args, 1, "", str(error))
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
