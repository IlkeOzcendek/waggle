import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests

from brain.foundry_report import _foundry_connection, generate_agent_report, generate_report, render_report

EVENTS = [ # A list in order to use in tests
    {"hive_id": "H1", "status": "NORMAL", "anomaly_fraction": .08, "consecutive_anomalies": 0},
    {"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 1.0, "consecutive_anomalies": 30},
]

class FoundryReportTest(unittest.TestCase):
    def test_safe_bilingual_rendering(self): # It generates TR and EN reports from the same alarm situation and checks that both reports use safe language such as this could be a sign not a definitive diagnosis instead of saying the queen is definitely missing
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

    @patch("brain.foundry_report.assess_with_foundry", side_effect = ValueError("bad output"))
    def test_invalid_model_output_uses_safe_fallback(self, _): # The system is testing whether if the AI or the model gives a nonsensical or invalid answer instead of crashing it will move on to a secure report based on the local knowledge base and suggest a physical hive check
        report = generate_report(EVENTS, "tr")

        self.assertEqual(report.generator, "safe-fallback")

        self.assertIn("alarm-interpretation", report.assessment["knowledge_ids"])

        self.assertTrue(
            any("fiziksel olarak kontrol" in item for item in report.recommendations)
        )

    # Without this the narrative step would reach the real Foundry CLI and network.
    @patch("brain.foundry_report._with_model_narrative", side_effect=lambda draft, *args, **kwargs: draft)
    @patch("brain.foundry_report.assess_with_agent_framework", new_callable=AsyncMock)
    def test_weekly_report_records_agent_framework_provenance(self, assess, _narrative):
        assess.return_value = {
            "priority": "immediate",
            "pattern": "persistent_acoustic_change",
            "queen_loss_compatible": True,
            "inspection_required": True,
            "action_codes": ["inspect_hive", "check_queen"],
        }

        report = generate_agent_report(EVENTS, "en", "test-model")

        self.assertEqual(report.generator, "agent-framework:foundry-local:test-model")
        self.assertIn("alarm-interpretation", report.assessment["knowledge_ids"])

    @patch("brain.foundry_report.assess_with_agent_framework", new_callable=AsyncMock)
    def test_weekly_agent_failure_uses_safe_fallback(self, assess):
        assess.side_effect = RuntimeError("framework unavailable")

        report = generate_agent_report(EVENTS, "tr")

        self.assertEqual(report.generator, "safe-fallback")
        self.assertTrue(report.assessment["inspection_required"])

    # An exported endpoint override would short-circuit CLI discovery and fail this test.
    @patch.dict(os.environ, {"WAGGLE_FOUNDRY_BASE_URL": ""}, clear=False)
    @patch("brain.foundry_report.subprocess.run")
    @patch("brain.foundry_report._run_foundry")
    @patch("brain.foundry_report.requests.get")
    def test_stale_foundry_daemon_is_restarted_once(self, get, run_foundry, run): # If the initial Foundry connection is broken the system detects this and restarts the Foundry server, reconnecting via a new port as 5001
        get.side_effect = [requests.ConnectionError("stale port"), Mock()]

        run_foundry.side_effect = [
            '{"webUrls":["http://127.0.0.1:5000"]}',
            '{"model":{"id":"phi-id"}}',
            '{"webUrls":["http://127.0.0.1:5001"]}',
            '{"model":{"id":"phi-id"}}',
        ]

        self.assertEqual(
            _foundry_connection("phi-3.5-mini"),
            ("http://127.0.0.1:5001/v1", "phi-id"),
        )

        self.assertTrue(
            any(call.args[0][:3] == ["foundry", "server", "restart"] for call in run.call_args_list)
        )

if __name__ == "__main__":
    unittest.main()
