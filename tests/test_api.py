import inspect
import unittest

from protonxlib import api
from protonxlib.errors import ProtonxError


class ClientVersionTest(unittest.TestCase):
    def test_auth_calls_default_to_the_single_engine_version(self):
        # Proton gates the auth routes on a version allow-list; a second constant that nobody
        # called is how the Android port drifted onto a retired version and broke sign-in.
        signature = inspect.signature(api.auth_post)
        self.assertEqual(api.APP_VERSION, signature.parameters["app_version"].default)
        self.assertEqual("macos-vpn@4.5.0", api.APP_VERSION)

    def test_a_retired_client_version_asks_for_an_app_update(self):
        for code in (8004, 5003):
            with self.assertRaises(ProtonxError) as raised:
                api._raise_auth_error(422, {"Code": code, "Error": "Operation not allowed"})

            message = str(raised.exception)
            self.assertIn(str(code), message)
            self.assertIn("latest ProtonX release", message)

    def test_human_verification_still_names_the_browser_step(self):
        with self.assertRaises(ProtonxError) as raised:
            api._raise_auth_error(422, {"Code": 9001})

        message = str(raised.exception)
        self.assertIn("account.proton.me", message)
        self.assertNotIn("latest ProtonX release", message)


if __name__ == "__main__":
    unittest.main()
