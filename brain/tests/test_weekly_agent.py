import unittest

from datetime import datetime, timezone
from unittest.mock import Mock, patch

from brain.foundry_report import ReportDraft
from brain.weekly_agent import events_for_period, run_weekly_report

NOW = datetime(2026, 8, 29, 12, tzinfo = timezone.utc) # fixed date to get used in the test

class WeeklyAgentTest(unittest.TestCase):
    def test_period_filter_excludes_old_events(self): # This tests whether older events from the specified date range have been filtered out in short August 1st gets eliminated August 28th remains ultimately testing whether there will be only one event
        events = [
            {"timestamp": "2026-08-28T12:00:00+00:00"},
            {"timestamp": "2026-08-01T12:00:00+00:00"},
        ]

        self.assertEqual(len(events_for_period(events, NOW.replace(day = 22), NOW)), 1)

    @patch("brain.weekly_agent.generate_agent_report")
    @patch("brain.weekly_agent.requests.post")
    @patch("brain.weekly_agent.requests.get")
    def test_creates_bilingual_reports(self, get, post, generate): # A fake ALARM event is received, a Turkish report and an English report are generated and both are sent to the API with the correct device key --- The information source they used is also recorded and the results of the two reports returned from the API are verified
        get.return_value = Mock(
            json = lambda: [{"hive_id": "H3", "status": "ALARM", "timestamp": "2026-08-28T12:00:00+00:00"}],
            raise_for_status = lambda: None,
        )

        post.side_effect = [
            Mock(json = lambda: {"id": 1}, raise_for_status = lambda: None),
            Mock(json = lambda: {"id": 2}, raise_for_status = lambda: None),
        ]

        generate.side_effect = [
            ReportDraft("TR", ["Kontrol"], ["H3"], "tr", "foundry-local:test", {"knowledge_ids": ["alarm-inspection"]}),
            ReportDraft("EN", ["Inspect"], ["H3"], "en", "foundry-local:test", {"knowledge_ids": ["alarm-inspection"]}),
        ]

        result = run_weekly_report("http://panel", "key", "test", NOW)

        self.assertEqual(result, [{"id": 1}, {"id": 2}]) # check to if eq or not
        self.assertEqual([call.kwargs["json"]["language"] for call in post.call_args_list], ["tr", "en"]) # checks the post requests

        self.assertTrue(all(call.kwargs["headers"] == {"X-Device-Key": "key"} for call in post.call_args_list)) # right device key or not

        self.assertEqual(get.call_args.kwargs["headers"], {"X-Device-Key": "key"}) # checks the get requests that is right or not

        self.assertIn("/api/agent/events", get.call_args.args[0]) # is the get request is sent to the right API

        self.assertEqual(post.call_args_list[0].kwargs["json"]["grounding_sources"], ["alarm-inspection"]) # verification that the information source used in the payload of the initial report was sent correctly

class AssessmentPayloadTest(unittest.TestCase):
    """The decision the model reached has to survive the trip to the panel.

    The panel's model-decision box, the report PDF and the report export all read this one
    block. If the mapping in `weekly_agent` drifts, every one of them quietly shows a
    default instead — a report that says "routine" because a field was renamed looks
    exactly like a report that is genuinely routine.
    """

    ASSESSMENT = {
        "priority": "immediate",
        "pattern": "persistent_acoustic_change",
        "queen_loss_compatible": True,
        "inspection_required": True,
        "action_codes": ["inspect_hive", "check_queen"],
        "knowledge_ids": ["alarm-interpretation", "season-spring-swarm"],
        "cross_check": {"model": "qwen2.5-1.5b", "agreed": False, "resolved_to": "immediate"},
    }

    def _post_payload(self, assessment):
        with patch("brain.weekly_agent.generate_agent_report") as generate, \
             patch("brain.weekly_agent.requests.post") as post, \
             patch("brain.weekly_agent.requests.get") as get:
            get.return_value = Mock(
                json=lambda: [{"hive_id": "H3", "status": "ALARM",
                               "timestamp": "2026-08-28T12:00:00+00:00"}],
                raise_for_status=lambda: None,
            )
            post.side_effect = [
                Mock(json=lambda: {"id": 1}, raise_for_status=lambda: None),
                Mock(json=lambda: {"id": 2}, raise_for_status=lambda: None),
            ]
            generate.side_effect = [
                ReportDraft("TR", ["Kontrol"], ["H3"], "tr", "agent:test", dict(assessment)),
                ReportDraft("EN", ["Inspect"], ["H3"], "en", "agent:test", dict(assessment)),
            ]
            run_weekly_report("http://panel", "key", "test", NOW)
            return post.call_args_list[0].kwargs["json"]

    def test_the_decision_reaches_the_panel_intact(self):
        assessment = self._post_payload(self.ASSESSMENT)["assessment"]
        self.assertEqual(assessment["priority"], "immediate")
        self.assertEqual(assessment["pattern"], "persistent_acoustic_change")
        self.assertTrue(assessment["queen_loss_compatible"])
        self.assertTrue(assessment["inspection_required"])
        self.assertEqual(assessment["action_codes"], ["inspect_hive", "check_queen"])

    def test_a_disagreeing_cross_check_is_reported_as_a_disagreement(self):
        """Amber on the panel and 'the cautious reading was kept' in the PDF depend on this."""
        assessment = self._post_payload(self.ASSESSMENT)["assessment"]
        self.assertEqual(assessment["cross_check_model"], "qwen2.5-1.5b")
        self.assertIs(assessment["cross_check_agreed"], False)

    def test_without_a_second_model_the_cross_check_fields_stay_empty(self):
        """An empty field must not be mistaken for two models that agreed."""
        single = {key: value for key, value in self.ASSESSMENT.items() if key != "cross_check"}
        assessment = self._post_payload(single)["assessment"]
        self.assertIsNone(assessment["cross_check_model"])
        self.assertIsNone(assessment["cross_check_agreed"])

    def test_the_grounding_sources_travel_beside_the_decision(self):
        payload = self._post_payload(self.ASSESSMENT)
        self.assertEqual(payload["grounding_sources"],
                         ["alarm-interpretation", "season-spring-swarm"])

    def test_a_model_that_returned_nothing_usable_defaults_to_the_calm_reading(self):
        """The deterministic fallback must not invent an alarm out of a missing field."""
        assessment = self._post_payload({"knowledge_ids": []})["assessment"]
        self.assertEqual(assessment["priority"], "routine")
        self.assertEqual(assessment["pattern"], "within_baseline")
        self.assertFalse(assessment["inspection_required"])


if __name__ == "__main__":
    unittest.main()
