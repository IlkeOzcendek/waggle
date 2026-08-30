import unittest

from brain.local_rag import load_knowledge, retrieve_guidance

class LocalRagTest(unittest.TestCase): # Local RAG tests that ALARM uses the same resources correctly and in two languages that it highlights the correct recommendation in WATCH and that its knowledge base is not empty/insufficient
    def test_alarm_retrieval_is_grounded_and_bilingual(self):
        events = [{"hive_id": "H3", "status": "ALARM"}]

        turkish = retrieve_guidance(events, "tr")

        english = retrieve_guidance(events, "en")

        self.assertEqual([item["id"] for item in turkish], [item["id"] for item in english])

        self.assertIn("alarm-interpretation", [item["id"] for item in turkish])

        self.assertTrue(any("kesin tanı değildir" in item["text"] for item in turkish))

    def test_watch_prefers_follow_up_guidance(self):
        result = retrieve_guidance([{"hive_id": "H2", "status": "WATCH"}], "en")

        self.assertEqual(result[0]["id"], "watch-follow-up")

    def test_knowledge_entries_are_complete(self):
        self.assertGreaterEqual(len(load_knowledge()), 5)

if __name__ == "__main__":
    unittest.main()