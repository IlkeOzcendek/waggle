import unittest
from datetime import datetime, timedelta, timezone

from panel.app.main import integration_freshness


class IntegrationFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

    def test_missing_integration_is_waiting(self):
        self.assertEqual(integration_freshness(None, 900, self.now), "waiting")

    def test_recent_integration_is_ok(self):
        last_seen = self.now - timedelta(minutes=14)
        self.assertEqual(integration_freshness(last_seen, 900, self.now), "ok")

    def test_stale_integration_is_warning(self):
        last_seen = self.now - timedelta(minutes=16)
        self.assertEqual(integration_freshness(last_seen, 900, self.now), "warning")

    def test_naive_database_timestamp_is_treated_as_utc(self):
        last_seen = (self.now - timedelta(minutes=5)).replace(tzinfo=None)
        self.assertEqual(integration_freshness(last_seen, 900, self.now), "ok")

    def test_invalid_threshold_is_rejected(self):
        with self.assertRaises(ValueError):
            integration_freshness(self.now, 0, self.now)


if __name__ == "__main__":
    unittest.main()
