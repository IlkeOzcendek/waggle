import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

from panel.app import main
from panel.app.database import EventStore
from panel.app.models import HiveEventIn, WeatherState


class WeatherPrivacyTest(unittest.TestCase):
    @patch("panel.app.main.requests.get")
    def test_disabled_weather_never_calls_external_service(self, get):
        fake_store = Mock()
        fake_store.settings.return_value = {
            "panel_name": "Waggle",
            "location_name": "Demo Kovanları",
            "alarm_threshold": .85,
            "sound_enabled": True,
            "refresh_seconds": 5,
            "onboarding_completed": False,
            "weather_enabled": False,
        }
        with patch.object(main, "store", fake_store):
            with self.assertRaises(HTTPException) as raised:
                main.weather()
        self.assertEqual(raised.exception.status_code, 503)
        get.assert_not_called()


class WeatherStampTest(unittest.TestCase):
    """Conditions travel with the recording, or they do not travel at all.

    A recording is read for the colony's sound, and wind and rain put their own sound on
    the microphone. Without the weather of the moment stored beside the measurement, the
    knowledge base's own rule about wind and rain can never fire, and a report cannot say
    whether an alarm was measured in conditions worth trusting.
    """

    def _event(self, **overrides):
        fields = dict(hive_id="H3", timestamp=datetime.now(timezone.utc), status="ALARM",
                      anomaly_fraction=0.93, consecutive_anomalies=6)
        fields.update(overrides)
        return HiveEventIn(**fields)

    def _observed(self):
        return WeatherState(location="Demo", temperature_c=17.4, humidity_percent=81,
                            wind_kmh=34.0, weather_code=61,
                            observed_at=datetime.now(timezone.utc))

    def test_a_fresh_recording_carries_the_conditions_it_was_taken_in(self):
        with patch.object(main, "weather", return_value=self._observed()):
            stamped = main.with_conditions(self._event())
        self.assertEqual(stamped.wind_kmh, 34.0)
        self.assertEqual(stamped.weather_code, 61)
        self.assertEqual(stamped.humidity_percent, 81)

    def test_weather_turned_off_leaves_the_event_unstamped(self):
        """The privacy switch is the one thing stamping may never route around."""
        def refuse():
            raise HTTPException(status_code=503, detail="disabled")

        with patch.object(main, "weather", side_effect=refuse):
            stamped = main.with_conditions(self._event())
        self.assertIsNone(stamped.wind_kmh)
        self.assertIsNone(stamped.weather_code)

    def test_an_unreachable_service_never_costs_the_event(self):
        def fail():
            raise HTTPException(status_code=503, detail="unreachable")

        with patch.object(main, "weather", side_effect=fail):
            stamped = main.with_conditions(self._event())
        self.assertEqual(stamped.hive_id, "H3")
        self.assertIsNone(stamped.temperature_c)

    def test_a_recording_from_hours_ago_is_not_given_this_hour_s_weather(self):
        """Current conditions are not the conditions a past recording was taken in."""
        old = self._event(timestamp=datetime.now(timezone.utc) - timedelta(hours=6))
        with patch.object(main, "weather", return_value=self._observed()):
            stamped = main.with_conditions(old)
        self.assertIsNone(stamped.wind_kmh)

    def test_conditions_the_device_measured_itself_are_not_overwritten(self):
        """An edge device at the hive knows its own air better than one panel coordinate."""
        own = self._event(wind_kmh=3.0, weather_code=0)
        with patch.object(main, "weather", return_value=self._observed()):
            stamped = main.with_conditions(own)
        self.assertEqual(stamped.wind_kmh, 3.0)
        self.assertEqual(stamped.weather_code, 0)


class WeatherStorageTest(unittest.TestCase):
    """Stamped conditions have to survive the round trip, or the report never sees them."""

    def test_conditions_survive_a_write_and_a_read(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "weather.db")
            store.initialize()
            store.seed_sample_hives()
            store.add(HiveEventIn(hive_id="H3", timestamp=datetime.now(timezone.utc), status="ALARM",
                                  anomaly_fraction=0.93, consecutive_anomalies=6,
                                  temperature_c=17.4, humidity_percent=81, wind_kmh=34.0, weather_code=61))
            stored = store.recent()[0]
        self.assertEqual(stored.wind_kmh, 34.0)
        self.assertEqual(stored.weather_code, 61)
        self.assertEqual(stored.temperature_c, 17.4)

    def test_an_event_written_without_weather_reads_back_as_unknown_not_as_calm(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "weather.db")
            store.initialize()
            store.seed_sample_hives()
            store.add(HiveEventIn(hive_id="H3", timestamp=datetime.now(timezone.utc), status="ALARM",
                                  anomaly_fraction=0.93, consecutive_anomalies=6))
            stored = store.recent()[0]
        self.assertIsNone(stored.wind_kmh)
        self.assertIsNone(stored.weather_code)


if __name__ == "__main__":
    unittest.main()
