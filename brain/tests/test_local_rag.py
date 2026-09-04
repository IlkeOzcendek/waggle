import unittest

from brain.local_rag import (event_profile, guidance_category, guidance_title, load_knowledge,
                             retrieve_guidance, search_guidance)

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

    def test_non_finite_and_out_of_range_measurements_are_rejected(self):
        for field, value in (
            ("anomaly_fraction", float("nan")),
            ("anomaly_fraction", float("inf")),
            ("anomaly_fraction", 1.01),
            ("anomaly_severity", -0.01),
        ):
            with self.subTest(field=field, value=value):
                event = self._event()
                event[field] = value
                with self.assertRaises(ValueError):
                    retrieve_guidance([event], "tr")

    def test_run_length_must_be_a_non_negative_integer(self):
        for value in (-1, 1.5, True, "3"):
            with self.subTest(value=value):
                event = self._event(run=value)
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    retrieve_guidance([event], "tr")

    def test_the_seasonal_note_is_always_given_a_place(self):
        ids = self._ids([self._event(anomaly=0.99, run=40, month=10)])
        self.assertIn("season-autumn-varroa", ids)

    def test_free_text_search_finds_a_topic_the_period_did_not_raise(self):
        found = [item["id"] for item in search_guidance("varroa mite treatment", "en")]
        self.assertIn("season-autumn-varroa", found)


class TurkishMorphologyTest(unittest.TestCase):
    """Turkish attaches its suffixes to the stem, so the searched word is rarely the
    written one. Matching whole tokens meant a reader had to guess the exact form a
    passage happened to use, and every query below returned nothing at all."""

    def _ids(self, query):
        return [item["id"] for item in search_guidance(query, "tr", limit=3)]

    def test_an_inflected_query_finds_the_note_its_stem_belongs_to(self):
        for query, expected in (
            ("kraliçesiz", "queen-replacement"),
            ("oğullar", "season-spring-swarm"),
            ("kovanları", "alarm-inspection"),
        ):
            with self.subTest(query=query):
                self.assertEqual(self._ids(query)[0], expected)

    def test_a_stem_finds_the_note_that_only_uses_an_inflected_form(self):
        """The other direction: "kış" is written nowhere, "kışlatma" and "kış kümesi" are."""
        self.assertEqual(self._ids("kış")[0], "season-winter-cluster")

    def test_a_word_the_base_does_not_contain_still_returns_nothing(self):
        """A guess about morphology must not become a guess about relevance: a query with
        no stem in common with the base has to keep returning an empty answer, so the
        panel can say "no note covers this" instead of offering three unrelated ones."""
        self.assertEqual(self._ids("kuantum bilgisayar"), [])
        self.assertEqual(self._ids("zzzqqq"), [])

    def test_one_searched_word_scores_once_however_many_forms_a_note_uses(self):
        """Inflections of one word are that word used again, not further evidence.

        Summing them let a note that writes "kraliçesizlik", "kraliçe" and "kraliçesini"
        outscore the note about queens on no more evidence than its own word endings — and
        that note opens with "Kraliçesizlik doğrulanırsa", so it was offering a remedy
        ahead of the sentence saying the reading is not a diagnosis.
        """
        self.assertEqual(self._ids("kraliçe")[0], "alarm-interpretation")

    def test_an_exact_match_outranks_an_inflected_one(self):
        """A prefix relationship is evidence, not proof, so it must not displace a passage
        that uses the searched word itself."""
        self.assertEqual(self._ids("varroa")[0], "season-autumn-varroa")


class RecordingConditionsTest(unittest.TestCase):
    """The knowledge base has always carried a rule about wind and rain.

    Nothing could ever fire it: the retriever had no way to know what the weather was when
    a recording was taken, so the one passage that explains a false alarm sat unreachable
    in the corpus.
    """

    def _event(self, **overrides):
        event = {
            "hive_id": "H3",
            "timestamp": "2026-09-04T12:00:00+00:00",
            "status": "ALARM",
            "anomaly_fraction": 1.0,
            "anomaly_severity": 0.37,
            "consecutive_anomalies": 6,
        }
        event.update(overrides)
        return event

    def test_wind_and_rain_bring_the_recording_conditions_passage_up(self):
        ids = [item["id"] for item in retrieve_guidance([self._event(wind_kmh=34.0, weather_code=61)], "tr", limit=4)]
        self.assertIn("false-alarm-weather", ids)

    def test_a_calm_dry_recording_leaves_it_out(self):
        ids = [item["id"] for item in retrieve_guidance([self._event(wind_kmh=4.0, weather_code=1)], "tr", limit=4)]
        self.assertNotIn("false-alarm-weather", ids)

    def test_unobserved_weather_is_not_read_as_good_weather(self):
        """With online weather off nothing is stamped, and unknown is not calm and dry.

        Matching the passage on an unstamped period would tell a beekeeper their recording
        was fine on the strength of a measurement nobody took.
        """
        profile = event_profile([self._event()])
        self.assertFalse(profile["has_weather"])
        self.assertFalse(profile["adverse_recording"])
        ids = [item["id"] for item in retrieve_guidance([self._event()], "tr", limit=4)]
        self.assertNotIn("false-alarm-weather", ids)

    def test_a_calm_but_wet_recording_still_counts_as_adverse(self):
        profile = event_profile([self._event(wind_kmh=3.0, weather_code=63)])
        self.assertTrue(profile["precipitation"])
        self.assertTrue(profile["adverse_recording"])

    def test_fog_is_not_treated_as_rain(self):
        """Fog does not lay the sound of rain onto a microphone."""
        profile = event_profile([self._event(wind_kmh=3.0, weather_code=45)])
        self.assertFalse(profile["precipitation"])
        self.assertFalse(profile["adverse_recording"])


class GuidancePresentationTest(unittest.TestCase):
    """A note is written for a beekeeper, so it is named and filed like one.

    The panel used to show each note as its slug — "alarm-sustained-run" — above a row of the
    retriever's own tags: "consecutive_anomalies", "false_positive", "health_confirmation".
    That is the machine's index, printed on the one screen where a person inspects what the
    model was told.
    """

    def test_every_note_is_named_in_both_languages(self):
        for entry in load_knowledge():
            with self.subTest(note=entry["id"]):
                for language in ("tr", "en"):
                    title = guidance_title(entry, language)
                    self.assertTrue(title, f"{entry['id']} has no {language} title")
                    self.assertNotEqual(title, entry["id"], "the slug is not a title")
                    self.assertNotIn("_", title)
                    self.assertNotIn("-", title.replace("Rüzgâr", ""))

    def test_every_note_is_filed_under_a_subject_a_reader_recognises(self):
        allowed = {"Alarm", "İzleme", "Normal", "Mevsim", "Yöntem", "Yanlış alarm", "Saha kontrolü",
                   "Sınırlar", "Koloni"}
        for entry in load_knowledge():
            with self.subTest(note=entry["id"]):
                self.assertIn(guidance_category(entry, "tr"), allowed)
                self.assertTrue(guidance_category(entry, "en"))

    def test_a_seasonal_note_is_filed_under_the_season_that_makes_it_apply(self):
        entries = {entry["id"]: entry for entry in load_knowledge()}
        self.assertEqual(guidance_category(entries["season-autumn-varroa"], "tr"), "Mevsim")
        self.assertEqual(guidance_category(entries["false-alarm-weather"], "tr"), "Yanlış alarm")
        self.assertEqual(guidance_category(entries["limits-not-diagnosis"], "tr"), "Sınırlar")
        self.assertEqual(guidance_category(entries["alarm-sustained-run"], "tr"), "Alarm")

    def test_retrieval_hands_back_the_name_and_the_subject_with_the_text(self):
        """Every reader of the retriever — panel, report, PDF — needs the same three."""
        note = retrieve_guidance([{
            "hive_id": "H3", "timestamp": "2026-09-04T12:00:00+00:00", "status": "ALARM",
            "anomaly_fraction": 1.0, "consecutive_anomalies": 6,
        }], "tr", limit=1)[0]
        self.assertEqual(set(note), {"id", "title", "category", "text"})
