import unittest
from unittest.mock import patch

from brain.foundry_report import generate_report, render_report


EVENTS = [
    {"hive_id": "H1", "status": "NORMAL", "anomaly_fraction": .08, "consecutive_anomalies": 0},
    {"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 1.0, "consecutive_anomalies": 30},
]


class FoundryReportTest(unittest.TestCase):
    def test_safe_bilingual_rendering(self):
        assessment = {
            "priority": "immediate",
            "pattern": "persistent_acoustic_change",
            "queen_loss_compatible": True,
            "inspection_required": True,
            "action_codes": ["inspect_hive", "check_queen"],
        }
        turkish = render_report(EVENTS, assessment, "tr", "test")
        english = render_report(EVENTS, assessment, "en", "test")
        self.assertIn("kalıcı akustik değişim", turkish.summary)
        self.assertIn("kesin tanı değildir", turkish.summary)
        self.assertIn("Persistent acoustic change", english.summary)
        self.assertIn("not a definitive diagnosis", english.summary)

    @patch("brain.foundry_report.assess_with_foundry", side_effect=ValueError("bad output"))
    def test_invalid_model_output_uses_safe_fallback(self, _):
        report = generate_report(EVENTS, "tr")
        self.assertEqual(report.generator, "safe-fallback")
        self.assertTrue(
            any("fiziksel olarak kontrol" in item for item in report.recommendations)
        )


if __name__ == "__main__":
    unittest.main()
