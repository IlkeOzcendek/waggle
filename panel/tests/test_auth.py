import unittest

from panel.app.auth import create_session, read_session, verify_credentials


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


if __name__ == "__main__":
    unittest.main()
