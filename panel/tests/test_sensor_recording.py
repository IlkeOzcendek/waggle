import asyncio # for async codes
import json 
import tempfile
import unittest # writing running and automatic tests

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace # easily reaching the objects
from unittest.mock import patch # replacing function or obj with a fake one

from fastapi import HTTPException , Request

from panel.app import main

from panel.app.database import EventStore # To managing the events of data
from panel.app.models import DeviceCreate, HealthConfirmationIn, HiveCreate


def signed_in_request(username: str) -> Request:
    """A Request carrying only what the endpoint reads: the signed-in username."""
    request = Request({"type": "http", "headers": [], "method": "POST", "path": "/"})
    request.state.username = username
    return request


class SensorRecordingTest(unittest.TestCase):
    def setUp(self): # runs before each test to prepare, temp database and fake ONNX model folder
        self.tempdir = tempfile.TemporaryDirectory()

        self.store = EventStore(Path(self.tempdir.name) / "sensor.db")

        self.store.initialize()
        # The sample hives are no longer created for every database, so a test that
        # relies on them asks for them: the dependency is stated rather than inherited.
        self.store.seed_sample_hives()

        self.model = Path(self.tempdir.name) / "monitor.onnx"

        self.model.write_bytes(b"test-model")

    def tearDown(self): # runs after each test to clean it up first "seUp" and at the end this
        self.tempdir.cleanup()

    @patch("ear.wav_isolation_monitor.analyze_wav")
    def test_phone_wav_is_analyzed_and_stored(self, analyze): # A fake phone sends a WAV file and the system analyzes it and tests whether if it is saved to the correct hive using the WATCH result
        analyze.return_value = {
            "status": "WATCH",
            "windows": 12,
            "anomaly_fraction": .75,
            # How far the deviating windows fell outside the profile, read off the ONNX
            # graph's second output beside the decision itself.
            "anomaly_severity": .41,
            "peak_severity": .58,
            "consecutive_anomalies": 5,
            "maximum_consecutive_anomalies": 5,
        }
        
        wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40

        request = SimpleNamespace(headers = {"content-length": str(len(wav))}, body = lambda: _async_value(wav))

        device = self.store.add_device("H2", DeviceCreate(name = "Test telefonu", kind = "phone"))

        with patch.object(main, "store", self.store), patch.object(main, "SENSOR_MODEL_PATH", self.model):
            response = asyncio.run(main.analyze_sensor_recording(request, "H2", device.device_id, "phone.wav"))

        self.assertEqual(response.mode, "monitoring")
        self.assertEqual(response.event.status, "WATCH")
        self.assertEqual(response.event.source_file, "phone:phone.wav")
        self.assertEqual(self.store.recent()[0].hive_id, "H2")
        # The ONNX profile that decided this travels with the event, so a report reading
        # these rows can name the model that measured them and not only the one that wrote
        # about them.
        self.assertTrue(response.event.model.endswith(".onnx"))
        # Depth is stored beside the ratio: two events at 75% are not the same measurement
        # and the panel used to record them as if they were.
        self.assertEqual(response.event.anomaly_severity, .41)
        self.assertEqual(self.store.recent()[0].anomaly_severity, .41)
        self.assertEqual(self.store.recent()[0].model, response.model)

    def test_non_wav_upload_is_rejected(self): # It tests whether if a non WAV .m4a file is not accepted when sent to the system
        request = SimpleNamespace(headers = {}, body = lambda: _async_value(b"not audio"))

        with patch.object(main, "store", self.store), patch.object(main, "SENSOR_MODEL_PATH", self.model):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(main.analyze_sensor_recording(request, "H2", "H2-D1", "phone.m4a"))

        self.assertEqual(caught.exception.status_code, 415)

    @patch("ear.wav_isolation_monitor.wav_features")
    def test_new_hive_recording_is_enrollment_not_alarm(self, features): # Instead of immediately sounding an anomaly alarm when the new hive's sound is detected the system is testing whether it first stores this recording as enrollment data to learn the hive's normal sound 
        features.return_value = ([[0.0] * 21] * 12, [f"f{i}" for i in range(21)])

        hive = self.store.add_hive(HiveCreate(name="Yeni Kovan"))

        device = self.store.add_device(hive.hive_id, DeviceCreate(name = "Kovan telefonu"))

        self.store.add_health_confirmation(hive.hive_id, HealthConfirmationIn(evidence="queen_seen"))

        wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40

        request = SimpleNamespace(headers = {}, body = lambda: _async_value(wav))

        with patch.object(main, "store", self.store), patch.object(main, "SENSOR_MODEL_PATH", self.model):
            response = asyncio.run(main.analyze_sensor_recording(request, hive.hive_id, device.device_id, "healthy.wav"))

        self.assertEqual(response.mode, "enrollment")
        self.assertIsNone(response.event)
        self.assertEqual(self.store.recent(), [])

        values, names = self.store.enrollment_features(hive.hive_id)

        self.assertEqual(values.shape, (12, 21))
        self.assertEqual(len(names), 21)

    def test_enrollment_requires_health_confirmation(self): # It tests whether enrollment cannot be started without a health verification such as queen_seen for the new hive
        hive = self.store.add_hive(HiveCreate(name = "Yeni Kovan"))

        device = self.store.add_device(hive.hive_id, DeviceCreate(name = "Kovan telefonu"))

        wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40

        request = SimpleNamespace(headers = {}, body = lambda: _async_value(wav))

        with patch.object(main, "store", self.store), patch.object(main, "SENSOR_MODEL_PATH", self.model):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(main.analyze_sensor_recording(request, hive.hive_id, device.device_id, "unknown.wav"))

        self.assertEqual(caught.exception.status_code, 422)

    def test_enrollment_rejects_a_second_microphone(self): # To ensure enrollment data always comes from the same microphone/device they are testing that a second microphone cannot be added to the hive
        hive = self.store.add_hive(HiveCreate(name = "Yeni Kovan"))

        self.store.add_device(hive.hive_id, DeviceCreate(name = "Birinci telefon"))

        with self.assertRaises(ValueError):
            self.store.add_device(hive.hive_id, DeviceCreate(name = "İkinci telefon"))

    def test_uncertain_field_check_does_not_unlock_enrollment(self): # "We cannot say the hive is healthy" Therefore enrollment is not being opened and the system continues to await a definitive field/health verification
        hive = self.store.add_hive(HiveCreate(name = "Yeni Kovan"))

        self.store.add_device(hive.hive_id, DeviceCreate(name = "Kovan telefonu")) 

        confirmation = self.store.add_health_confirmation(
            hive.hive_id, HealthConfirmationIn(evidence = "uncertain")
        )

        status = self.store.enrollment_status(hive.hive_id)

        self.assertFalse(confirmation.accepted_for_enrollment)
        self.assertEqual(status.confirmation_count, 0)
        self.assertTrue(status.confirmation_due)

    def test_accepted_field_checks_cannot_be_repeated_immediately(self): # A second verification is performed immediately after the first valid field check to prevent the system from being fooled new verification is not accepted before the specified time has passed
        hive = self.store.add_hive(HiveCreate(name = "Yeni Kovan"))

        self.store.add_device(hive.hive_id, DeviceCreate(name="Kovan telefonu"))
        
        with patch.object(main, "store", self.store):
            first = main.create_health_confirmation(
                hive.hive_id, HealthConfirmationIn(evidence="queen_seen"), signed_in_request("ilke")
            )

            self.assertTrue(first.accepted_for_enrollment)
            # The field check is what unlocks more training data, so the panel records
            # which account vouched for it.
            self.assertEqual(first.confirmed_by, "ilke")
            with self.assertRaises(HTTPException) as caught:
                main.create_health_confirmation(
                    hive.hive_id,
                    HealthConfirmationIn(evidence="brood_healthy"),
                    signed_in_request("ilke"),
                )

        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.store.enrollment_status(hive.hive_id).confirmation_count, 1)

    @patch("ear.profile_training.train_verified_profile")
    @patch("ear.wav_isolation_monitor.wav_features")
    def test_final_enrollment_recording_activates_verified_profile(self, features, train): # The test prepares the database as if it already has 41 valid voice recordings  and 4 valid field checks to bring the system to the final stage; thus, the next recording can be the final enrollment recording
        features.return_value = ([[0.0] * 21] * 12, [f"f{i}" for i in range(21)])

        hive = self.store.add_hive(HiveCreate(name = "Hazırlanan Kovan"))
        device = self.store.add_device(hive.hive_id, DeviceCreate(name = "Kovan telefonu"))

        now = datetime.now(timezone.utc)

        names = json.dumps([f"f{i}" for i in range(21)])
        
        matrix = json.dumps([[0.0] * 21])

        with self.store.connect() as connection:
            for index in range(41):
                recorded_at = now - timedelta(days=index % 14)

                connection.execute(
                    "INSERT INTO enrollment_recordings (hive_id, device_id, recorded_at, filename, window_count, healthy_confirmed, feature_names, features) VALUES (?, ?, ?, ?, 1, 1, ?, ?)",
                    (hive.hive_id, device.device_id, recorded_at.isoformat(), f"seed-{index}.wav", names, matrix),
                )

            for index in range(4):
                confirmed_at = now - timedelta(days = index * 4)

                connection.execute(
                    "INSERT INTO health_confirmations (hive_id, confirmed_at, evidence, accepted_for_enrollment) VALUES (?, ?, 'brood_healthy', 1)",
                    (hive.hive_id, confirmed_at.isoformat()),
                )

        def create_models(_values, _names, _hive_id, joblib_path, onnx_path): # When the last enrollment record arrives the system tests that it has trained and created a hive specific model once and moved the hive to the monitoring phase
            joblib_path.parent.mkdir(parents = True, exist_ok = True)
            joblib_path.write_bytes(b"joblib")

            onnx_path.write_bytes(b"onnx")
            # Training compares the ONNX decisions with the joblib ones it converted and
            # hands the comparison back; the panel used to drop it on the floor.
            return {"hive_id": _hive_id, "windows": 96, "features": 21, "different_decisions": 0}

        train.side_effect = create_models

        wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40

        request = SimpleNamespace(headers = {}, body = lambda: _async_value(wav))

        profile_dir = Path(self.tempdir.name) / "profiles"

        with patch.object(main, "store", self.store), patch.object(main, "HIVE_PROFILE_DIR", profile_dir):
            response = asyncio.run(main.analyze_sensor_recording(request, hive.hive_id, device.device_id, "final.wav"))

        self.assertTrue(self.store.enrollment_status(hive.hive_id).can_monitor)

        self.assertEqual(response.model, f"{hive.hive_id}.onnx")

        train.assert_called_once()

        profile = next(item for item in self.store.monitoring_profiles() if item["hive_id"] == hive.hive_id)
        self.assertEqual(profile["verification"]["different_decisions"], 0)
        self.assertEqual(profile["verification"]["windows"], 96)

async def _async_value(value):
    return value

if __name__ == "__main__":
    unittest.main()