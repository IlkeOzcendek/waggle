import unittest
from unittest.mock import patch

from tools.run_demo import seed_demo


class DemoToolsTest(unittest.TestCase):
    @patch("tools.run_demo.requests.post")
    def test_seed_demo_sends_three_events_and_report_with_device_key(self, post):
        post.return_value.raise_for_status.return_value = None
        seed_demo("http://example.test", "secret-key")
        self.assertEqual(post.call_count, 4)
        event_calls = post.call_args_list[:3]
        self.assertEqual(
            [call.kwargs["json"]["event"] for call in event_calls],
            ["healthy", "uncertain", "queenless_suspected"],
        )
        self.assertTrue(
            all(call.kwargs["headers"] == {"X-Device-Key": "secret-key"} for call in post.call_args_list)
        )
        self.assertTrue(post.call_args.args[0].endswith("/api/reports"))


if __name__ == "__main__":
    unittest.main()
