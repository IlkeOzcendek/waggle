import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from panel.app.database import EventStore
from panel.app.models import HiveEventIn, ReportIn


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
            event="queenless_suspected",
            confidence=.87,
        )
        created = self.store.add(event)
        self.assertEqual(self.store.recent()[0].id, created.id)
        self.assertEqual(self.store.summaries()[2].durum, "kritik")

    def test_empty_hives_have_no_data_status(self):
        self.assertTrue(all(hive.durum == "veri_yok" for hive in self.store.summaries()))

    def test_acknowledge_event(self):
        created = self.store.add(
            HiveEventIn(
                hive_id="H3",
                timestamp=datetime.now(timezone.utc),
                event="queenless_suspected",
                confidence=.91,
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
        )
        created = self.store.add_report(report)
        saved = self.store.reports()[0]
        self.assertEqual(saved.id, created.id)
        self.assertEqual(saved.hive_ids, ["H1", "H3"])


if __name__ == "__main__":
    unittest.main()
