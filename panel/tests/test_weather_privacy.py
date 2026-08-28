import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from panel.app import main


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


if __name__ == "__main__":
    unittest.main()
