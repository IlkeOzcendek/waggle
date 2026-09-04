import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from panel.app.database import EventStore
from panel.app.models import HiveEvent, HiveEventIn, ModelAssessment, Report, ReportIn
from panel.app.report_pdf import (build_report_pdf, measurement_label, notable_record_rows,
                                  recording_conditions, weather_label)


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

    def test_the_record_table_reports_how_deep_the_deviation_was(self):
        """Two records at the same anomalous-window ratio are not the same measurement.

        The printed table showed only the ratio, so a shallow deviation across a whole
        recording and a deep one across a whole recording were indistinguishable on the
        page a beekeeper carries to the hive.
        """
        now = datetime.now(timezone.utc)
        measured = HiveEvent(
            id=1, hive_id="H3", timestamp=now, status="ALARM", anomaly_fraction=1,
            anomaly_severity=0.37, consecutive_anomalies=30, source_file="demo.wav", alindi=now,
        )

        rows, widths = notable_record_rows([measured], "tr", {"H3": "Deneme Kovanı"})

        self.assertIn("Sapma şiddeti", rows[0])
        self.assertIn("%37", rows[1])
        self.assertEqual(len(rows[0]), len(widths))

    def test_a_period_recorded_before_the_depth_was_measured_keeps_the_narrow_table(self):
        """A column of dashes claims the measurement was taken and came out empty."""
        now = datetime.now(timezone.utc)
        older = HiveEvent(
            id=2, hive_id="H3", timestamp=now, status="ALARM", anomaly_fraction=1,
            consecutive_anomalies=30, source_file="demo.wav", alindi=now,
        )

        rows, widths = notable_record_rows([older], "en", {"H3": "Deneme Kovanı"})

        self.assertNotIn("Severity", rows[0])
        self.assertEqual(len(rows[0]), 5)
        self.assertEqual(len(rows[0]), len(widths))
        # The table still adds up to a width, in millimetres, that fits the page margins.
        self.assertLess(sum(widths), 170)


if __name__ == "__main__":
    unittest.main()


class ReportPdfProvenanceTest(unittest.TestCase):
    """The PDF is the artefact people take away, so the reasoning has to travel with it."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "pdf.db")
        self.store.initialize()
        self.store.seed_sample_hives()
        self.now = datetime.now(timezone.utc)
        event = self.store.add(HiveEventIn(hive_id="H3", timestamp=self.now, status="ALARM",
                                           anomaly_fraction=0.93, consecutive_anomalies=30))
        self.store.acknowledge(event.id, "issue_confirmed", "Kraliçe görülmedi", acknowledged_by="ilke")
        self.events = self.store.recent()

    def tearDown(self):
        self.tempdir.cleanup()

    def _report(self, **overrides):
        fields = dict(
            period_start=self.now - timedelta(days=7), period_end=self.now,
            summary="Çayır Kovanı (H3) kovanında kalıcı akustik değişim ölçüldü ve kontrol isteniyor.",
            recommendations=["Kovanı fiziksel kontrol edin"], hive_ids=["H3"], language="tr",
            generator="agent-framework:foundry-local:phi-3.5-mini+qwen2.5-1.5b",
            grounding_sources=["alarm-interpretation", "season-spring-swarm"],
            assessment=ModelAssessment(
                priority="immediate", pattern="persistent_acoustic_change",
                queen_loss_compatible=True, inspection_required=True,
                action_codes=["inspect_hive", "check_queen"],
                cross_check_model="qwen2.5-1.5b", cross_check_agreed=True),
        )
        fields.update(overrides)
        return self.store.add_report(ReportIn(**fields))

    def test_the_pdf_is_produced_with_the_assessment(self):
        content = build_report_pdf(self._report(), self.events, {"H3": "Çayır Kovanı"})
        self.assertTrue(content.startswith(b"%PDF"))
        # A report carrying a decision, a cross-check and its sources is materially longer
        # than the same report stripped of them.
        bare = self.store.add_report(ReportIn(
            period_start=self.now - timedelta(days=7), period_end=self.now,
            summary="Aynı özet metni, değerlendirme ve kaynak bilgisi olmadan yazıldı.",
            recommendations=["Kovanı fiziksel kontrol edin"], hive_ids=["H3"], language="tr",
            generator="safe-fallback", grounding_sources=[], assessment=None))
        stripped = build_report_pdf(bare, self.events, {"H3": "Çayır Kovanı"})
        self.assertGreater(len(content), len(stripped))

    def test_a_report_without_an_assessment_still_renders(self):
        """Reports written before the column existed must keep opening."""
        report = self.store.add_report(ReportIn(
            period_start=self.now - timedelta(days=7), period_end=self.now,
            summary="Eski bir rapor, model kararı olmadan da açılabilmelidir.",
            recommendations=["Kontrol edin"], hive_ids=["H3"], language="tr",
            generator="manual", grounding_sources=[], assessment=None))
        content = build_report_pdf(report, self.events, {"H3": "Çayır Kovanı"})
        self.assertTrue(content.startswith(b"%PDF"))

    def test_both_languages_render(self):
        for language in ("tr", "en"):
            with self.subTest(language=language):
                content = build_report_pdf(self._report(language=language), self.events, {"H3": "Çayır Kovanı"})
                self.assertTrue(content.startswith(b"%PDF"))

    def test_the_pdf_renders_with_the_acoustic_model_recorded(self):
        """The document names the model that measured the period, not only the one that wrote it."""
        measured = self.store.add(HiveEventIn(hive_id="H3", timestamp=self.now, status="ALARM",
                                              anomaly_fraction=0.91, consecutive_anomalies=22,
                                              model="H3.onnx"))
        content = build_report_pdf(self._report(), [measured], {"H3": "Çayır Kovanı"})
        self.assertTrue(content.startswith(b"%PDF"))


class MeasurementLabelTest(unittest.TestCase):
    """The first link in a report's chain is the ONNX profile that decided its events.

    The PDF named the model that phrased the report and nothing about the one that
    measured it, which reads as prose about nothing measured.
    """

    def _event(self, model):
        now = datetime.now(timezone.utc)
        return HiveEvent(id=1, hive_id="H3", timestamp=now, status="ALARM", anomaly_fraction=1,
                         consecutive_anomalies=30, model=model, alindi=now)

    def test_it_names_the_model_and_the_runtime(self):
        self.assertEqual(measurement_label([self._event("H3.onnx")], "tr"), "H3.onnx · ONNX Runtime")

    def test_several_profiles_are_all_named_once_each(self):
        events = [self._event("H1.onnx"), self._event("H3.onnx"), self._event("H3.onnx")]
        self.assertEqual(measurement_label(events, "en"), "H1.onnx, H3.onnx · ONNX Runtime")

    def test_events_from_before_the_column_existed_say_so_rather_than_inventing_a_model(self):
        self.assertEqual(measurement_label([self._event(None)], "tr"), "Kayıt yok")
        self.assertEqual(measurement_label([], "en"), "Not recorded")


class ReportPdfConditionsTest(unittest.TestCase):
    """The printed page has to agree with the retriever about what counts as bad weather.

    A page that flagged a recording the model did not — or stayed silent about one it did
    — would be two halves of the same system contradicting each other in front of the
    person holding the paper.
    """

    def _report(self):
        now = datetime.now(timezone.utc)
        return Report(
            id=1, period_start=now - timedelta(days=7), period_end=now,
            summary="Çayır Kovanı için kalıcı akustik değişim ölçüldü ve fiziksel kontrol isteniyor.",
            recommendations=["Kovanı fiziksel kontrol edin"], hive_ids=["H3"], language="tr",
            generator="agent-framework:foundry-local:phi", grounding_sources=[],
            report_type="weekly", event_id=None, created_at=now, assessment=None,
        )

    def _event(self, **overrides):
        now = datetime.now(timezone.utc)
        fields = dict(id=1, hive_id="H3", timestamp=now, status="ALARM", anomaly_fraction=1.0,
                      consecutive_anomalies=30, alindi=now)
        fields.update(overrides)
        return HiveEvent(**fields)

    def test_no_conditions_block_when_weather_was_never_stamped(self):
        self.assertIsNone(recording_conditions([self._event()], "tr"))

    def test_a_calm_period_is_reported_as_calm_rather_than_flagged(self):
        conditions = recording_conditions([self._event(wind_kmh=5.0, weather_code=1)], "tr")
        self.assertIsNotNone(conditions)
        self.assertFalse(conditions["adverse"])
        self.assertEqual(conditions["flagged"], [])

    def test_a_windy_alarm_is_flagged(self):
        conditions = recording_conditions([self._event(wind_kmh=34.0, weather_code=61)], "tr")
        self.assertTrue(conditions["adverse"])
        self.assertEqual(conditions["peak_wind"], 34.0)

    def test_the_sky_reads_in_the_report_language(self):
        self.assertEqual(weather_label(61, "tr"), "yağmur")
        self.assertEqual(weather_label(61, "en"), "rain")
        self.assertEqual(weather_label(None, "tr"), "—")

    def test_the_caveat_reaches_the_page_without_delaying_the_inspection(self):
        windy = build_report_pdf(self._report(), [self._event(wind_kmh=34.0, weather_code=61)],
                                 {"H3": "Çayır Kovanı"})
        calm = build_report_pdf(self._report(), [self._event(wind_kmh=5.0, weather_code=1)],
                                {"H3": "Çayır Kovanı"})
        self.assertTrue(windy.startswith(b"%PDF"))
        # The flagged period carries a warning block and a caveat the calm one does not.
        self.assertGreater(len(windy), len(calm))
