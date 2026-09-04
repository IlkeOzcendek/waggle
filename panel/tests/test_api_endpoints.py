"""The HTTP surface of the export and guidance endpoints.

`exports.py` is unit-tested directly, but the panel reaches it through a route that keeps
its *own* copy of the dataset allowlist. The two lists have already drifted apart once and
the only symptom was a 404 on a card that had just been added to the page — no test failed,
because no test crossed the HTTP boundary. These do.
"""

import csv
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import get_args
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from panel.app import main
from panel.app.database import EventStore
from panel.app.exports import Dataset
from panel.app.models import HiveCreate, HiveEventIn, ModelAssessment, ReportIn

DATASETS = list(get_args(Dataset))


class ExportEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "exports.db")
        self.store.initialize()
        self.store.seed_sample_hives()
        self.store_patch = patch.object(main, "store", self.store)
        self.demo_patch = patch.object(main, "DEMO_MODE", False)
        self.store_patch.start()
        self.demo_patch.start()
        self.client = TestClient(main.app)
        self.client.post(
            "/api/setup",
            json={"display_name": "İlke", "username": "ilke", "password": "guclu-parola-123"},
        )
        now = datetime.now(timezone.utc)
        event = self.store.add(HiveEventIn(hive_id="H3", timestamp=now, status="ALARM",
                                           anomaly_fraction=0.93, consecutive_anomalies=30))
        self.store.acknowledge(event.id, "issue_confirmed", "Kraliçe görülmedi", acknowledged_by="ilke")
        self.store.add_report(ReportIn(
            period_start=now - timedelta(days=7), period_end=now,
            summary="Kalıcı akustik değişim ölçüldü.", recommendations=["Kovanı kontrol edin"],
            hive_ids=["H3"], language="tr", generator="agent-framework:foundry-local:phi-3.5-mini",
            grounding_sources=["alarm-interpretation"],
            assessment=ModelAssessment(
                priority="immediate", pattern="persistent_acoustic_change",
                queen_loss_compatible=True, inspection_required=True,
                action_codes=["inspect_hive"], cross_check_model="qwen2.5-1.5b",
                cross_check_agreed=True)))

    def tearDown(self):
        self.client.close()
        self.demo_patch.stop()
        self.store_patch.stop()
        self.tempdir.cleanup()

    def test_every_declared_dataset_is_reachable_over_http(self):
        """The route's allowlist and the exports module's own list must not drift apart."""
        for dataset in DATASETS:
            for file_format in ("csv", "json"):
                with self.subTest(dataset=dataset, file_format=file_format):
                    response = self.client.get(f"/api/export/{dataset}.{file_format}")
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(f"{dataset}", response.headers["content-disposition"])

    def test_an_unknown_dataset_is_a_404_rather_than_a_crash(self):
        self.assertEqual(self.client.get("/api/export/passwords.csv").status_code, 404)
        self.assertEqual(self.client.get("/api/export/events.xlsx").status_code, 404)

    def test_csv_exports_have_a_header_row_even_with_no_rows(self):
        """An empty file with no header tells the reader nothing about what is missing."""
        empty = EventStore(Path(self.tempdir.name) / "empty.db")
        empty.initialize()
        with patch.object(main, "store", empty):
            client = TestClient(main.app)
            for dataset in DATASETS:
                with self.subTest(dataset=dataset):
                    rows = list(csv.reader(io.StringIO(client.get(f"/api/export/{dataset}.csv").text)))
                    self.assertTrue(rows and rows[0])
            client.close()

    def test_the_acknowledging_account_reaches_the_export(self):
        rows = json.loads(self.client.get("/api/export/alarms.json").text)
        self.assertTrue(any(row.get("acknowledged_by") == "ilke" for row in rows))

    def test_the_report_export_carries_the_model_decision(self):
        row = json.loads(self.client.get("/api/export/reports.json").text)[0]
        self.assertEqual(row["priority"], "immediate")
        self.assertEqual(row["pattern"], "persistent_acoustic_change")
        self.assertEqual(row["cross_check_model"], "qwen2.5-1.5b")

    def test_the_guidance_export_is_the_reviewed_knowledge_base(self):
        rows = json.loads(self.client.get("/api/export/guidance.json").text)
        self.assertGreater(len(rows), 20)
        self.assertTrue(any(row["id"] == "alarm-interpretation" for row in rows))


class GuidanceEndpointTest(unittest.TestCase):
    """The panel shows what an assessment rested on, so the text has to be fetchable."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "guidance.db")
        self.store.initialize()
        self.store_patch = patch.object(main, "store", self.store)
        self.demo_patch = patch.object(main, "DEMO_MODE", False)
        self.store_patch.start()
        self.demo_patch.start()
        self.client = TestClient(main.app)
        self.client.post(
            "/api/setup",
            json={"display_name": "İlke", "username": "ilke", "password": "guclu-parola-123"},
        )

    def tearDown(self):
        self.client.close()
        self.demo_patch.stop()
        self.store_patch.stop()
        self.tempdir.cleanup()

    def test_it_returns_the_whole_base_in_both_languages(self):
        turkish = self.client.get("/api/guidance?language=tr").json()
        english = self.client.get("/api/guidance?language=en").json()
        self.assertEqual(len(turkish), len(english))
        self.assertGreater(len(turkish), 20)
        by_id = {entry["id"]: entry["text"] for entry in turkish}
        self.assertNotEqual(by_id["alarm-interpretation"],
                            next(e["text"] for e in english if e["id"] == "alarm-interpretation"))

    def test_it_can_be_narrowed_to_the_ids_a_report_recorded(self):
        response = self.client.get("/api/guidance?ids=alarm-interpretation,season-spring-swarm")
        returned = {entry["id"] for entry in response.json()}
        self.assertEqual(returned, {"alarm-interpretation", "season-spring-swarm"})

    def test_an_unknown_id_yields_nothing_rather_than_an_error(self):
        """A report from an older guidance version must not break the page that opens it."""
        response = self.client.get("/api/guidance?ids=note-that-was-removed")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_an_unsupported_language_is_rejected(self):
        self.assertEqual(self.client.get("/api/guidance?language=de").status_code, 422)

    def test_a_search_is_ranked_by_the_retriever_a_report_is_grounded_with(self):
        """The base was searched with a substring match while reports used the retriever.

        The one screen where a person can inspect the knowledge base then behaved unlike
        the retrieval it exists to explain, and a query could rank a passing mention above
        the note actually about the topic.
        """
        results = self.client.get("/api/guidance?q=varroa&language=tr").json()
        self.assertEqual(results[0]["id"], "season-autumn-varroa")
        self.assertTrue(all(entry["tags"] for entry in results))
        # A ranked answer, not the whole base filtered.
        self.assertLess(len(results), len(self.client.get("/api/guidance?language=tr").json()))

    def test_a_search_puts_the_note_about_the_topic_first(self):
        """What the sound may mean comes before what to do about it.

        The action note opens with "Kraliçesizlik doğrulanırsa", so putting it first would
        offer a remedy before the reader has been told the reading is not a diagnosis. A
        search for the narrower "kraliçesiz" does surface it first, which is the query that
        asks for it.
        """
        results = self.client.get("/api/guidance?q=kraliçe&language=tr").json()
        self.assertEqual(results[0]["id"], "alarm-interpretation")

        narrower = self.client.get("/api/guidance?q=kraliçesiz&language=tr").json()
        self.assertEqual(narrower[0]["id"], "queen-replacement")

    def test_a_search_finds_a_note_through_a_turkish_suffix(self):
        """Turkish suffixes attach to the stem, so the searched word rarely appears whole.

        Every one of these returned nothing at all while the note it belongs to was in the
        base: the reader had to guess the exact form the passage happened to use.
        """
        for query, expected in (
            ("kraliçesiz", "queen-replacement"),
            ("oğullar", "season-spring-swarm"),
            ("kış", "season-winter-cluster"),
        ):
            with self.subTest(query=query):
                results = self.client.get(f"/api/guidance?q={query}&language=tr").json()
                self.assertEqual(results[0]["id"], expected)

    def test_a_search_that_matches_nothing_returns_nothing(self):
        self.assertEqual(self.client.get("/api/guidance?q=kuantum+bilgisayar").json(), [])

    def test_a_search_honours_its_limit(self):
        self.assertLessEqual(len(self.client.get("/api/guidance?q=kovan&limit=2").json()), 2)


class EventGuidanceEndpointTest(unittest.TestCase):
    """Retrieval used to be reachable only by generating a report.

    An alarm on the screen therefore carried no guidance until a weekly report had been
    written about it, even though the retriever needs no model and answers per event.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "event-guidance.db")
        self.store.initialize()
        self.store.seed_sample_hives()
        self.store_patch = patch.object(main, "store", self.store)
        self.demo_patch = patch.object(main, "DEMO_MODE", False)
        self.store_patch.start()
        self.demo_patch.start()
        self.client = TestClient(main.app)
        self.client.post(
            "/api/setup",
            json={"display_name": "İlke", "username": "ilke", "password": "guclu-parola-123"},
        )
        now = datetime.now(timezone.utc)
        self.alarm = self.store.add(HiveEventIn(hive_id="H3", timestamp=now, status="ALARM",
                                                anomaly_fraction=0.93, consecutive_anomalies=30))
        self.normal = self.store.add(HiveEventIn(hive_id="H1", timestamp=now, status="NORMAL",
                                                 anomaly_fraction=0.05, consecutive_anomalies=0))

    def tearDown(self):
        self.client.close()
        self.demo_patch.stop()
        self.store_patch.stop()
        self.tempdir.cleanup()

    def _ids(self, event_id: int, query: str = "") -> list[str]:
        response = self.client.get(f"/api/events/{event_id}/guidance{query}")
        self.assertEqual(response.status_code, 200)
        return [entry["id"] for entry in response.json()]

    def test_an_alarm_gets_alarm_guidance(self):
        known = {entry["id"] for entry in self.client.get("/api/guidance").json()}
        returned = self._ids(self.alarm.id)
        self.assertTrue(returned)
        self.assertTrue(set(returned) <= known)

    def test_the_notes_follow_the_event_rather_than_the_label(self):
        """A normal record and an alarm must not be handed the same passages."""
        self.assertNotEqual(self._ids(self.alarm.id), self._ids(self.normal.id))

    def test_it_honours_the_limit(self):
        self.assertLessEqual(len(self._ids(self.alarm.id, "?limit=1")), 1)

    def test_both_languages_are_served(self):
        turkish = self.client.get(f"/api/events/{self.alarm.id}/guidance?language=tr").json()
        english = self.client.get(f"/api/events/{self.alarm.id}/guidance?language=en").json()
        self.assertEqual([e["id"] for e in turkish], [e["id"] for e in english])
        self.assertNotEqual(turkish[0]["text"], english[0]["text"])

    def test_an_unknown_event_is_a_404(self):
        self.assertEqual(self.client.get("/api/events/9999/guidance").status_code, 404)


class EventModelProvenanceTest(unittest.TestCase):
    """Which acoustic model decided an event is the first link in a report's chain."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "provenance.db")
        self.store.initialize()
        self.store.seed_sample_hives()
        self.store_patch = patch.object(main, "store", self.store)
        self.demo_patch = patch.object(main, "DEMO_MODE", False)
        self.store_patch.start()
        self.demo_patch.start()
        self.client = TestClient(main.app)
        self.client.post(
            "/api/setup",
            json={"display_name": "İlke", "username": "ilke", "password": "guclu-parola-123"},
        )

    def tearDown(self):
        self.client.close()
        self.demo_patch.stop()
        self.store_patch.stop()
        self.tempdir.cleanup()

    def test_the_model_that_decided_an_event_survives_the_round_trip(self):
        now = datetime.now(timezone.utc)
        stored = self.store.add(HiveEventIn(hive_id="H3", timestamp=now, status="ALARM",
                                            anomaly_fraction=0.9, consecutive_anomalies=25,
                                            model="H3.onnx"))
        self.assertEqual(stored.model, "H3.onnx")
        self.assertEqual(self.store.event(stored.id).model, "H3.onnx")
        self.assertEqual(self.store.recent()[0].model, "H3.onnx")

    def test_an_event_without_a_recorded_model_still_reads_back(self):
        """Rows written before the column existed must keep loading."""
        now = datetime.now(timezone.utc)
        stored = self.store.add(HiveEventIn(hive_id="H1", timestamp=now, status="NORMAL",
                                            anomaly_fraction=0.04))
        self.assertIsNone(self.store.event(stored.id).model)

    def test_the_model_reaches_the_api_and_the_export(self):
        now = datetime.now(timezone.utc)
        self.store.add(HiveEventIn(hive_id="H3", timestamp=now, status="ALARM",
                                   anomaly_fraction=0.9, consecutive_anomalies=25,
                                   model="mendeley_isolation_monitor.onnx"))
        served = self.client.get("/api/events?limit=5").json()
        self.assertEqual(served[0]["model"], "mendeley_isolation_monitor.onnx")
        rows = json.loads(self.client.get("/api/export/events.json").text)
        self.assertTrue(any(row["model"] == "mendeley_isolation_monitor.onnx" for row in rows))


class ReportGenerationStatusTest(unittest.TestCase):
    """A run reports what the model is doing, not only that it started.

    The page showed a counter climbing past three minutes with nothing behind it, and a
    blocking request could not have told a stalled model from a slow one: both are silence
    until the timeout. Now the answer arrives token by token, so both facts exist.
    """

    def setUp(self):
        self.original = dict(main.REPORT_GENERATION)
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "generation.db")
        self.store.initialize()
        self.store_patch = patch.object(main, "store", self.store)
        self.store_patch.start()
        self.client = TestClient(main.app)
        # The status endpoint is behind a panel session, like everything a person reads.
        self.client.post(
            "/api/setup",
            json={"display_name": "İlke", "username": "ilke", "password": "guclu-parola-123"},
        )

    def tearDown(self):
        self.client.close()
        self.store_patch.stop()
        self.tempdir.cleanup()
        main.REPORT_GENERATION.clear()
        main.REPORT_GENERATION.update(self.original)

    def _status(self, **state):
        main.REPORT_GENERATION.update(state)
        with patch.object(main, "LLM_ENABLED", True):
            return self.client.get("/api/reports/generation-status").json()

    def test_a_run_that_is_still_writing_is_slow_rather_than_stalled(self):
        began = datetime.now(timezone.utc) - timedelta(seconds=main.REPORT_GENERATION_STALL_SECONDS + 120)
        status = self._status(
            running=True,
            started_at=began.isoformat(),
            finished_at=None,
            written_characters=430,
            written_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        )

        self.assertFalse(status["stalled"])
        self.assertEqual(status["written_characters"], 430)
        self.assertLess(status["silent_seconds"], 60)
        self.assertGreater(status["elapsed_seconds"], main.REPORT_GENERATION_STALL_SECONDS)

    def test_a_run_that_has_stopped_writing_is_stalled(self):
        """The count only grows, so it cannot answer this on its own: a single character
        written early would otherwise clear the flag for the rest of the run."""
        silence = datetime.now(timezone.utc) - timedelta(seconds=main.REPORT_GENERATION_STALL_SECONDS + 60)
        status = self._status(
            running=True,
            started_at=(silence - timedelta(seconds=60)).isoformat(),
            finished_at=None,
            written_characters=12,
            written_at=silence.isoformat(),
        )

        self.assertTrue(status["stalled"])

    def test_a_run_that_has_written_nothing_yet_is_measured_from_its_start(self):
        began = datetime.now(timezone.utc) - timedelta(seconds=main.REPORT_GENERATION_STALL_SECONDS + 10)
        status = self._status(
            running=True, started_at=began.isoformat(), finished_at=None,
            written_characters=0, written_at=None,
        )

        self.assertTrue(status["stalled"])

    def test_the_device_the_model_runs_on_travels_with_the_status(self):
        """The catalogue had been reporting it all along and nothing read it."""
        status = self._status(running=False, started_at=None, finished_at=None, device="GPU")

        self.assertEqual(status["device"], "GPU")


class AcousticModelStatusTest(unittest.TestCase):
    """The component named after the acoustic model only ever checked event freshness.

    A deleted or unreadable model file left the panel reporting a healthy acoustic
    pipeline right up until the next recording failed, and the recorded joblib-versus-ONNX
    decision comparison — the evidence that the conversion changed nothing — was shown
    nowhere at all.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = EventStore(self.root / "status.db")
        self.store.initialize()
        self.store.seed_sample_hives()
        self.model = self.root / "reference.onnx"
        self.model.write_bytes(b"onnx")
        self.parity = self.root / "parity.json"
        self.parity.write_text(json.dumps({"verified": True, "verification_rows": 5400,
                                           "different_decisions": 0}), encoding="utf-8")
        # The sample hives are seeded pointing at the repository's packaged model. Repoint
        # them inside the fixture so a test is not deciding on a file outside it.
        self.seeded = self.root / "seeded.onnx"
        self.seeded.write_bytes(b"onnx")
        for profile in self.store.monitoring_profiles():
            self.store.activate_profile(profile["hive_id"], str(self.seeded))
        self.patches = [
            patch.object(main, "store", self.store),
            patch.object(main, "SENSOR_MODEL_PATH", self.model),
            patch.object(main, "ONNX_PARITY_REPORT", self.parity),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()

    def test_a_present_and_verified_model_reads_ok(self):
        component = main.acoustic_model_status()
        self.assertEqual(component.status, "ok")
        self.assertIn("5400", component.detail)
        self.assertIn("ONNX Runtime", component.detail)

    def test_a_missing_model_file_is_a_warning_that_names_it(self):
        self.model.unlink()
        component = main.acoustic_model_status()
        self.assertEqual(component.status, "warning")
        self.assertIn("reference.onnx", component.detail)

    def test_a_monitored_hive_whose_profile_vanished_is_reported(self):
        """The panel says the hive is monitored; the file behind that claim may be gone."""
        self.store.activate_profile("H2", str(self.root / "H2.onnx"))
        component = main.acoustic_model_status()
        self.assertEqual(component.status, "warning")
        self.assertIn("H2", component.detail)

    def test_present_profiles_are_counted_rather_than_complained_about(self):
        component = main.acoustic_model_status()
        self.assertEqual(component.status, "ok")
        self.assertIn("3 kovan kendi profiliyle izleniyor", component.detail)

    def test_an_unverified_profile_is_not_counted_as_a_verified_one(self):
        """Seeded and pre-existing profiles carry no comparison, so none is claimed."""
        self.assertNotIn("karar eşleşmesiyle doğrulandı", main.acoustic_model_status().detail)

    def test_a_hive_profile_that_was_checked_at_training_says_so(self):
        self.store.activate_profile("H2", str(self.seeded),
                                    {"windows": 96, "features": 21, "different_decisions": 0})
        self.assertIn("1/3 kovan profili karar eşleşmesiyle doğrulandı",
                      main.acoustic_model_status().detail)

    def test_a_stored_comparison_that_found_a_difference_is_not_counted(self):
        """Training cannot publish one, but a hand-edited database must not be believed."""
        self.store.activate_profile("H2", str(self.seeded),
                                    {"windows": 96, "features": 21, "different_decisions": 3})
        self.assertNotIn("karar eşleşmesiyle doğrulandı", main.acoustic_model_status().detail)

    def test_an_unverified_conversion_is_not_presented_as_a_verified_one(self):
        self.parity.unlink()
        component = main.acoustic_model_status()
        self.assertEqual(component.status, "waiting")
        self.assertIn("karar eşleşmesi raporu bulunamadı", component.detail)

    def test_a_corrupt_parity_report_does_not_crash_the_status_page(self):
        self.parity.write_text("{ not json", encoding="utf-8")
        self.assertEqual(main.acoustic_model_status().status, "waiting")

    def test_a_parity_report_with_an_unusable_row_count_does_not_raise(self):
        """The file is on disk and can be hand-edited or written half-way."""
        for rows in ('"many"', "null", "0", "[]"):
            with self.subTest(rows=rows):
                self.parity.write_text(f'{{"verified": true, "verification_rows": {rows}}}',
                                       encoding="utf-8")
                component = main.acoustic_model_status()
                self.assertEqual(component.status, "waiting")
                self.assertIn("karar eşleşmesi raporu bulunamadı", component.detail)

    def test_a_report_that_says_the_decisions_differed_is_not_treated_as_verified(self):
        self.parity.write_text(json.dumps({"verified": False, "verification_rows": 5400,
                                           "different_decisions": 7}), encoding="utf-8")
        self.assertEqual(main.acoustic_model_status().status, "waiting")

    def test_a_profile_with_an_empty_model_path_reads_as_missing(self):
        """Path("") is the directory the panel runs from, and that directory exists."""
        self.store.activate_profile("H2", "   ")
        component = main.acoustic_model_status()
        self.assertEqual(component.status, "warning")
        self.assertIn("H2", component.detail)

    def test_it_is_served_as_part_of_the_system_status(self):
        with patch.object(main, "DEMO_MODE", False):
            client = TestClient(main.app)
            client.post("/api/setup", json={"display_name": "İlke", "username": "ilke",
                                            "password": "guclu-parola-123"})
            components = client.get("/api/system-status").json()["components"]
            client.close()
        self.assertIn("acoustic-model", [component["key"] for component in components])


class MonitoringProfilesTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "profiles.db")
        self.store.initialize()
        self.store.seed_sample_hives()

    def tearDown(self):
        self.tempdir.cleanup()

    def _listed(self) -> dict:
        return {profile["hive_id"]: profile for profile in self.store.monitoring_profiles()}

    def test_a_hive_still_learning_is_not_listed_as_monitored(self):
        hive = self.store.add_hive(HiveCreate(name="Yeni Kovan"))
        self.assertNotIn(hive.hive_id, self._listed())
        self.store.activate_profile(hive.hive_id, f"results/hive_profiles/{hive.hive_id}.onnx")
        self.assertEqual(self._listed()[hive.hive_id]["model_path"], f"results/hive_profiles/{hive.hive_id}.onnx")

    def test_the_training_comparison_is_kept_with_the_profile(self):
        """Training checked joblib against ONNX and the answer was being thrown away."""
        hive = self.store.add_hive(HiveCreate(name="Doğrulanan Kovan"))
        self.store.activate_profile(hive.hive_id, "results/hive_profiles/x.onnx",
                                    {"windows": 96, "features": 21, "different_decisions": 0})
        verification = self._listed()[hive.hive_id]["verification"]
        self.assertEqual(verification["different_decisions"], 0)
        self.assertEqual(verification["windows"], 96)

    def test_a_profile_activated_without_a_comparison_reads_back_as_none(self):
        """Profiles trained before this was recorded must not look verified."""
        hive = self.store.add_hive(HiveCreate(name="Eski Kovan"))
        self.store.activate_profile(hive.hive_id, "results/hive_profiles/y.onnx")
        self.assertIsNone(self._listed()[hive.hive_id]["verification"])

if __name__ == "__main__":
    unittest.main()


class SystemStatusChainTest(unittest.TestCase):
    """The components are a pipeline, and the page can only draw it if the API returns one.

    A recording travels microphone → ONNX profile → stored decision → report engine →
    panel. Returned as an unordered set, the page could only show which tile is red, never
    where the flow stopped — which is the question someone opens this page to ask.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "status.db")
        self.store.initialize()
        self.store.seed_sample_hives()

    def tearDown(self):
        self.tempdir.cleanup()

    def _components(self):
        with patch.object(main, "store", self.store):
            return [component.model_dump() for component in main.system_status().components]

    def test_the_components_arrive_in_the_order_the_data_travels(self):
        keys = [component["key"] for component in self._components()]
        self.assertEqual(keys, ["device", "acoustic-model", "database", "reports", "panel"])

    def test_a_component_that_can_go_stale_says_how_long_it_may_stay_silent(self):
        """Without the threshold the page can say "late" but never "late by how much"."""
        components = {component["key"]: component for component in self._components()}
        self.assertEqual(components["device"]["stale_after_seconds"], main.DEVICE_STALE_SECONDS)
        self.assertEqual(components["reports"]["stale_after_seconds"], main.REPORT_STALE_SECONDS)
        # The panel is answering the request, so it can never be stale.
        self.assertIsNone(components["panel"]["stale_after_seconds"])

    def test_a_component_needing_attention_carries_what_to_do_about_it(self):
        components = {component["key"]: component for component in self._components()}
        device = components["device"]
        self.assertNotEqual(device["status"], "ok")
        self.assertTrue(device["remedies"], "a component in trouble offered no next step")

    def test_a_healthy_component_offers_no_remedy(self):
        """Steps beside something that is working read as steps that are still owed."""
        components = {component["key"]: component for component in self._components()}
        self.assertEqual(components["panel"]["status"], "ok")
        self.assertEqual(components["panel"]["remedies"], [])


class ComponentHistoryTest(unittest.TestCase):
    """"Cihaz verisi gecikiyor" is a claim about a pattern, so the pattern has to be shown.

    An hour of silence after months of hourly contact is a different problem from a device
    that was always sporadic, and the page asserted the first without ever showing which
    one it was.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "history.db")
        self.store.initialize()
        self.store.seed_sample_hives()
        self.now = datetime.now(timezone.utc)
        for index, status in enumerate(("NORMAL", "WATCH", "ALARM")):
            self.store.add(HiveEventIn(hive_id="H3", timestamp=self.now - timedelta(hours=index),
                                       status=status, anomaly_fraction=0.5))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_the_device_history_names_the_hive_and_what_it_brought(self):
        with patch.object(main, "store", self.store):
            history = main.component_history("device", limit=20)
        self.assertEqual(history.component, "device")
        # Newest contact first: the question is "when did it last get through".
        self.assertEqual([entry.status for entry in history.entries], ["NORMAL", "WATCH", "ALARM"])
        self.assertGreater(history.entries[0].at, history.entries[-1].at)
        self.assertTrue(all(entry.label for entry in history.entries))

    def test_the_report_history_is_kept_separately(self):
        with patch.object(main, "store", self.store):
            self.store.add_report(ReportIn(
                period_start=self.now - timedelta(days=7), period_end=self.now,
                summary="Dönem boyunca kovanlar öğrenilmiş profillerinin içinde kaldı.",
                recommendations=["İzlemeye devam edin"], hive_ids=["H3"], language="tr",
                generator="safe-fallback", grounding_sources=[]))
            history = main.component_history("reports", limit=20)
        self.assertEqual(len(history.entries), 1)
        self.assertEqual(history.entries[0].status, "ok")

    def test_a_component_that_is_asked_rather_than_heard_from_has_no_history(self):
        """The panel and the database are queried; they never "get through" to anything."""
        for component in ("panel", "database", "acoustic-model"):
            with self.subTest(component=component):
                with patch.object(main, "store", self.store), self.assertRaises(HTTPException) as raised:
                    main.component_history(component, limit=20)
                self.assertEqual(raised.exception.status_code, 404)

    def test_only_the_components_with_a_history_advertise_one(self):
        with patch.object(main, "store", self.store):
            components = {item.key: item for item in main.system_status().components}
        self.assertTrue(components["device"].has_history)
        self.assertTrue(components["reports"].has_history)
        self.assertFalse(components["panel"].has_history)
        self.assertFalse(components["database"].has_history)
