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

if __name__ == "__main__":
    unittest.main()
