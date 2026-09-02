import base64
import unittest
from unittest.mock import patch

from panel.app import auth
from panel.app.auth import REMEMBERED_SESSION_SECONDS, SESSION_SECONDS, LoginAttemptGuard, create_session, hash_password, read_session, security_warnings, validate_security_config, verify_credentials, verify_device_key, verify_password


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

    def test_per_user_password_hash_round_trip(self):
        salt, password_hash = hash_password("a-strong-local-password")
        self.assertTrue(verify_password("a-strong-local-password", salt, password_hash))
        self.assertFalse(verify_password("wrong-password", salt, password_hash))
        self.assertNotIn("a-strong-local-password", password_hash)

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


class RememberMeTest(unittest.TestCase):
    """"Keep me signed in" lengthens the session; it never stores the password."""

    def test_remembered_sessions_outlive_ordinary_ones(self):
        ordinary = create_session("ilke")
        remembered = create_session("ilke", REMEMBERED_SESSION_SECONDS)
        self.assertEqual(read_session(ordinary), "ilke")
        self.assertEqual(read_session(remembered), "ilke")

        def expiry(token: str) -> int:
            payload = base64.urlsafe_b64decode(
                token.split(".", 1)[0] + "=" * (-len(token.split(".", 1)[0]) % 4)
            )
            return int(payload.decode().rsplit("|", 1)[1])

        self.assertGreater(expiry(remembered), expiry(ordinary))
        self.assertGreater(REMEMBERED_SESSION_SECONDS, SESSION_SECONDS)

    def test_a_remembered_session_still_expires(self):
        with patch("panel.app.auth.time.time", return_value=1_000_000):
            token = create_session("ilke", 60)
        with patch("panel.app.auth.time.time", return_value=1_000_000 + 61):
            self.assertIsNone(read_session(token))
