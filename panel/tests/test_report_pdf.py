import unittest
from datetime import datetime, timedelta, timezone

from panel.app.models import HiveEvent, Report
from panel.app.report_pdf import build_report_pdf


class ReportPdfTest(unittest.TestCase):
    def test_pdf_contains_a_complete_report_document(self):
        now = datetime.now(timezone.utc)
        report = Report(
            id=1, period_start=now-timedelta(days=1), period_end=now,
            summary="Kovan seslerinde kalıcı bir akustik değişim değerlendirildi.",
            recommendations=["Kovanı fiziksel olarak kontrol edin."], hive_ids=["H3"],
            language="tr", generator="agent-framework:foundry-local:phi",
            grounding_sources=["alarm-inspection"], report_type="daily", event_id=None,
            created_at=now,
        )
        event = HiveEvent(
            id=1, hive_id="H3", timestamp=now, status="ALARM", anomaly_fraction=1,
            consecutive_anomalies=30, source_file="demo.wav", alindi=now,
            acknowledged_at=None, inspection_result=None, inspection_note=None,
        )
        content = build_report_pdf(report, [event], {"H3": "Deneme Kovanı"})
        self.assertTrue(content.startswith(b"%PDF-"))
        self.assertGreater(len(content), 5_000)


if __name__ == "__main__":
    unittest.main()
