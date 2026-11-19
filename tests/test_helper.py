import base64
import os
import sys
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "helper"))

import protonx_helper as helper

VALID = {
    "private_key": base64.b64encode(bytes(range(32))).decode(),
    "address": "10.2.0.2/32",
    "peer_public_key": base64.b64encode(bytes(range(32, 64))).decode(),
    "allowed_ips": "0.0.0.0/0",
    "endpoint_host": "nl-1.protonvpn.net",
    "endpoint_port": 51820,
    "dns": "10.2.0.1",
    "mtu": 1420,
    "keepalive": 25,
}


def variant(**changes):
    config = dict(VALID)
    config.update(changes)
    return config


class ValidateTests(unittest.TestCase):
    def test_valid_config_is_accepted(self):
        rendered = helper.render(VALID)
        self.assertIn("[Interface]", rendered)
        self.assertIn("Endpoint = nl-1.protonvpn.net:51820", rendered)
        self.assertIn("PersistentKeepalive = 25", rendered)

    def test_hook_directive_is_rejected_as_unknown_field(self):
        with self.assertRaises(helper.HelperError):
            helper.render(variant(PostUp="curl evil"))

    def test_missing_field_is_rejected(self):
        config = dict(VALID)
        del config["peer_public_key"]
        with self.assertRaises(helper.HelperError):
            helper.render(config)

    def test_short_key_is_rejected(self):
        with self.assertRaises(helper.HelperError):
            helper.render(variant(private_key="AAAA"))

    def test_key_with_injected_newline_is_rejected(self):
        injected = base64.b64encode(bytes(range(32))).decode() + "\nPostUp = id"
        with self.assertRaises(helper.HelperError):
            helper.render(variant(private_key=injected))

    def test_bad_address_is_rejected(self):
        with self.assertRaises(helper.HelperError):
            helper.render(variant(address="10.2.0.2/32\nPostUp = id"))

    def test_bad_network_is_rejected(self):
        with self.assertRaises(helper.HelperError):
            helper.render(variant(allowed_ips="0.0.0.0/0; rm -rf /"))

    def test_host_with_space_is_rejected(self):
        with self.assertRaises(helper.HelperError):
            helper.render(variant(endpoint_host="host name"))

    def test_host_with_shell_metacharacter_is_rejected(self):
        with self.assertRaises(helper.HelperError):
            helper.render(variant(endpoint_host="host;id"))

    def test_port_out_of_range_is_rejected(self):
        with self.assertRaises(helper.HelperError):
            helper.render(variant(endpoint_port=70000))

    def test_port_as_string_is_rejected(self):
        with self.assertRaises(helper.HelperError):
            helper.render(variant(endpoint_port="51820"))

    def test_mtu_below_minimum_is_rejected(self):
        with self.assertRaises(helper.HelperError):
            helper.render(variant(mtu=500))

    def test_keepalive_bool_is_rejected(self):
        with self.assertRaises(helper.HelperError):
            helper.render(variant(keepalive=True))

    def test_dns_absent_omits_line(self):
        rendered = helper.render(variant(dns=None))
        self.assertNotIn("DNS =", rendered)

    def test_wg_quick_never_owns_dns(self):
        self.assertNotIn("DNS =", helper.render(variant(dns="10.2.0.1")))

    def test_unknown_command_is_rejected(self):
        with self.assertRaises(helper.HelperError):
            helper.dispatch({"command": "shell"})


class DnsOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.written = []
        self.saved = {}
        self.patches = [
            unittest.mock.patch.object(helper, "_primary_service", return_value="Wi-Fi"),
            unittest.mock.patch.object(helper, "_read_dns", side_effect=lambda service: list(self.saved.get(service, []))),
            unittest.mock.patch.object(helper, "_write_dns", side_effect=lambda service, servers: self.written.append((service, list(servers)))),
            unittest.mock.patch.object(helper, "DNS_STATE_PATH", os.path.join(self.tmpdir(), "dns.json")),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tmpdir(self):
        import tempfile

        if not hasattr(self, "_tmpdir"):
            self._tmpdir = tempfile.mkdtemp()
        return self._tmpdir

    def test_apply_saves_previous_servers_then_sets_tunnel_resolver(self):
        self.saved["Wi-Fi"] = ["192.168.31.1"]
        helper._apply_dns("10.2.0.1")
        self.assertEqual(self.written, [("Wi-Fi", ["10.2.0.1"])])
        self.assertTrue(os.path.exists(helper.DNS_STATE_PATH))

    def test_restore_returns_the_previous_servers(self):
        self.saved["Wi-Fi"] = ["192.168.31.1"]
        helper._apply_dns("10.2.0.1")
        self.written.clear()
        helper._restore_dns()
        self.assertEqual(self.written, [("Wi-Fi", ["192.168.31.1"])])
        self.assertFalse(os.path.exists(helper.DNS_STATE_PATH))

    def test_restore_drops_stale_tunnel_resolvers(self):
        self.saved["Wi-Fi"] = ["10.2.0.1", "10.200.74.101", "192.168.31.1"]
        helper._apply_dns("10.2.0.1")
        self.written.clear()
        helper._restore_dns()
        self.assertEqual(self.written, [("Wi-Fi", ["192.168.31.1"])])

    def test_restore_without_saved_state_does_nothing(self):
        helper._restore_dns()
        self.assertEqual(self.written, [])

    def test_restore_falls_back_to_automatic_when_only_tunnel_dns_was_saved(self):
        self.saved["Wi-Fi"] = ["10.200.74.101"]
        helper._apply_dns("10.2.0.1")
        self.written.clear()
        helper._restore_dns()
        self.assertEqual(self.written, [("Wi-Fi", [])])


if __name__ == "__main__":
    unittest.main()
