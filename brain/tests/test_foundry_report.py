import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests

from brain import foundry_report
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

    # Without these the narrative step and the cross-check would reach a real local model.
    @patch("brain.foundry_report._cross_check_model", return_value="")
    @patch("brain.foundry_report._with_model_narrative", side_effect=lambda draft, *args, **kwargs: draft)
    @patch("brain.foundry_report.assess_with_agent_framework", new_callable=AsyncMock)
    def test_weekly_report_records_agent_framework_provenance(self, assess, _narrative, _cross):
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

    @patch("brain.foundry_report._cross_check_model", return_value="")
    @patch("brain.foundry_report.assess_with_agent_framework", new_callable=AsyncMock)
    def test_agent_failure_falls_back_to_the_direct_model_call(self, assess, _cross):
        """Losing the framework must not cost the model's judgement too."""
        assess.side_effect = RuntimeError("framework unavailable")

        with patch("brain.foundry_report.assess_with_foundry") as direct:
            direct.return_value = {
                "priority": "immediate",
                "pattern": "persistent_acoustic_change",
                "queen_loss_compatible": True,
                "inspection_required": True,
                "action_codes": ["inspect_hive", "check_queen"],
            }
            report = generate_agent_report(EVENTS, "tr")

        self.assertEqual(report.generator, "foundry-local:phi-3.5-mini")
        direct.assert_called_once()

    @patch("brain.foundry_report.assess_with_agent_framework", new_callable=AsyncMock)
    def test_weekly_agent_failure_uses_safe_fallback(self, assess):
        """Only when the model itself is unreachable does the deterministic engine run."""
        assess.side_effect = RuntimeError("framework unavailable")

        with patch("brain.foundry_report.assess_with_foundry", side_effect=RuntimeError("model down")):
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


class CrossCheckTest(unittest.TestCase):
    """A second local model covers the first one's slips, and can never break the report."""

    EVENTS = [{"hive_id": "H3", "timestamp": "2026-05-15T09:00:00+00:00",
               "status": "ALARM", "anomaly_fraction": 0.93, "consecutive_anomalies": 30}]

    @staticmethod
    def _assessment(priority):
        shapes = {
            "routine": ("within_baseline", False, False, ["continue_monitoring"]),
            "watch": ("developing_acoustic_change", False, False, ["record_again"]),
            "immediate": ("persistent_acoustic_change", True, True, ["inspect_hive", "check_queen"]),
        }
        pattern, queen, inspect, actions = shapes[priority]
        return {"priority": priority, "pattern": pattern, "queen_loss_compatible": queen,
                "inspection_required": inspect, "action_codes": actions}

    def _run(self, primary, second=None, error=None, model="qwen2.5-1.5b"):
        with patch.object(foundry_report, "_cross_check_model", return_value=model), \
             patch.object(foundry_report, "assess_with_agent_framework", new_callable=AsyncMock) as agent:
            agent.side_effect = error or (lambda *a, **k: second)
            return foundry_report._cross_check(self.EVENTS, [], dict(primary), "phi-3.5-mini")

    def test_agreement_is_recorded(self):
        result = self._run(self._assessment("immediate"), self._assessment("immediate"))
        self.assertEqual(result["priority"], "immediate")
        self.assertTrue(result["cross_check"]["agreed"])

    def test_disagreement_keeps_the_more_cautious_priority(self):
        """Under-calling an alarm costs a colony; over-calling one costs an inspection."""
        result = self._run(self._assessment("watch"), self._assessment("immediate"))
        self.assertEqual(result["priority"], "immediate")
        self.assertFalse(result["cross_check"]["agreed"])
        self.assertEqual(result["cross_check"]["resolved_to"], "immediate")

    def test_a_calmer_second_opinion_does_not_lower_the_priority(self):
        result = self._run(self._assessment("immediate"), self._assessment("routine"))
        self.assertEqual(result["priority"], "immediate")

    def test_a_failing_second_model_leaves_the_assessment_untouched(self):
        primary = self._assessment("watch")
        with patch.object(foundry_report, "assess_with_foundry", side_effect=RuntimeError("down")):
            result = self._run(primary, error=RuntimeError("model down"))
        self.assertEqual(result["priority"], "watch")
        self.assertNotIn("cross_check", result)

    def test_no_second_model_configured_is_a_no_op(self):
        result = self._run(self._assessment("watch"), model="")
        self.assertNotIn("cross_check", result)
