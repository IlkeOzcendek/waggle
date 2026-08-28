import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.send_event import flush_queue, queue_event, read_queue


class DeviceClientTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.queue = Path(self.tempdir.name) / "pending.jsonl"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_queue_round_trip(self):
        event = {"hive_id": "H4", "event": "healthy", "confidence": .92}
        queue_event(self.queue, event)
        self.assertEqual(read_queue(self.queue), [event])

    @patch("tools.send_event.post_event", return_value=True)
    def test_flush_removes_sent_events(self, post_event):
        queue_event(self.queue, {"hive_id": "H4", "event": "healthy", "confidence": .92})
        self.assertEqual(flush_queue("http://example.test", "key", self.queue), 1)
        self.assertFalse(self.queue.exists())
        post_event.assert_called_once()

    @patch("tools.send_event.post_event", return_value=False)
    def test_flush_keeps_unsent_events(self, _):
        event = {"hive_id": "H4", "event": "uncertain", "confidence": .55}
        queue_event(self.queue, event)
        self.assertEqual(flush_queue("http://example.test", "key", self.queue), 0)
        self.assertEqual(read_queue(self.queue), [event])


if __name__ == "__main__":
    unittest.main()
