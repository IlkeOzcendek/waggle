"""Field worker accounts: what they may do, and what only the owner may do."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from panel.app import main
from panel.app.database import EventStore
from panel.app.models import DeviceCreate, HiveCreate, HiveEventIn


class WorkerAccountTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "workers.db")
        self.store.initialize()
        self.store_patch = patch.object(main, "store", self.store)
        self.demo_patch = patch.object(main, "DEMO_MODE", False)
        self.store_patch.start()
        self.demo_patch.start()
        self.owner = TestClient(main.app)
        self.owner.post(
            "/api/setup",
            json={"display_name": "İlke", "username": "ilke", "password": "guclu-parola-123"},
        )

    def tearDown(self):
        self.owner.close()
        self.demo_patch.stop()
        self.store_patch.stop()
        self.tempdir.cleanup()

    def _worker(self, password: str = "gecici-parola-123") -> TestClient:
        self.owner.post(
            "/api/users",
            json={"display_name": "Ayşe Saha", "username": "ayse", "password": password},
        )
        client = TestClient(main.app)
        client.post("/api/login", json={"username": "ayse", "password": password})
        return client

    def _settled_worker(self) -> TestClient:
        client = self._worker()
        client.post(
            "/api/password",
            json={"current_password": "gecici-parola-123", "new_password": "ayse-parolasi-456"},
        )
        return client

    def test_owner_adds_a_worker_who_must_set_their_own_password_first(self):
        worker = self._worker()
        self.assertTrue(worker.get("/api/me").json()["must_change_password"])
        self.assertEqual(worker.get("/api/me").json()["role"], "worker")
        # Nothing attributable may happen while two people know the password.
        hive = self.store.add_hive(HiveCreate(name="Kovan"))
        self.store.add_device(hive.hive_id, DeviceCreate(name="Saha telefonu"))
        blocked = worker.post(
            f"/api/hives/{hive.hive_id}/health-confirmations", json={"evidence": "queen_seen"}
        )
        self.assertEqual(blocked.status_code, 403)

        worker.post(
            "/api/password",
            json={"current_password": "gecici-parola-123", "new_password": "ayse-parolasi-456"},
        )
        self.assertFalse(worker.get("/api/me").json()["must_change_password"])
        allowed = worker.post(
            f"/api/hives/{hive.hive_id}/health-confirmations", json={"evidence": "queen_seen"}
        )
        self.assertEqual(allowed.status_code, 201)
        self.assertEqual(allowed.json()["confirmed_by"], "ayse")
        worker.close()

    def test_worker_may_do_field_work_but_not_own_the_apiary(self):
        worker = self._settled_worker()
        hive = self.store.add_hive(HiveCreate(name="Kovan"))
        event = self.store.add(
            HiveEventIn(
                hive_id=hive.hive_id, timestamp=datetime.now(timezone.utc), status="ALARM",
                anomaly_fraction=0.9, consecutive_anomalies=30,
            )
        )
        acknowledged = worker.post(
            f"/api/events/{event.id}/acknowledge", json={"result": "issue_confirmed"}
        )
        self.assertEqual(acknowledged.status_code, 200)
        self.assertEqual(acknowledged.json()["acknowledged_by"], "ayse")
        # Reading the panel stays open to the whole team.
        self.assertEqual(worker.get("/api/dashboard").status_code, 200)

        for method, path, payload in (
            ("post", "/api/hives", {"name": "Yeni"}),
            ("delete", f"/api/hives/{hive.hive_id}", None),
            ("post", f"/api/hives/{hive.hive_id}/devices", {"name": "Telefon"}),
            ("put", "/api/settings", {"panel_name": "X", "location_name": "Y", "alarm_threshold": 0.8, "sound_enabled": True, "refresh_seconds": 5}),
            ("post", "/api/users", {"display_name": "Yeni", "username": "yeni", "password": "parola-123456"}),
            ("get", "/api/users", None),
        ):
            with self.subTest(path=path, method=method):
                call = getattr(worker, method)
                response = call(path) if payload is None else call(path, json=payload)
                self.assertEqual(response.status_code, 403)
        worker.close()

    def test_disabling_a_worker_ends_their_open_session_at_once(self):
        worker = self._settled_worker()
        self.assertEqual(worker.get("/api/dashboard").status_code, 200)
        self.assertEqual(
            self.owner.patch("/api/users/ayse", json={"active": False}).status_code, 204
        )
        # The cookie is still a valid signed token; the account behind it is not.
        self.assertEqual(worker.get("/api/dashboard").status_code, 401)
        self.assertEqual(
            TestClient(main.app)
            .post("/api/login", json={"username": "ayse", "password": "ayse-parolasi-456"})
            .status_code,
            403,
        )
        self.owner.patch("/api/users/ayse", json={"active": True})
        self.assertEqual(
            TestClient(main.app)
            .post("/api/login", json={"username": "ayse", "password": "ayse-parolasi-456"})
            .status_code,
            200,
        )
        worker.close()

    def test_owner_issues_a_replacement_password_that_must_be_changed(self):
        worker = self._settled_worker()
        self.assertEqual(
            self.owner.post("/api/users/ayse/password", json={"password": "yeni-gecici-123"}).status_code,
            204,
        )
        fresh = TestClient(main.app)
        self.assertEqual(
            fresh.post("/api/login", json={"username": "ayse", "password": "ayse-parolasi-456"}).status_code,
            401,
        )
        fresh.post("/api/login", json={"username": "ayse", "password": "yeni-gecici-123"})
        self.assertTrue(fresh.get("/api/me").json()["must_change_password"])
        fresh.close()
        worker.close()

    def test_owner_cannot_lock_themselves_out(self):
        self.assertEqual(
            self.owner.patch("/api/users/ilke", json={"active": False}).status_code, 409
        )
        self.assertEqual(
            self.owner.post("/api/users/ilke/password", json={"password": "baska-parola-1"}).status_code,
            404,
        )

    def test_demo_account_can_manage_the_team(self):
        """Otherwise the team screen is hidden in exactly the mode it would be shown in."""
        with patch.object(main, "DEMO_MODE", True):
            with TestClient(main.app) as demo:
                demo.cookies.set(main.COOKIE_NAME, main.create_session(main.ADMIN_USERNAME, stamp=main._stamp_for(main.ADMIN_USERNAME)))
                me = demo.get("/api/me").json()
                self.assertTrue(me["manages_accounts"])
                self.assertEqual(me["role"], "owner")
                self.assertTrue(me["demo_mode"])
                created = demo.post(
                    "/api/users",
                    json={"display_name": "Ayşe", "username": "ayse", "password": "gecici-parola-123"},
                )
                self.assertEqual(created.status_code, 201)
                self.assertEqual(demo.get("/api/users").status_code, 200)
                # And it keeps its own recovery code like any other owner.
                self.assertEqual(demo.post("/api/recovery-code").status_code, 201)

    def test_workers_never_manage_the_team_even_in_demo_mode(self):
        with patch.object(main, "DEMO_MODE", True):
            worker = self._settled_worker()
            self.assertFalse(worker.get("/api/me").json()["manages_accounts"])
            self.assertEqual(worker.get("/api/users").status_code, 403)
            worker.close()

    def test_the_same_username_cannot_be_taken_twice(self):
        self.owner.post(
            "/api/users",
            json={"display_name": "Ayşe", "username": "ayse", "password": "gecici-parola-123"},
        )
        duplicate = self.owner.post(
            "/api/users",
            json={"display_name": "Başkası", "username": "ayse", "password": "gecici-parola-123"},
        )
        self.assertEqual(duplicate.status_code, 409)
        owner_name = self.owner.post(
            "/api/users",
            json={"display_name": "Sahte", "username": "ilke", "password": "gecici-parola-123"},
        )
        self.assertEqual(owner_name.status_code, 409)

    def test_usernames_differing_only_by_case_are_separate_accounts(self):
        """Deliberate: a username is matched exactly, so "Ayse" is not "ayse"."""
        self.owner.post(
            "/api/users",
            json={"display_name": "Ayşe", "username": "ayse", "password": "gecici-parola-123"},
        )
        other = self.owner.post(
            "/api/users",
            json={"display_name": "Ayşe B.", "username": "Ayse", "password": "gecici-parola-456"},
        )
        self.assertEqual(other.status_code, 201)
        usernames = [user["username"] for user in self.store.users()]
        self.assertIn("ayse", usernames)
        self.assertIn("Ayse", usernames)
        # And each signs in only with its own password.
        first = TestClient(main.app)
        self.assertEqual(
            first.post("/api/login", json={"username": "ayse", "password": "gecici-parola-456"}).status_code,
            401,
        )
        self.assertEqual(
            first.post("/api/login", json={"username": "ayse", "password": "gecici-parola-123"}).status_code,
            200,
        )
        first.close()


if __name__ == "__main__":
    unittest.main()


class SessionInvalidationTest(unittest.TestCase):
    """Changing a password has to end the sessions opened with the old one.

    Sessions are signed tokens with no server-side record, so "sign out everywhere" cannot
    be done by deleting rows. The token carries a marker of the password it was minted
    with instead, and a request whose marker no longer matches is refused.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "sessions.db")
        self.store.initialize()
        self.store_patch = patch.object(main, "store", self.store)
        self.demo_patch = patch.object(main, "DEMO_MODE", False)
        self.store_patch.start()
        self.demo_patch.start()
        self.owner = TestClient(main.app)
        self.owner.post(
            "/api/setup",
            json={"display_name": "İlke", "username": "ilke", "password": "guclu-parola-123"},
        )

    def tearDown(self):
        self.owner.close()
        self.demo_patch.stop()
        self.store_patch.stop()
        self.tempdir.cleanup()

    def _second_device(self, username: str, password: str) -> TestClient:
        """The same account signed in somewhere else — a phone, a borrowed laptop."""
        client = TestClient(main.app)
        self.assertEqual(
            client.post("/api/login", json={"username": username, "password": password}).status_code,
            200,
        )
        self.assertEqual(client.get("/api/me").status_code, 200)
        return client

    def test_changing_your_password_ends_your_other_sessions(self):
        phone = self._second_device("ilke", "guclu-parola-123")
        self.owner.post(
            "/api/password",
            json={"current_password": "guclu-parola-123", "new_password": "yeni-parola-456"},
        )
        self.assertEqual(phone.get("/api/me").status_code, 401)
        phone.close()

    def test_but_not_the_session_you_changed_it_from(self):
        """Otherwise choosing a password would throw you out onto the sign-in screen."""
        self.owner.post(
            "/api/password",
            json={"current_password": "guclu-parola-123", "new_password": "yeni-parola-456"},
        )
        self.assertEqual(self.owner.get("/api/me").status_code, 200)

    def test_the_new_password_signs_in_normally_afterwards(self):
        self.owner.post(
            "/api/password",
            json={"current_password": "guclu-parola-123", "new_password": "yeni-parola-456"},
        )
        again = self._second_device("ilke", "yeni-parola-456")
        again.close()

    def test_a_reset_the_owner_issues_ends_the_worker_open_session(self):
        """The reason to reset a worker's password is usually that it is not private any more."""
        self.owner.post(
            "/api/users",
            json={"display_name": "Ayşe Saha", "username": "ayse", "password": "gecici-parola-123"},
        )
        worker = self._second_device("ayse", "gecici-parola-123")
        self.owner.post("/api/users/ayse/password", json={"password": "yeni-gecici-789"})
        self.assertEqual(worker.get("/api/me").status_code, 401)
        worker.close()

    def test_resetting_a_worker_leaves_the_owner_signed_in(self):
        self.owner.post(
            "/api/users",
            json={"display_name": "Ayşe Saha", "username": "ayse", "password": "gecici-parola-123"},
        )
        self.owner.post("/api/users/ayse/password", json={"password": "yeni-gecici-789"})
        self.assertEqual(self.owner.get("/api/me").status_code, 200)

    def test_recovering_a_password_ends_the_sessions_too(self):
        """Recovery exists for a lost machine; leaving its session open would defeat it."""
        lost_laptop = self._second_device("ilke", "guclu-parola-123")
        code = self.owner.post("/api/recovery-code").json()["code"]
        stranger = TestClient(main.app)
        self.assertEqual(
            stranger.post("/api/password-recovery", json={
                "username": "ilke", "recovery_code": code, "new_password": "kurtarilan-parola-1",
            }).status_code,
            204,
        )
        self.assertEqual(lost_laptop.get("/api/me").status_code, 401)
        lost_laptop.close()
        stranger.close()
