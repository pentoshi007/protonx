import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = os.path.join(ROOT, "protonx")
sys.path.insert(0, ROOT)

from protonxlib import service
SOCKET = "/var/run/protonx/helper.sock"

PEER_KEY = base64.b64encode(bytes(range(32, 64))).decode()

FIXTURE = {
    "LogicalServers": [
        {
            "ID": "T1",
            "Name": "NL-TEST#1",
            "ExitCountry": "NL",
            "EntryCountry": "NL",
            "City": "Amsterdam",
            "Tier": 0,
            "Load": 7,
            "Status": 1,
            "Features": 0,
            "Servers": [
                {
                    "ID": "t1",
                    "Name": "NL-TEST#1",
                    "Domain": "127.0.0.1",
                    "X25519PublicKey": PEER_KEY,
                    "ProtocolEntries": {"WireGuardUDP": {"Ports": [51820]}},
                }
            ],
        },
        {
            "ID": "T2",
            "Name": "DE-TEST#2",
            "ExitCountry": "DE",
            "EntryCountry": "DE",
            "City": "Berlin",
            "Tier": 2,
            "Load": 3,
            "Status": 1,
            "Features": 0,
            "Servers": [
                {
                    "ID": "t2",
                    "Name": "DE-TEST#2",
                    "Domain": "127.0.0.1",
                    "X25519PublicKey": PEER_KEY,
                    "ProtocolEntries": {"WireGuardUDP": {"Ports": [51820]}},
                }
            ],
        },
    ]
}


class CliTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        config_dir = os.path.join(self.home, ".config", "protonx")
        os.makedirs(config_dir)
        with open(os.path.join(config_dir, "logicals.json"), "w") as handle:
            json.dump({"fetchedAt": 1, "payload": FIXTURE}, handle)

    def run_cli(self, *args):
        env = dict(os.environ, HOME=self.home)
        return subprocess.run(
            [sys.executable, ENTRY] + list(args),
            capture_output=True,
            text=True,
            env=env,
        )

    def test_countries_json_is_machine_readable(self):
        result = self.run_cli("countries", "--offline", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual([row["code"] for row in rows], ["DE", "NL"])
        self.assertEqual(rows[0]["tier"], "plus")

    def test_servers_json_excludes_paid_by_default(self):
        result = self.run_cli("servers", "--country", "NL", "--offline", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual([row["name"] for row in rows], ["NL-TEST#1"])
        self.assertEqual(rows[0]["ports"], [51820])

    def test_servers_json_includes_paid_on_request(self):
        result = self.run_cli("servers", "--country", "DE", "--offline", "--paid", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row["name"] for row in json.loads(result.stdout)], ["DE-TEST#2"])

    def test_dry_run_json_reports_selection(self):
        if not os.path.exists(SOCKET):
            self.skipTest("protonx helper not installed")
        result = self.run_cli("connect", "--offline", "--country", "NL", "--dry-run", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["server"], "NL-TEST#1")
        self.assertEqual(payload["endpoint"], "127.0.0.1:51820")
        self.assertTrue(payload["dry_run"])
        self.assertIn("PrivateKey", payload["config"])

    def test_status_json_without_tunnel_is_valid(self):
        if not os.path.exists(SOCKET):
            self.skipTest("protonx helper not installed")
        result = self.run_cli("status", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("up", payload)
        self.assertIn("server", payload)

    def test_unknown_country_fails_with_message(self):
        result = self.run_cli("servers", "--country", "atlantis", "--offline", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown country", result.stderr)


class StateTests(unittest.TestCase):
    def setUp(self):
        from protonxlib import state

        self.state = state
        self.directory = tempfile.mkdtemp()
        self.original = state.STATE_PATH
        state.STATE_PATH = os.path.join(self.directory, "last.json")

    def tearDown(self):
        self.state.STATE_PATH = self.original

    def test_round_trip(self):
        self.state.save({"country": "NL", "server": "NL-TEST#1", "label": "NL-TEST#1"})
        self.assertEqual(self.state.load()["server"], "NL-TEST#1")

    def test_missing_file_returns_none(self):
        self.assertIsNone(self.state.load())

    def test_clear_removes_record(self):
        self.state.save({"server": "x"})
        self.state.clear()
        self.assertIsNone(self.state.load())


if __name__ == "__main__":
    unittest.main()


class TierTests(unittest.TestCase):
    def test_unsubscribed_account_reports_free(self):
        with mock.patch.object(service.api, "auth_post", return_value={"User": {"Subscribed": 0}}):
            self.assertEqual(service.tier({"userId": "u"}), 0)

    def test_subscribed_account_does_not_claim_free(self):
        with mock.patch.object(service.api, "auth_post", return_value={"User": {"Subscribed": 1}}):
            self.assertIsNone(service.tier({"userId": "u"}))

    def test_api_failure_is_not_reported_as_free(self):
        with mock.patch.object(service.api, "auth_post", side_effect=service.ProtonxError("boom")):
            self.assertIsNone(service.tier({"userId": "u"}))

    def test_labels(self):
        self.assertEqual(service.tier_label(0), "free")
        self.assertEqual(service.tier_label(None), "unknown")
