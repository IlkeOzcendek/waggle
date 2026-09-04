import csv
import io
import json
import sqlite3
import zipfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from panel.app.database import EventStore
from panel.app.exports import CATALOGUE, build_bundle, build_export, export_rows, export_summary, filter_rows
from panel.app.models import DeviceCreate, HealthConfirmationIn, HiveCreate, HiveEventIn, ReportIn


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "exports.db")
        self.store.initialize()
        # The sample hives are no longer created for every database, so a test that
        # relies on them asks for them: the dependency is stated rather than inherited.
        self.store.seed_sample_hives()
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


class AuditExportTest(unittest.TestCase):
    """What the AI layer rests on has to be exportable, or it cannot be audited."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "audit.db")
        self.store.initialize()
        self.store.seed_sample_hives()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_events_carry_the_account_that_inspected_the_hive(self):
        event = self.store.add(
            HiveEventIn(hive_id="H3", timestamp=datetime.now(timezone.utc), status="ALARM",
                        anomaly_fraction=0.9, consecutive_anomalies=30)
        )
        self.store.acknowledge(event.id, "issue_confirmed", "Kraliçe yok", acknowledged_by="ilke")
        row = export_rows(self.store, "events")[0]
        self.assertEqual(row["acknowledged_by"], "ilke")

    def test_field_checks_are_exportable_with_their_author(self):
        self.store.add_health_confirmation(
            "H3", HealthConfirmationIn(evidence="queen_seen", note="Görüldü"), confirmed_by="ilke"
        )
        rows = export_rows(self.store, "confirmations")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["confirmed_by"], "ilke")
        self.assertTrue(rows[0]["accepted_for_enrollment"])

    def test_the_guidance_base_is_exportable(self):
        rows = export_rows(self.store, "guidance")
        self.assertGreaterEqual(len(rows), 28)
        self.assertEqual(sorted(rows[0]), ["conditions", "en", "id", "tags", "tr"])

    def test_both_new_datasets_render_as_csv_and_json(self):
        for dataset in ("confirmations", "guidance"):
            for file_format in ("csv", "json"):
                with self.subTest(dataset=dataset, file_format=file_format):
                    content, media_type, filename = build_export(self.store, dataset, file_format)
                    self.assertTrue(content)
                    self.assertIn(dataset, filename)


class EnrollmentAndDeviceExportTest(unittest.TestCase):
    """The evidence behind the enrollment gate, and which microphone produced it.

    Both were written to the database from the beginning and neither could be downloaded.
    The panel showed a percentage nobody could check.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "enrollment.db")
        self.store.initialize()
        self.hive = self.store.add_hive(HiveCreate(name="Çayır Kovanı", location="Bahçe"))
        self.device = self.store.add_device(self.hive.hive_id, DeviceCreate(name="Saha telefonu", kind="phone"))
        now = datetime.now(timezone.utc)
        with sqlite3.connect(Path(self.tempdir.name) / "enrollment.db") as connection:
            for day in range(3):
                for index in range(2):
                    connection.execute(
                        """INSERT INTO enrollment_recordings
                           (hive_id, device_id, recorded_at, filename, window_count,
                            healthy_confirmed, feature_names, features)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (self.hive.hive_id, self.device.device_id,
                         (now - timedelta(days=day)).isoformat(), f"kayit-{day}-{index}.wav",
                         18, 1 if index == 0 else 0, "[]", "[]"),
                    )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_each_recording_is_one_row_named_by_hive_and_device(self):
        rows = export_rows(self.store, "enrollment")
        self.assertEqual(len(rows), 6)
        self.assertEqual({row["hive_name"] for row in rows}, {"Çayır Kovanı"})
        self.assertEqual({row["device_id"] for row in rows}, {self.device.device_id})

    def test_the_calendar_day_is_spelled_out_because_the_threshold_counts_days(self):
        """Forty recordings in one afternoon are still one day, and the export must show that."""
        rows = export_rows(self.store, "enrollment")
        self.assertEqual(len({row["recorded_day"] for row in rows}), 3)
        self.assertTrue(all(len(row["recorded_day"]) == 10 for row in rows))

    def test_healthy_confirmation_is_carried_because_only_those_recordings_count(self):
        rows = export_rows(self.store, "enrollment")
        self.assertEqual(sum(1 for row in rows if row["healthy_confirmed"]), 3)

    def test_the_feature_vectors_are_left_out(self):
        """A long numeric blob helps nobody in a spreadsheet, and the audio is gone anyway."""
        rows = export_rows(self.store, "enrollment")
        self.assertNotIn("features", rows[0])
        self.assertNotIn("feature_names", rows[0])

    def test_devices_say_which_hive_they_belong_to(self):
        rows = export_rows(self.store, "devices")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hive_name"], "Çayır Kovanı")
        self.assertEqual(rows[0]["kind"], "phone")
        self.assertTrue(rows[0]["active"])

    def test_both_render_as_csv_with_a_header_when_empty(self):
        empty = EventStore(Path(self.tempdir.name) / "empty.db")
        empty.initialize()
        for dataset in ("enrollment", "devices"):
            with self.subTest(dataset=dataset):
                content, _, _ = build_export(empty, dataset, "csv")
                self.assertTrue(content.decode("utf-8").splitlines()[0].strip())


class ExportRangeTest(unittest.TestCase):
    """A date range has to narrow what it can and say so where it cannot.

    Hives, devices and guidance describe the setup a measurement happened in, not the
    measurement. Filtering them by a period would strip the very rows the filtered events
    point at, so the range leaves them whole — and the page says that rather than showing
    a filter that quietly did nothing.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "range.db")
        self.store.initialize()
        self.store.seed_sample_hives()
        self.now = datetime.now(timezone.utc)
        for days in (0, 5, 40, 400):
            self.store.add(HiveEventIn(hive_id="H3", timestamp=self.now - timedelta(days=days),
                                       status="NORMAL", anomaly_fraction=0.1))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_a_range_narrows_the_datasets_that_have_a_period(self):
        rows = export_rows(self.store, "events")
        self.assertEqual(len(filter_rows(rows, "events", self.now - timedelta(days=30))), 2)
        self.assertEqual(len(filter_rows(rows, "events", self.now - timedelta(days=90))), 3)
        self.assertEqual(len(filter_rows(rows, "events")), 4)

    def test_a_range_leaves_the_setup_datasets_whole(self):
        hives = export_rows(self.store, "hives")
        self.assertEqual(filter_rows(hives, "hives", self.now - timedelta(days=1)), hives)

    def test_the_summary_reports_the_count_and_whether_the_range_applied(self):
        summary = {row["dataset"]: row for row in export_summary(self.store, self.now - timedelta(days=30))}
        self.assertEqual(summary["events"]["count"], 2)
        self.assertEqual(summary["events"]["total"], 4)
        self.assertTrue(summary["events"]["period_filtered"])
        self.assertFalse(summary["hives"]["period_filtered"])
        self.assertEqual(summary["hives"]["count"], summary["hives"]["total"])

    def test_an_unreadable_timestamp_is_kept_rather_than_dropped(self):
        """An export is the complete record; a malformed date is a row to look at, not hide."""
        rows = [{"timestamp": "not a date"}]
        self.assertEqual(filter_rows(rows, "events", self.now - timedelta(days=1)), rows)


class ExportBundleTest(unittest.TestCase):
    """A CSV holds one table, so "everything in one file" can only be an archive."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "bundle.db")
        self.store.initialize()
        self.store.seed_sample_hives()
        self.store.add(HiveEventIn(hive_id="H3", timestamp=datetime.now(timezone.utc),
                                   status="ALARM", anomaly_fraction=0.9, consecutive_anomalies=6))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_every_chosen_dataset_becomes_a_file(self):
        content, media, filename = build_bundle(self.store, ["events", "hives"], "csv")
        self.assertEqual(media, "application/zip")
        self.assertTrue(filename.endswith(".zip"))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIn("waggle-events.csv", archive.namelist())
            self.assertIn("waggle-hives.csv", archive.namelist())

    def test_the_manifest_records_what_the_archive_answers(self):
        """Opened a year later, the archive has to say what was asked for and what it holds."""
        since = datetime.now(timezone.utc) - timedelta(days=7)
        content, _, _ = build_bundle(self.store, ["events", "guidance"], "json", since)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["format"], "json")
        self.assertEqual(manifest["period_start"], since.isoformat())
        listed = {item["dataset"]: item for item in manifest["datasets"]}
        self.assertTrue(listed["events"]["period_filtered"])
        self.assertFalse(listed["guidance"]["period_filtered"])
        self.assertEqual(listed["events"]["rows"], 1)

    def test_the_files_inside_are_readable_on_their_own(self):
        content, _, _ = build_bundle(self.store, ["events"], "json")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            rows = json.loads(archive.read("waggle-events.json"))
        self.assertEqual(rows[0]["hive_id"], "H3")


class EveryDatasetTest(unittest.TestCase):
    """Each dataset, on its own, in both formats, checked for what is actually inside it.

    The page now offers eight choices and a bundle of any combination of them. A suite that
    only exercised one dataset would let a broken one reach a beekeeper as an empty file
    with the right name on it.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.tempdir.name) / "all.db")
        self.store.initialize()
        self.store.seed_sample_hives()
        self.now = datetime.now(timezone.utc)
        event = self.store.add(HiveEventIn(
            hive_id="H3", timestamp=self.now, status="ALARM", anomaly_fraction=0.93,
            anomaly_severity=0.37, consecutive_anomalies=6, source_file="demo.wav",
            model="H3.onnx", temperature_c=17.4, humidity_percent=81, wind_kmh=34.0, weather_code=61))
        self.store.acknowledge(event.id, "issue_confirmed", "Kraliçe görülmedi", acknowledged_by="ilke")
        self.store.add_report(ReportIn(
            period_start=self.now - timedelta(days=7), period_end=self.now,
            summary="Çayır Kovanı için kalıcı akustik değişim ölçüldü ve kontrol isteniyor.",
            recommendations=["Kovanı fiziksel kontrol edin"], hive_ids=["H3"], language="tr",
            generator="agent-framework:foundry-local:phi", grounding_sources=["alarm-interpretation"]))
        self.store.add_health_confirmation("H3", HealthConfirmationIn(evidence="queen_seen", note="Kraliçe görüldü"),
                                           confirmed_by="ilke")
        self.store.add_device("H3", DeviceCreate(name="Saha telefonu", kind="phone"))

    def tearDown(self):
        self.tempdir.cleanup()

    # What every dataset must be able to say about itself: a column that identifies a row,
    # and a value that proves the row came from this store rather than from a stub.
    EXPECTATIONS = {
        "hives": ("hive_id", "H3"),
        "events": ("hive_id", "H3"),
        "alarms": ("status", "ALARM"),
        "reports": ("language", "tr"),
        "confirmations": ("evidence", "queen_seen"),
        "enrollment": (None, None),
        "devices": ("kind", "phone"),
        "guidance": ("id", "alarm-interpretation"),
    }

    def test_every_dataset_produces_a_csv_with_a_header(self):
        for dataset in CATALOGUE:
            with self.subTest(dataset=dataset):
                content, media, filename = build_export(self.store, dataset, "csv")
                self.assertEqual(media, "text/csv; charset=utf-8")
                self.assertTrue(filename.endswith(".csv"))
                text = content.decode("utf-8")
                # The byte-order mark is what makes a spreadsheet read Turkish correctly.
                self.assertTrue(text.startswith("﻿"))
                header = next(csv.reader(io.StringIO(text.lstrip("﻿"))))
                self.assertTrue(header, f"{dataset} exported no columns")
                self.assertEqual(len(header), len(set(header)), f"{dataset} repeats a column")

    def test_every_dataset_produces_json_that_parses(self):
        for dataset in CATALOGUE:
            with self.subTest(dataset=dataset):
                content, media, filename = build_export(self.store, dataset, "json")
                self.assertEqual(media, "application/json; charset=utf-8")
                self.assertTrue(filename.endswith(".json"))
                self.assertIsInstance(json.loads(content.decode("utf-8")), list)

    def test_each_dataset_carries_the_row_it_is_named_after(self):
        for dataset, (column, value) in self.EXPECTATIONS.items():
            if column is None:  # Enrollment needs an uploaded recording, which this store has none of.
                continue
            with self.subTest(dataset=dataset):
                rows = json.loads(build_export(self.store, dataset, "json")[0].decode("utf-8"))
                self.assertTrue(rows, f"{dataset} exported nothing")
                self.assertIn(value, [row.get(column) for row in rows])

    def test_csv_and_json_agree_on_the_rows_they_hold(self):
        """One format quietly dropping rows is the failure a single-format test misses."""
        for dataset in CATALOGUE:
            with self.subTest(dataset=dataset):
                rows = json.loads(build_export(self.store, dataset, "json")[0].decode("utf-8"))
                text = build_export(self.store, dataset, "csv")[0].decode("utf-8").lstrip("﻿")
                self.assertEqual(len(list(csv.DictReader(io.StringIO(text)))), len(rows))

    def test_an_empty_dataset_still_exports_its_columns(self):
        """A file with no header cannot be opened as a table, only guessed at."""
        text = build_export(self.store, "enrollment", "csv")[0].decode("utf-8").lstrip("﻿")
        self.assertIn("hive_id", next(csv.reader(io.StringIO(text))))

    def test_a_bundle_of_every_dataset_holds_a_file_for_each(self):
        names = list(CATALOGUE)
        content, _, _ = build_bundle(self.store, names, "csv")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(sorted(archive.namelist()),
                             sorted([f"waggle-{name}.csv" for name in names] + ["manifest.json"]))
            for name in names:
                header = archive.read(f"waggle-{name}.csv").decode("utf-8").lstrip("﻿").splitlines()[0]
                self.assertTrue(header, f"{name} is empty inside the archive")

    def test_the_conditions_a_measurement_was_taken_in_reach_the_export(self):
        """Weather is stamped on the event, so an export that omits it is not the record."""
        rows = json.loads(build_export(self.store, "events", "json")[0].decode("utf-8"))
        self.assertEqual(rows[0]["wind_kmh"], 34.0)
        self.assertEqual(rows[0]["weather_code"], 61)
