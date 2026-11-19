import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from protonxlib import cache, catalog, cli
from protonxlib.errors import CatalogUnavailable
from tests.test_cli import FIXTURE


class CatalogTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = os.path.join(directory, "logicals.json")
        self.enterContext(patch.multiple(cache, CONFIG_DIR=directory, CACHE_PATH=self.path))

    def invoke(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = cli.main(args)
        return status, json.loads((output if status == 0 else errors).getvalue())

    def test_catalog_and_country_counts_match_the_connectable_free_pool(self):
        source = FIXTURE["LogicalServers"]
        offline = dict(source[0], Name="NL-OFFLINE#1", Status=0)
        no_wireguard = dict(source[0], Name="NL-NOKEY#1", Servers=[])
        pool = {"LogicalServers": [*source, offline, no_wireguard]}
        cache.save(pool, 42)
        status, snapshot = self.invoke("catalog", "--offline", "--json")
        self.assertEqual(status, 0)
        self.assertEqual(snapshot["fetchedAt"], 42)
        country, = snapshot["countries"]
        self.assertEqual(country["code"], "NL")
        self.assertEqual(country["servers"], [{"name": "NL-TEST#1", "city": "Amsterdam", "load": 7}])
        status, countries = self.invoke("countries", "--free", "--offline", "--json")
        self.assertEqual(status, 0)
        self.assertEqual([(item["code"], item["servers"]) for item in countries], [("NL", 1)])

    def test_empty_catalog_differs_from_cache_failure(self):
        status, failure = self.invoke("catalog", "--offline", "--json")
        self.assertEqual(status, 2)
        self.assertIn("No usable server list", failure["error"])
        cache.save({"LogicalServers": []}, 42)
        status, snapshot = self.invoke("catalog", "--offline", "--json")
        self.assertEqual(status, 0)
        self.assertEqual(snapshot, {"countries": [], "fetchedAt": 42})

    def test_refresh_validates_response_before_replacing_cache(self):
        cache.save(FIXTURE, 42)
        client = Mock()
        client.logicals.return_value = {"Code": 1000}
        with self.assertRaises(CatalogUnavailable):
            catalog.live(client)
        self.assertEqual(cache.load()["fetchedAt"], 42)
        self.assertEqual(cache.load()["payload"], FIXTURE)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_local_session_does_not_probe_tier_or_other_apps(self):
        with patch.multiple(cli.login, current=Mock(return_value={"username": "local"}), pending=Mock(return_value=None)), \
             patch.multiple(cli, _tier=Mock(side_effect=AssertionError), _default_username=Mock(side_effect=AssertionError)):
            status, snapshot = self.invoke("whoami", "--local", "--json")
        self.assertEqual(status, 0)
        self.assertEqual(snapshot, {"signedIn": True, "pending": False, "username": "local"})
