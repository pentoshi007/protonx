import json
import unittest

from protonxlib import selection
from protonxlib.logicals import parse

FIXTURE = {
    "LogicalServers": [
        {
            "ID": "A1",
            "Name": "NL-FREE#1",
            "ExitCountry": "NL",
            "EntryCountry": "NL",
            "City": "Amsterdam",
            "Tier": 0,
            "Load": 40,
            "Status": 1,
            "Features": 0,
            "Servers": [
                {
                    "ID": "s1",
                    "Name": "NL-FREE#1",
                    "Domain": "nl-free-01.protonvpn.net",
                    "EntryIP": "1.2.3.4",
                    "X25519PublicKey": "peerkey1=",
                    "ProtocolEntries": {"WireGuardUDP": {"Ports": [51820]}},
                }
            ],
        },
        {
            "ID": "A2",
            "Name": "NL-FREE#2",
            "ExitCountry": "NL",
            "EntryCountry": "NL",
            "City": "Amsterdam",
            "Tier": 0,
            "Load": 10,
            "Status": 1,
            "Features": 2,
            "Servers": [
                {
                    "ID": "s2",
                    "Name": "NL-FREE#2",
                    "Domain": "nl-free-02.protonvpn.net",
                    "EntryIP": "1.2.3.5",
                    "X25519PublicKey": "peerkey2=",
                    "ProtocolEntries": {"WireGuardUDP": {"Ports": [51820]}},
                }
            ],
        },
        {
            "ID": "A3",
            "Name": "DE#12",
            "ExitCountry": "DE",
            "EntryCountry": "DE",
            "City": "Berlin",
            "Tier": 2,
            "Load": 5,
            "Status": 1,
            "Features": 0,
            "Servers": [
                {
                    "ID": "s3",
                    "Name": "DE#12",
                    "Domain": "de-12.protonvpn.net",
                    "EntryIP": "5.6.7.8",
                    "X25519PublicKey": "peerkey3=",
                    "ProtocolEntries": {"WireGuardUDP": {"Ports": [51820]}},
                }
            ],
        },
        {
            "ID": "A4",
            "Name": "CH-NL#3",
            "ExitCountry": "NL",
            "EntryCountry": "CH",
            "City": "Amsterdam",
            "Tier": 2,
            "Load": 1,
            "Status": 1,
            "Features": 4,
            "Servers": [
                {
                    "ID": "s4",
                    "Name": "CH-NL#3",
                    "Domain": "ch-nl-03.protonvpn.net",
                    "EntryIP": "9.9.9.9",
                    "X25519PublicKey": "peerkey4=",
                    "ProtocolEntries": {"WireGuardUDP": {"Ports": [51820]}},
                }
            ],
        },
        {
            "ID": "A5",
            "Name": "US-FREE#9",
            "ExitCountry": "US",
            "EntryCountry": "US",
            "City": "New York",
            "Tier": 0,
            "Load": 90,
            "Status": 0,
            "Features": 0,
            "Servers": [
                {
                    "ID": "s5",
                    "Name": "US-FREE#9",
                    "Domain": "us-free-09.protonvpn.net",
                    "EntryIP": "4.4.4.4",
                    "X25519PublicKey": "peerkey5=",
                    "ProtocolEntries": {"WireGuardUDP": {"Ports": [51820]}},
                }
            ],
        },
    ]
}


class LogicalParsingTests(unittest.TestCase):
    def setUp(self):
        self.pool = parse(FIXTURE)

    def test_counts_all_logicals(self):
        self.assertEqual(len(self.pool), 5)

    def test_free_countries(self):
        self.assertEqual(sorted(self.pool.countries()), ["DE", "NL", "US"])

    def test_secure_core_detected(self):
        by_name = {item.name: item for item in self.pool}
        self.assertTrue(by_name["CH-NL#3"].secure_core)
        self.assertFalse(by_name["NL-FREE#1"].secure_core)

    def test_entry_fields(self):
        entry = self.pool[0].wireguard_entries[0]
        self.assertEqual(entry.endpoint_host, "1.2.3.4")
        self.assertEqual(entry.domain, "nl-free-01.protonvpn.net")
        self.assertEqual(entry.port, 51820)
        self.assertTrue(entry.x25519)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.pool = parse(FIXTURE)

    def test_country_by_code(self):
        self.assertEqual(selection.resolve_country(self.pool, "nl"), "NL")

    def test_country_by_name(self):
        self.assertEqual(selection.resolve_country(self.pool, "netherlands"), "NL")

    def test_unknown_country_raises(self):
        with self.assertRaises(selection.SelectionError):
            selection.resolve_country(self.pool, "atlantis")

    def test_free_tier_excludes_plus(self):
        found = selection.candidates(self.pool, "NL")
        self.assertEqual({item.name for item in found}, {"NL-FREE#1", "NL-FREE#2"})

    def test_paid_flag_includes_plus(self):
        found = selection.candidates(self.pool, "DE", include_paid=True)
        self.assertEqual({item.name for item in found}, {"DE#12"})

    def test_secure_core_never_selected_by_exit_country(self):
        found = selection.candidates(self.pool, "NL", include_paid=True)
        self.assertNotIn("CH-NL#3", {item.name for item in found})

    def test_offline_server_excluded(self):
        with self.assertRaises(selection.SelectionError):
            selection.candidates(self.pool, "US")

    def test_fastest_uses_lowest_load(self):
        picked = selection.select(self.pool, country="NL")
        self.assertEqual(picked.name, "NL-FREE#2")

    def test_server_by_name(self):
        picked = selection.select(self.pool, country="NL", server="NL-FREE#1")
        self.assertEqual(picked.name, "NL-FREE#1")

    def test_p2p_filter(self):
        found = selection.candidates(self.pool, "NL", p2p_only=True)
        self.assertEqual({item.name for item in found}, {"NL-FREE#2"})


class WireguardConfigTests(unittest.TestCase):
    def test_config_shape(self):
        from protonxlib import wireguard

        settings = wireguard.config("priv=", "peer=", "nl-free-01.protonvpn.net", 51820)
        self.assertEqual(settings["address"], "10.2.0.2/32")
        self.assertEqual(settings["allowed_ips"], "0.0.0.0/0")
        self.assertEqual(settings["dns"], "10.2.0.1")
        self.assertEqual(settings["endpoint_port"], 51820)

    def test_config_without_dns(self):
        from protonxlib import wireguard

        settings = wireguard.config("priv=", "peer=", "host", 51820, dns=None)
        self.assertIsNone(settings["dns"])

    def test_port_and_mtu_are_ints(self):
        from protonxlib import wireguard

        settings = wireguard.config("priv=", "peer=", "host", "51820", mtu="1400")
        self.assertIsInstance(settings["endpoint_port"], int)
        self.assertIsInstance(settings["mtu"], int)

    def test_preview_matches_helper_rendering(self):
        import base64
        import os

        from protonxlib import wireguard

        if not os.path.exists("/var/run/protonx/helper.sock"):
            self.skipTest("protonx helper not installed")
        key = base64.b64encode(bytes(range(32))).decode()
        settings = wireguard.config(key, key, "nl-free-01.protonvpn.net", 51820)
        text = wireguard.preview(settings)
        self.assertIn("PrivateKey = %s" % key, text)
        self.assertIn("Endpoint = nl-free-01.protonvpn.net:51820", text)
        self.assertIn("AllowedIPs = 0.0.0.0/0", text)
        self.assertNotIn("PostUp", text)


class IdentityTests(unittest.TestCase):
    def test_derivation_is_deterministic(self):
        from protonxlib import identity

        seed = bytes(range(32))
        first = identity.derive(seed)
        second = identity.derive(seed)
        self.assertEqual(first.x25519_priv_b64, second.x25519_priv_b64)
        self.assertEqual(first.ed25519_pub_b64, second.ed25519_pub_b64)

    def test_distinct_seeds_differ(self):
        from protonxlib import identity

        self.assertNotEqual(
            identity.create().x25519_pub_b64, identity.create().x25519_pub_b64
        )


if __name__ == "__main__":
    unittest.main()
