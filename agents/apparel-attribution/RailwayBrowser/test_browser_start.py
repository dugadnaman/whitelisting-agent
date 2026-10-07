"""Run with python -m unittest discover -s agents/apparel-attribution/RailwayBrowser.

Configuration-only tests: no browser, credentials, network, deployment, or sheet writes.
"""
import runpy
import unittest
from pathlib import Path

GUARD = runpy.run_path(str(Path(__file__).with_name("browser-start.py")))
validate_config = GUARD["validate_config"]
private_addresses = GUARD["private_addresses"]


class BrowserDeploymentGuardTests(unittest.TestCase):
    def config(self, **changes):
        # Deterministic synthetic test values, never deployment credentials.
        return {
            "CUSTOM_USER": "test-corporate-user",
            "PASSWORD": "0123456789abcdefABCDEF!@#$%^&*xyz",
            "APPAREL_BROWSER_STREAM_ACCESS": "trusted-network",
            "CHROME_CLI": GUARD["CHROME_CLI"],
            **changes,
        }

    def test_explicit_trusted_network_and_authenticated_proxy(self):
        validate_config(self.config())
        validate_config(self.config(
            APPAREL_BROWSER_STREAM_ACCESS="authenticated-proxy",
            APPAREL_BROWSER_PUBLIC_URL="https://login.corporate.test/browser/",
            APPAREL_BROWSER_PROXY_AUTH="oidc",
        ))

    def test_missing_or_weak_authentication_and_debugger_overrides_fail_closed(self):
        for change in (
            {"CUSTOM_USER": ""}, {"CUSTOM_USER": "administrator"},
            {"CUSTOM_USER": "aaaaaaaa"}, {"CUSTOM_USER": "user:name"},
            {"PASSWORD": ""}, {"PASSWORD": "a" * 40},
            {"PASSWORD": "change-me-0123456789ABCDEF!@#$%^&*"},
            {"APPAREL_BROWSER_STREAM_ACCESS": ""},
            {"CHROME_CLI": "--remote-debugging-address=0.0.0.0 --remote-debugging-port=9222"},
            {"RAILWAY_PUBLIC_DOMAIN": "unguarded.test"},
            {"RAILWAY_TCP_PROXY_DOMAIN": "public-debugger.test"},
        ):
            with self.subTest(change=tuple(change)):
                with self.assertRaises(ValueError) as caught:
                    validate_config(self.config(**change))
                self.assertNotIn(self.config()["PASSWORD"], str(caught.exception))

    def test_internet_stream_requires_https_and_robust_proxy_auth(self):
        config = self.config(
            APPAREL_BROWSER_STREAM_ACCESS="authenticated-proxy",
            APPAREL_BROWSER_PUBLIC_URL="https://login.corporate.test/",
            APPAREL_BROWSER_PROXY_AUTH="oidc",
        )
        for change in (
            {"APPAREL_BROWSER_PUBLIC_URL": ""},
            {"APPAREL_BROWSER_PUBLIC_URL": "http://login.corporate.test/"},
            {"APPAREL_BROWSER_PUBLIC_URL": "https://user:secret@login.corporate.test/"},
            {"APPAREL_BROWSER_PROXY_AUTH": ""},
            {"APPAREL_BROWSER_PROXY_AUTH": "basic"},
        ):
            with self.subTest(change=tuple(change)):
                with self.assertRaises(ValueError):
                    validate_config({**config, **change})

    def test_debugger_binds_only_assigned_private_network_addresses(self):
        interfaces = [{"addr_info": [{"local": value} for value in (
            "127.0.0.1", "::1", "10.1.2.3", "172.19.0.4", "192.168.1.5",
            "fd12:3456::1", "fe80::1", "203.0.113.4", "8.8.8.8",
        )]}]
        self.assertEqual(private_addresses(interfaces), [
            "10.1.2.3", "172.19.0.4", "192.168.1.5", "fd12:3456::1",
        ])
        self.assertEqual(private_addresses(interfaces, "fd12:3456::1"), ["fd12:3456::1"])
        for requested in ("0.0.0.0", "::", "127.0.0.1", "8.8.8.8", "10.9.9.9"):
            with self.subTest(requested=requested):
                with self.assertRaises(ValueError):
                    private_addresses(interfaces, requested)
        with self.assertRaises(ValueError):
            private_addresses([{"addr_info": [{"local": "127.0.0.1"}]}])



if __name__ == "__main__":
    unittest.main()
