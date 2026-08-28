import unittest
from unittest.mock import patch

from panel.app import auth
from panel.app.auth import LoginAttemptGuard, create_session, read_session, security_warnings, validate_security_config, verify_credentials, verify_device_key


class AuthenticationTest(unittest.TestCase):
    def test_login_attempt_guard_blocks_and_then_expires(self):
        guard = LoginAttemptGuard(max_attempts=3, window_seconds=60)
        guard.record_failure("client", now=10)
        guard.record_failure("client", now=20)
        guard.record_failure("client", now=30)
        self.assertGreater(guard.retry_after("client", now=30), 0)
        self.assertEqual(guard.retry_after("client", now=71), 0)

    def test_login_attempt_guard_resets_after_success(self):
        guard = LoginAttemptGuard(max_attempts=1, window_seconds=60)
        guard.record_failure("client", now=10)
        self.assertGreater(guard.retry_after("client", now=10), 0)
        guard.reset("client")
        self.assertEqual(guard.retry_after("client", now=10), 0)

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

    def test_development_defaults_produce_security_warnings(self):
        warnings = security_warnings()
        self.assertTrue(any("parolası" in warning for warning in warnings))
        self.assertTrue(any("cihaz anahtarı" in warning for warning in warnings))

    def test_production_rejects_security_warnings(self):
        with patch.object(auth, "ENVIRONMENT", "production"), patch.object(
            auth, "security_warnings", return_value=["Eksik güvenlik ayarı"]
        ):
            with self.assertRaises(RuntimeError):
                validate_security_config()


if __name__ == "__main__":
    unittest.main()
