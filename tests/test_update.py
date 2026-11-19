import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from protonxlib import cli, update


class VersionTests(unittest.TestCase):
    def test_versions_compare_numerically(self):
        self.assertEqual(update._version_tuple("1.1.0"), (1, 1, 0))
        self.assertEqual(update._version_tuple("v1.2"), (1, 2, 0))
        self.assertGreater(update._version_tuple("1.2.0"), update._version_tuple("1.1.9"))
        self.assertGreater(update._version_tuple("1.10.0"), update._version_tuple("1.9.9"))


class CheckTests(unittest.TestCase):
    @mock.patch("protonxlib.update.latest_release", return_value="1.2.0")
    def test_newer_release_is_an_update(self, latest):
        status = update.check()
        self.assertTrue(status["update"])
        self.assertEqual(status["latest"], "1.2.0")
        self.assertEqual(status["current"], update.__version__)

    @mock.patch("protonxlib.update.latest_release", return_value=update.__version__)
    def test_current_release_is_not_an_update(self, latest):
        self.assertFalse(update.check()["update"])


class UpdateTests(unittest.TestCase):
    @mock.patch("protonxlib.update.install")
    @mock.patch("protonxlib.update.check", return_value={"current": "1.1.0", "latest": "1.2.0", "update": True})
    def test_assume_yes_installs(self, check, install):
        status = update.update(assume_yes=True)
        install.assert_called_once_with("1.2.0", "cli")
        self.assertTrue(status["installed"])

    @mock.patch("protonxlib.update.install")
    @mock.patch("protonxlib.update.check", return_value={"current": "1.1.0", "latest": "1.1.0", "update": False})
    def test_current_does_not_install(self, check, install):
        status = update.update(assume_yes=True)
        install.assert_not_called()
        self.assertFalse(status["update"])

    @mock.patch("protonxlib.update.install")
    @mock.patch("protonxlib.update.check", return_value={"current": "1.1.0", "latest": "1.2.0", "update": True})
    def test_app_target_installs_app(self, check, install):
        status = update.update(assume_yes=True, target="app")
        install.assert_called_once_with("1.2.0", "app")
        self.assertTrue(status["installed"])

    @mock.patch("protonxlib.update.install")
    @mock.patch("protonxlib.update.check", return_value={"current": "1.1.0", "latest": "1.2.0", "update": True})
    def test_check_only_does_not_install(self, check, install):
        status = update.update(check_only=True)
        install.assert_not_called()
        self.assertTrue(status["update"])


class CommandTests(unittest.TestCase):
    @mock.patch("protonxlib.update.check", return_value={"current": "1.1.0", "latest": "1.2.0", "update": True})
    def test_update_check_json(self, check):
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli.main(["update", "--check", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["update"])


if __name__ == "__main__":
    unittest.main()
