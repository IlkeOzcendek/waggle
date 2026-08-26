import unittest

from panel.app.main import is_cross_site_request, security_headers


class WebSecurityTest(unittest.TestCase):
    def test_cross_site_detection_allows_devices_without_browser_headers(self):
        self.assertFalse(is_cross_site_request(None, None, "http://waggle.local"))
        self.assertFalse(
            is_cross_site_request(
                "http://waggle.local", "same-origin", "http://waggle.local"
            )
        )
        self.assertTrue(
            is_cross_site_request("https://evil.example", None, "http://waggle.local")
        )
        self.assertTrue(is_cross_site_request(None, "cross-site", "http://waggle.local"))

    def test_security_headers_are_added(self):
        headers = security_headers("/api/health")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_api_docs_keep_their_external_assets_available(self):
        self.assertNotIn("Content-Security-Policy", security_headers("/docs"))


if __name__ == "__main__":
    unittest.main()
