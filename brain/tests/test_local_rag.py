import unittest

from brain.local_rag import load_knowledge, retrieve_guidance, search_guidance

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

class FactDrivenRetrievalTest(unittest.TestCase):
    """Selection keys on the facts of the period, not on the status label alone."""

    @staticmethod
    def _event(status="ALARM", anomaly=0.9, run=25, month=5, hive="H3"):
        return {
            "hive_id": hive,
            "status": status,
            "anomaly_fraction": anomaly,
            "consecutive_anomalies": run,
            "timestamp": f"2026-{month:02d}-15T09:00:00+00:00",
        }

    def _ids(self, events, limit=4):
        return [item["id"] for item in retrieve_guidance(events, "tr", limit=limit)]

    def test_the_same_status_yields_different_guidance_in_different_months(self):
        may = self._ids([self._event(month=5)])
        december = self._ids([self._event(month=12)])
        self.assertIn("season-spring-swarm", may)
        self.assertIn("season-winter-cluster", december)
        self.assertNotEqual(may, december)

    def test_a_sustained_high_alarm_pulls_in_the_sustained_guidance(self):
        heavy = self._ids([self._event(anomaly=0.95, run=30)])
        light = self._ids([self._event(anomaly=0.35, run=3)])
        self.assertIn("alarm-sustained-run", heavy)
        self.assertIn("alarm-very-high-fraction", heavy)
        self.assertNotIn("alarm-sustained-run", light)

    def test_several_hives_changing_at_once_is_treated_as_environmental(self):
        many = self._ids([
            self._event(status="WATCH", hive="H1", anomaly=0.5, run=5),
            self._event(status="WATCH", hive="H2", anomaly=0.5, run=5),
        ])
        self.assertIn("limits-multiple-hives", many)
        one = self._ids([self._event(status="WATCH", hive="H1", anomaly=0.5, run=5)])
        self.assertNotIn("limits-multiple-hives", one)

    def test_a_missing_measurement_is_not_read_as_zero(self):
        """An event with no run length must not match "short anomalous run" guidance."""
        without = retrieve_guidance([{"hive_id": "H2", "status": "WATCH"}], "en")
        self.assertEqual(without[0]["id"], "watch-follow-up")
        self.assertNotIn("watch-short-run", [item["id"] for item in without])

    def test_the_seasonal_note_is_always_given_a_place(self):
        ids = self._ids([self._event(anomaly=0.99, run=40, month=10)])
        self.assertIn("season-autumn-varroa", ids)

    def test_free_text_search_finds_a_topic_the_period_did_not_raise(self):
        found = [item["id"] for item in search_guidance("varroa mite treatment", "en")]
        self.assertIn("season-autumn-varroa", found)
