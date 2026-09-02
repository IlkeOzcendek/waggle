import csv
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from panel.app.database import EventStore
from panel.app.exports import build_export
from panel.app.models import HiveEventIn, ReportIn


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "exports.db")
        self.store.initialize()
        now = datetime.now(timezone.utc)
        self.event = self.store.add(
            HiveEventIn(
                hive_id="H3",
                timestamp=now,
                status="ALARM",
                anomaly_fraction=.91,
                consecutive_anomalies=30,
            )
        )
        self.store.add_report(
            ReportIn(
                period_start=now,
                period_end=now,
                summary="Kovanlar için dışa aktarma test raporu.",
                recommendations=["H3 kovanını kontrol edin."],
                hive_ids=["H3"],
                grounding_sources=["alarm-inspection"],
            )
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_alarm_csv_is_excel_compatible(self):
        self.store.acknowledge(self.event.id, "no_issue_found", "Ana arı görüldü.")
        content, media_type, filename = build_export(self.store, "alarms", "csv")
        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["hive_name"], "Çayır Kovanı")
        self.assertEqual(rows[0]["status"], "ALARM")
        self.assertEqual(rows[0]["consecutive_anomalies"], "30")
        self.assertEqual(rows[0]["inspection_result"], "no_issue_found")
        self.assertEqual(rows[0]["inspection_note"], "Ana arı görüldü.")
        self.assertEqual(media_type, "text/csv; charset=utf-8")
        self.assertTrue(filename.endswith(".csv"))

    def test_report_json_preserves_lists(self):
        content, media_type, filename = build_export(self.store, "reports", "json")
        reports = json.loads(content)
        self.assertEqual(reports[0]["recommendations"], ["H3 kovanını kontrol edin."])
        self.assertEqual(reports[0]["hive_ids"], ["H3"])
        self.assertEqual(reports[0]["language"], "tr")
        self.assertEqual(reports[0]["generator"], "manual")
        self.assertEqual(reports[0]["grounding_sources"], ["alarm-inspection"])
        self.assertEqual(reports[0]["report_type"], "weekly")
        self.assertIsNone(reports[0]["event_id"])
        self.assertEqual(media_type, "application/json; charset=utf-8")
        self.assertTrue(filename.endswith(".json"))

    def test_hive_export_contains_inactive_hives(self):
        self.store.set_hive_active("H1", False)
        content, _, _ = build_export(self.store, "hives", "json")
        hives = json.loads(content)
        archived = next(hive for hive in hives if hive["hive_id"] == "H1")
        self.assertFalse(archived["active"])


if __name__ == "__main__":
    unittest.main()
