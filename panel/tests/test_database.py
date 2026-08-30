import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from panel.app.database import EventStore
from panel.app.models import HiveCreate, HiveEventIn, HiveUpdate, ReportIn


class EventStoreTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "events.db")
        self.store.initialize()

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
        acknowledged = self.store.acknowledge(created.id)
        self.assertIsNotNone(acknowledged.acknowledged_at)
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
        )
        created = self.store.add_report(report)
        saved = self.store.reports()[0]
        self.assertEqual(saved.id, created.id)
        self.assertEqual(saved.hive_ids, ["H1", "H3"])
        self.assertEqual(saved.language, "en")
        self.assertEqual(saved.generator, "foundry-local:phi-3.5-mini")
        self.assertEqual(saved.grounding_sources, ["alarm-interpretation", "alarm-inspection"])

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
