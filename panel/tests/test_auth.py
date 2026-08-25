import unittest

from panel.app.auth import create_session, read_session, verify_credentials, verify_device_key


class AuthenticationTest(unittest.TestCase):
    def test_demo_credentials(self):
        self.assertTrue(verify_credentials("admin", "waggle-demo"))
        self.assertFalse(verify_credentials("admin", "wrong-password"))

    def test_signed_session(self):
        token = create_session("admin")
        self.assertEqual(read_session(token), "admin")

    def test_tampered_session_is_rejected(self):
        token = create_session("admin")
        payload, signature = token.split(".", 1)
        tampered = f"{payload[:-1]}x.{signature}"
        self.assertIsNone(read_session(tampered))

    def test_device_key(self):
        self.assertTrue(verify_device_key("waggle-device-demo"))
        self.assertFalse(verify_device_key("wrong-device-key"))
        self.assertFalse(verify_device_key(None))


if __name__ == "__main__":
    unittest.main()
