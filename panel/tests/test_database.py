import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from panel.app.database import EventStore
from panel.app.auth import hash_password, verify_password
from panel.app.models import HiveCreate, HiveEventIn, HiveUpdate, ReportIn


class EventStoreTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "events.db")
        self.store.initialize()

    def test_first_owner_can_only_be_created_once(self):
        self.assertFalse(self.store.has_users())
        salt, password_hash = hash_password("owner-password-123")
        self.store.create_owner("İlke", "ilke", salt, password_hash)
        self.assertTrue(self.store.has_users())
        stored = self.store.user_credentials("ilke")
        self.assertEqual(stored[0], "İlke")
        self.assertTrue(verify_password("owner-password-123", stored[1], stored[2]))
        # Usernames are identifiers, matched exactly as typed.
        self.assertIsNone(self.store.user_credentials("ILKE"))
        self.assertIsNone(self.store.user_credentials("İlke"))
        with self.assertRaises(ValueError):
            self.store.create_owner("Başka", "another", salt, password_hash)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_add_and_read_event(self):
        event = HiveEventIn(
            hive_id="H3",
            timestamp=datetime.now(timezone.utc),
            status="ALARM",
            anomaly_fraction=.87,
            consecutive_anomalies=30,
            source_file="queen_loss_sample.wav",
        )
        created = self.store.add(event)
        saved = self.store.recent()[0]
        self.assertEqual(saved.id, created.id)
        self.assertEqual(saved.status, "ALARM")
        self.assertEqual(saved.anomaly_fraction, .87)
        self.assertEqual(saved.consecutive_anomalies, 30)
        self.assertEqual(saved.source_file, "queen_loss_sample.wav")
        self.assertEqual(self.store.summaries()[2].durum, "kritik")

    def test_empty_hives_have_no_data_status(self):
        self.assertTrue(all(hive.durum == "veri_yok" for hive in self.store.summaries()))

    def test_acknowledge_event(self):
        created = self.store.add(
            HiveEventIn(
                hive_id="H3",
                timestamp=datetime.now(timezone.utc),
                status="ALARM",
                anomaly_fraction=.91,
            )
        )
        acknowledged = self.store.acknowledge(created.id, "issue_confirmed", "Ana arı görülmedi.")
        self.assertIsNotNone(acknowledged.acknowledged_at)
        self.assertEqual(acknowledged.inspection_result, "issue_confirmed")
        self.assertEqual(acknowledged.inspection_note, "Ana arı görülmedi.")
        self.assertEqual(self.store.recent()[0].id, created.id)

    def test_add_and_read_report(self):
        now = datetime.now(timezone.utc)
        report = ReportIn(
            period_start=now,
            period_end=now,
            summary="Kovanlar için haftalık örnek değerlendirme raporu.",
            recommendations=["H3 kovanını kontrol edin."],
            hive_ids=["H1", "H3"],
            language="en",
            generator="foundry-local:phi-3.5-mini",
            grounding_sources=["alarm-interpretation", "alarm-inspection"],
            report_type="daily",
        )
        created = self.store.add_report(report)
        saved = self.store.reports()[0]
        self.assertEqual(saved.id, created.id)
        self.assertEqual(saved.hive_ids, ["H1", "H3"])
        self.assertEqual(saved.language, "en")
        self.assertEqual(saved.generator, "foundry-local:phi-3.5-mini")
        self.assertEqual(saved.grounding_sources, ["alarm-interpretation", "alarm-inspection"])
        self.assertEqual(saved.report_type, "daily")
        self.assertIsNone(saved.event_id)

    def test_add_hive_and_receive_its_event(self):
        hive = self.store.add_hive(HiveCreate(name="Arka Bahçe Kovanı", location="Gölbaşı"))
        self.assertEqual(hive.hive_id, "H4")
        self.assertTrue(self.store.has_hive("H4"))
        self.store.add(
            HiveEventIn(
                hive_id="H4",
                timestamp=datetime.now(timezone.utc),
                status="NORMAL",
                anomaly_fraction=.06,
            )
        )
        summary = self.store.summaries()[3]
        self.assertEqual(summary.name, "Arka Bahçe Kovanı")
        self.assertEqual(summary.durum, "normal")

    def test_update_archive_and_restore_hive(self):
        updated = self.store.update_hive(
            "H1", HiveUpdate(name="Yeni Bahçe Kovanı", location="Kuzey bahçesi")
        )
        self.assertEqual(updated.name, "Yeni Bahçe Kovanı")
        archived = self.store.set_hive_active("H1", False)
        self.assertFalse(archived.active)
        self.assertFalse(self.store.has_hive("H1"))
        self.assertEqual(len(self.store.hives(include_inactive=True)), 3)
        restored = self.store.set_hive_active("H1", True)
        self.assertTrue(restored.active)
        self.assertTrue(self.store.has_hive("H1"))

    def test_online_backup_preserves_a_consistent_snapshot(self):
        self.store.add(
            HiveEventIn(
                hive_id="H2",
                timestamp=datetime.now(timezone.utc),
                status="WATCH",
                anomaly_fraction=.67,
            )
        )
        backup_path = Path(self.tempdir.name) / "backup.db"
        self.store.backup_to(backup_path)
        self.store.add(
            HiveEventIn(
                hive_id="H1",
                timestamp=datetime.now(timezone.utc),
                status="NORMAL",
                anomaly_fraction=.05,
            )
        )
        backup_store = EventStore(backup_path)
        self.assertEqual(len(backup_store.recent()), 1)
        self.assertEqual(backup_store.recent()[0].hive_id, "H2")
        self.assertEqual(len(backup_store.hives(include_inactive=True)), 3)

    def test_restore_replaces_data_with_valid_backup(self):
        self.store.add(
            HiveEventIn(
                hive_id="H2",
                timestamp=datetime.now(timezone.utc),
                status="WATCH",
                anomaly_fraction=.67,
            )
        )
        backup_path = Path(self.tempdir.name) / "restore.db"
        self.store.backup_to(backup_path)
        self.store.add(
            HiveEventIn(
                hive_id="H1",
                timestamp=datetime.now(timezone.utc),
                status="NORMAL",
                anomaly_fraction=.05,
            )
        )
        self.store.restore_from(backup_path)
        self.store.initialize()
        self.assertEqual(len(self.store.recent()), 1)
        self.assertEqual(self.store.recent()[0].hive_id, "H2")

    def test_invalid_restore_is_rejected_without_changing_data(self):
        self.store.add(
            HiveEventIn(
                hive_id="H1",
                timestamp=datetime.now(timezone.utc),
                status="NORMAL",
                anomaly_fraction=.05,
            )
        )
        invalid_path = Path(self.tempdir.name) / "invalid.db"
        invalid_path.write_text("not a sqlite database")
        with self.assertRaises(ValueError):
            self.store.restore_from(invalid_path)
        self.assertEqual(len(self.store.recent()), 1)

    def test_diagnostics_report_counts_and_last_integration_activity(self):
        empty = self.store.diagnostics()
        self.assertEqual(empty["integrity"], "ok")
        self.assertEqual(empty["counts"], {"hives": 3, "events": 0, "reports": 0})
        self.assertIsNone(empty["last_event_at"])
        self.store.add(HiveEventIn(hive_id="H1", timestamp=datetime.now(timezone.utc), status="NORMAL", anomaly_fraction=.04))
        current = self.store.diagnostics()
        self.assertEqual(current["counts"]["events"], 1)
        self.assertIsNotNone(current["last_event_at"])

    def test_settings_are_persistent(self):
        defaults = self.store.settings()
        self.assertEqual(defaults["panel_name"], "Waggle")
        self.assertEqual(defaults["alarm_threshold"], .85)
        self.assertFalse(defaults["weather_enabled"])
        self.assertEqual(defaults["language"], "tr")
        saved = self.store.update_settings({
            "panel_name": "Arılığım",
            "location_name": "Ankara",
            "alarm_threshold": .92,
            "sound_enabled": False,
            "refresh_seconds": 10,
            "onboarding_completed": True,
            "weather_enabled": True,
            "language": "en",
        })
        self.assertEqual(saved["panel_name"], "Arılığım")
        self.assertFalse(saved["sound_enabled"])
        self.assertTrue(saved["onboarding_completed"])
        self.assertTrue(saved["weather_enabled"])
        self.assertEqual(saved["language"], "en")
        self.store.add(HiveEventIn(hive_id="H1", timestamp=datetime.now(timezone.utc), status="ALARM", anomaly_fraction=.90))
        self.assertEqual(self.store.summaries()[0].durum, "kritik")


if __name__ == "__main__":
    unittest.main()


class AcknowledgementAttributionTest(unittest.TestCase):
    """Who inspected the hive is part of the trail behind an AI decision."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "ack.db")
        self.store.initialize()

    def tearDown(self):
        self.tempdir.cleanup()

    def _alarm(self) -> int:
        hive = self.store.add_hive(HiveCreate(name="Kovan"))
        event = self.store.add(
            HiveEventIn(
                hive_id=hive.hive_id,
                timestamp=datetime.now(timezone.utc),
                status="ALARM",
                anomaly_fraction=0.9,
                consecutive_anomalies=30,
            )
        )
        return event.id

    def test_acknowledgement_records_the_account(self):
        event_id = self._alarm()
        acknowledged = self.store.acknowledge(
            event_id, "issue_confirmed", "Kraliçe görülmedi", acknowledged_by="ilke"
        )
        self.assertEqual(acknowledged.acknowledged_by, "ilke")
        self.assertEqual(self.store.recent()[0].acknowledged_by, "ilke")

    def test_events_acknowledged_without_an_account_stay_anonymous(self):
        event_id = self._alarm()
        acknowledged = self.store.acknowledge(event_id, "no_issue_found")
        self.assertIsNone(acknowledged.acknowledged_by)

    def test_column_is_added_to_a_database_created_before_it_existed(self):
        legacy = Path(self.tempdir.name) / "legacy.db"
        with sqlite3.connect(legacy) as connection:
            connection.execute(
                """CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, hive_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL, event TEXT NOT NULL, confidence REAL NOT NULL,
                    alindi TEXT NOT NULL)"""
            )
            connection.execute(
                """CREATE TABLE health_confirmations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, hive_id TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL, evidence TEXT NOT NULL, note TEXT,
                    accepted_for_enrollment INTEGER NOT NULL)"""
            )
        store = EventStore(legacy)
        store.initialize()
        with sqlite3.connect(legacy) as connection:
            events = {row[1] for row in connection.execute("PRAGMA table_info(events)")}
            confirmations = {
                row[1] for row in connection.execute("PRAGMA table_info(health_confirmations)")
            }
        self.assertIn("acknowledged_by", events)
        self.assertIn("confirmed_by", confirmations)


class LegacyUserTableTest(unittest.TestCase):
    """A panel created before workers existed has to keep working."""

    def test_role_constraint_is_widened_without_losing_the_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """CREATE TABLE users (
                        username TEXT PRIMARY KEY COLLATE NOCASE,
                        display_name TEXT NOT NULL,
                        password_salt TEXT NOT NULL,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'owner' CHECK (role IN ('owner')),
                        created_at TEXT NOT NULL)"""
                )
                connection.execute(
                    "INSERT INTO users VALUES ('ilke', 'İlke', 'salt', 'hash', 'owner', ?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
            store = EventStore(path)
            store.initialize()

            owners = store.users()
            self.assertEqual([user["username"] for user in owners], ["ilke"])
            self.assertTrue(owners[0]["active"])
            self.assertFalse(owners[0]["must_change_password"])
            # The old CHECK would have refused this row outright.
            store.add_worker("Ayşe", "ayse", "salt", "hash")
            self.assertEqual(
                sorted(user["role"] for user in store.users()), ["owner", "worker"]
            )
