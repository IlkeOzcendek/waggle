import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from panel.app import main
from panel.app.auth import verify_password
from panel.app.database import EventStore


class SetupFlowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "setup.db")
        self.store.initialize()
        self.store_patch = patch.object(main, "store", self.store)
        self.demo_patch = patch.object(main, "DEMO_MODE", False)
        self.store_patch.start()
        self.demo_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.demo_patch.stop()
        self.store_patch.stop()
        self.tempdir.cleanup()

    def test_owner_setup_then_login(self):
        self.assertEqual(
            self.client.get("/api/setup-status").json(),
            {"setup_required": True, "setup_available": True, "demo_mode": False, "demo_username": ""},
        )
        setup_response = self.client.post(
            "/api/setup",
            json={
                "display_name": "İlke Özçendek",
                "username": "ilke",
                "password": "strong-password-123",
            },
        )
        self.assertEqual(setup_response.status_code, 201)
        self.assertIn("waggle_session", setup_response.cookies)
        self.assertEqual(self.client.get("/api/me").json()["display_name"], "İlke Özçendek")
        self.assertEqual(
            self.client.get("/api/setup-status").json(),
            {"setup_required": False, "setup_available": False, "demo_mode": False, "demo_username": ""},
        )

        second_setup = self.client.post(
            "/api/setup",
            json={"display_name": "Other", "username": "other", "password": "another-password"},
        )
        self.assertEqual(second_setup.status_code, 409)

        fresh_client = TestClient(main.app)
        bad_login = fresh_client.post(
            "/api/login", json={"username": "ilke", "password": "wrong-password"}
        )
        self.assertEqual(bad_login.status_code, 401)
        good_login = fresh_client.post(
            "/api/login", json={"username": "ILKE", "password": "strong-password-123"}
        )
        self.assertEqual(good_login.status_code, 200)
        fresh_client.close()

    def test_setup_rejects_weak_or_invalid_credentials(self):
        weak = self.client.post(
            "/api/setup", json={"display_name": "İlke", "username": "ilke", "password": "short"}
        )
        self.assertEqual(weak.status_code, 422)
        invalid_username = self.client.post(
            "/api/setup",
            json={"display_name": "İlke", "username": "bad user", "password": "strong-password-123"},
        )
        self.assertEqual(invalid_username.status_code, 422)

    def test_demo_mode_never_demands_setup_but_keeps_it_available(self):
        """A demo server logs straight in with the built-in account, yet a real owner can
        still register alongside it — that owner is the non-demo channel."""
        with patch.object(main, "DEMO_MODE", True):
            self.assertEqual(
                self.client.get("/api/setup-status").json(),
                {
                    "setup_required": False,
                    "setup_available": True,
                    "demo_mode": True,
                    "demo_username": main.ADMIN_USERNAME,
                },
            )
            response = self.client.post(
                "/api/setup",
                json={"display_name": "İlke", "username": "ilke", "password": "strong-password-123"},
            )
            self.assertEqual(response.status_code, 201)
            self.assertFalse(self.client.get("/api/setup-status").json()["setup_available"])
            # The account that just registered is a real user, not the demo channel.
            self.assertIs(self.client.get("/api/me").json()["demo_mode"], False)

    def test_demo_flag_follows_the_account_not_the_server(self):
        with patch.object(main, "DEMO_MODE", True):
            # Entering the context runs the app's lifespan, which seeds the demo owner.
            with TestClient(main.app) as demo_client:
                self.client.post(
                    "/api/setup",
                    json={"display_name": "İlke", "username": "ilke", "password": "strong-password-123"},
                )
                owner = self.client.get("/api/me").json()
                self.assertEqual(owner["username"], "ilke")
                self.assertIs(owner["demo_mode"], False)

                demo_client.cookies.set(main.COOKIE_NAME, main.create_session(main.ADMIN_USERNAME))
                demo = demo_client.get("/api/me").json()
                self.assertEqual(demo["username"], main.ADMIN_USERNAME)
                self.assertIs(demo["demo_mode"], True)

    def test_seeded_demo_owner_cannot_sign_in_once_demo_mode_is_off(self):
        """A panel that once ran a demo must not keep a well-known password alive."""
        with patch.object(main, "DEMO_MODE", True):
            with TestClient(main.app) as demo_client:
                self.assertEqual(
                    demo_client.post(
                        "/api/login",
                        json={"username": main.ADMIN_USERNAME, "password": main.DEMO_PASSWORD},
                    ).status_code,
                    200,
                )
        # Same database, demo mode off: the seeded row is inert.
        self.assertEqual(
            TestClient(main.app)
            .post("/api/login", json={"username": main.ADMIN_USERNAME, "password": main.DEMO_PASSWORD})
            .status_code,
            401,
        )

    def test_seeded_demo_owner_does_not_block_first_time_setup(self):
        with patch.object(main, "DEMO_MODE", True):
            with TestClient(main.app) as demo_client:
                # The demo owner exists, yet a real owner can still be registered.
                self.assertTrue(demo_client.get("/api/setup-status").json()["setup_available"])
                self.assertEqual(
                    demo_client.post(
                        "/api/setup",
                        json={"display_name": "İlke", "username": "ilke", "password": "guclu-parola-123"},
                    ).status_code,
                    201,
                )
                self.assertFalse(demo_client.get("/api/setup-status").json()["setup_available"])

    def test_demo_owner_holds_its_own_password_and_recovery_code(self):
        """The point of the seeded row: the demo account behaves like a real one."""
        with patch.object(main, "DEMO_MODE", True):
            with TestClient(main.app) as demo_client:
                demo_client.post(
                    "/api/login",
                    json={"username": main.ADMIN_USERNAME, "password": main.DEMO_PASSWORD},
                )
                self.assertEqual(demo_client.post("/api/recovery-code").status_code, 201)
                self.assertTrue(demo_client.get("/api/recovery-code").json()["configured"])
                self.assertEqual(
                    demo_client.post(
                        "/api/password",
                        json={"current_password": main.DEMO_PASSWORD, "new_password": "demo-parolasi-456"},
                    ).status_code,
                    204,
                )

    def test_owner_can_change_password(self):
        self.client.post(
            "/api/setup",
            json={"display_name": "İlke", "username": "ilke", "password": "guclu-parola-123"},
        )
        wrong_current = self.client.post(
            "/api/password",
            json={"current_password": "yanlis-parola", "new_password": "yeni-parola-456"},
        )
        self.assertEqual(wrong_current.status_code, 403)
        too_short = self.client.post(
            "/api/password",
            json={"current_password": "guclu-parola-123", "new_password": "kisa"},
        )
        self.assertEqual(too_short.status_code, 422)
        same = self.client.post(
            "/api/password",
            json={"current_password": "guclu-parola-123", "new_password": "guclu-parola-123"},
        )
        self.assertEqual(same.status_code, 422)

        changed = self.client.post(
            "/api/password",
            json={"current_password": "guclu-parola-123", "new_password": "yeni-parola-456"},
        )
        self.assertEqual(changed.status_code, 204)

        fresh = TestClient(main.app)
        self.assertEqual(
            fresh.post("/api/login", json={"username": "ilke", "password": "guclu-parola-123"}).status_code,
            401,
        )
        self.assertEqual(
            fresh.post("/api/login", json={"username": "ilke", "password": "yeni-parola-456"}).status_code,
            200,
        )
        fresh.close()

    def _owner(self, password: str = "guclu-parola-123") -> None:
        self.client.post(
            "/api/setup",
            json={"display_name": "İlke", "username": "ilke", "password": password},
        )

    def test_recovery_code_resets_a_forgotten_password_once(self):
        self._owner()
        self.assertFalse(self.client.get("/api/recovery-code").json()["configured"])
        code = self.client.post("/api/recovery-code").json()["code"]
        self.assertTrue(self.client.get("/api/recovery-code").json()["configured"])

        anonymous = TestClient(main.app)
        # Retyped from paper: lower case, spaces instead of dashes.
        retyped = code.lower().replace("-", " ")
        self.assertEqual(
            anonymous.post(
                "/api/password-recovery",
                json={"username": "ilke", "recovery_code": retyped, "new_password": "yeni-parola-456"},
            ).status_code,
            204,
        )
        self.assertEqual(
            anonymous.post("/api/login", json={"username": "ilke", "password": "yeni-parola-456"}).status_code,
            200,
        )
        # Single use: the same code must not open the door a second time.
        replay = TestClient(main.app).post(
            "/api/password-recovery",
            json={"username": "ilke", "recovery_code": code, "new_password": "ucuncu-parola-789"},
        )
        self.assertEqual(replay.status_code, 403)
        anonymous.close()

    def test_recovery_rejects_a_wrong_code_without_revealing_the_account(self):
        self._owner()
        self.client.post("/api/recovery-code")
        unknown_user = TestClient(main.app).post(
            "/api/password-recovery",
            json={"username": "kimseyok", "recovery_code": "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2", "new_password": "yeni-parola-456"},
        )
        wrong_code = TestClient(main.app).post(
            "/api/password-recovery",
            json={"username": "ilke", "recovery_code": "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2", "new_password": "yeni-parola-456"},
        )
        self.assertEqual(unknown_user.status_code, 403)
        self.assertEqual(wrong_code.status_code, 403)
        # One message for both, or the endpoint would confirm which usernames exist.
        self.assertEqual(unknown_user.json()["detail"], wrong_code.json()["detail"])
        # The account keeps its original password.
        self.assertEqual(
            TestClient(main.app).post(
                "/api/login", json={"username": "ilke", "password": "guclu-parola-123"}
            ).status_code,
            200,
        )

    def test_generating_a_new_code_invalidates_the_previous_one(self):
        self._owner()
        first = self.client.post("/api/recovery-code").json()["code"]
        self.client.post("/api/recovery-code")
        stale = TestClient(main.app).post(
            "/api/password-recovery",
            json={"username": "ilke", "recovery_code": first, "new_password": "yeni-parola-456"},
        )
        self.assertEqual(stale.status_code, 403)

    def test_recovery_code_is_never_stored_in_plain_text(self):
        self._owner()
        code = self.client.post("/api/recovery-code").json()["code"]
        with sqlite3.connect(self.store.path) as connection:
            row = connection.execute(
                "SELECT recovery_salt, recovery_hash FROM users WHERE username = 'ilke'"
            ).fetchone()
        self.assertNotIn(main.normalize_recovery_code(code), row)
        self.assertTrue(verify_password(main.normalize_recovery_code(code), row[0], row[1]))

    def test_demo_account_is_not_demo_when_demo_mode_is_off(self):
        client = TestClient(main.app)
        client.cookies.set(main.COOKIE_NAME, main.create_session(main.ADMIN_USERNAME))
        self.assertIs(client.get("/api/me").json()["demo_mode"], False)
        client.close()


if __name__ == "__main__":
    unittest.main()
