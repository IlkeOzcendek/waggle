"""Tests for the model written narrative and the guardrails that police it.

Written with unittest, not pytest, because CI runs `python -m unittest discover`
and pytest is not a declared dependency.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from brain.foundry_report import (
    MAX_RECOMMENDATION_CHARACTERS,
    MAX_SUMMARY_CHARACTERS,
    MIN_SUMMARY_CHARACTERS,
    _extract_json,
    _narrative_facts,
    _validate_narrative,
    _with_model_narrative,
    render_report,
)

ALLOWED = {"H1", "H2", "H3"}

EVENTS = [
    {"hive_id": "H1", "status": "NORMAL", "anomaly_fraction": 0.1, "timestamp": "2026-08-24T10:00:00+00:00"},
    {"hive_id": "H2", "status": "WATCH", "anomaly_fraction": 0.5, "timestamp": "2026-08-25T10:00:00+00:00"},
    {"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 0.9, "timestamp": "2026-08-26T10:00:00+00:00", "inspection_result": "issue_confirmed"},
]

ALARM_ASSESSMENT = {
    "priority": "immediate",
    "pattern": "persistent_acoustic_change",
    "queen_loss_compatible": True,
    "inspection_required": True,
    "action_codes": ["inspect_hive", "check_queen"],
}

ROUTINE_ASSESSMENT = {
    "priority": "routine",
    "pattern": "within_baseline",
    "queen_loss_compatible": False,
    "inspection_required": False,
    "action_codes": ["continue_monitoring"],
}

# Realistic prose: names its hives, hedges, and long enough to be worth replacing the template with.
GOOD_TR = (
    "H1 kovanı dönem boyunca normal aralıkta kaldı. H2 için gelişen bir akustik değişim izleniyor. "
    "H3 kovanında kalıcı bir değişim ölçüldü; bu kraliçe kaybıyla uyumlu olabilir, tek başına kesin tanı değildir."
)
GOOD_EN = (
    "H1 stayed within its normal range for the period. A developing acoustic change is being watched on H2. "
    "H3 recorded a persistent change, which may be compatible with queen loss and is not a diagnosis on its own."
)


def payload(**overrides) -> dict:
    body = {"summary": GOOD_TR, "recommendations": ["H3 kovanını bugün kontrol edin.", "H2 için yeni kayıt alın."]}
    body.update(overrides)
    return body


def padded(text: str, language: str = "tr") -> str:
    """Extend a probe string past the minimum length so the length gate is not what fires."""
    filler = (
        " Bu cümle yalnızca uzunluk eşiğini geçmek için eklenmiştir ve içeriği etkilemez."
        if language == "tr" else
        " This sentence exists only to clear the minimum length requirement for the summary."
    )
    while len(text) < MIN_SUMMARY_CHARACTERS:
        text += filler
    return text


class NarrativeValidationTests(unittest.TestCase):
    def test_valid_narrative_is_accepted_and_whitespace_normalised(self):
        summary, recommendations = _validate_narrative(
            payload(summary=GOOD_TR.replace(". ", ".\n\n   ", 1)), ALLOWED, "tr"
        )
        self.assertEqual(summary, GOOD_TR)
        self.assertEqual(len(recommendations), 2)

    def test_malformed_narratives_are_rejected(self):
        cases = {
            "empty summary": payload(summary=""),
            "summary is not a string": payload(summary=None),
            "payload is not an object": ["nope"],
            "recommendations are not a list": payload(recommendations="not a list"),
            "no recommendations": payload(recommendations=[]),
            "too many recommendations": payload(recommendations=["a", "b", "c", "d", "e", "f"]),
            "recommendation is not a string": payload(recommendations=["ok", 42]),
            "summary too long": payload(summary="x" * (MAX_SUMMARY_CHARACTERS + 1)),
            "recommendation too long": payload(recommendations=["ok", "y" * (MAX_RECOMMENDATION_CHARACTERS + 1)]),
        }
        for label, body in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    _validate_narrative(body, ALLOWED, "tr")

    def test_single_recommendation_is_allowed(self):
        """A routine period produces one action code, so one recommendation must pass."""
        _, recommendations = _validate_narrative(
            payload(recommendations=["Rutin izlemeye devam edin."]), ALLOWED, "tr"
        )
        self.assertEqual(len(recommendations), 1)

    def test_thin_summary_is_rejected(self):
        body = payload(summary="H3 kovanında kalıcı akustik değişim var.")
        with self.assertRaisesRegex(ValueError, "too thin"):
            _validate_narrative(body, ALLOWED, "tr")

    def test_summary_naming_no_hive_is_rejected(self):
        body = payload(summary=padded("Kalıcı akustik değişim var, tek başına kesin tanı değildir."), recommendations=["Kovanı kontrol edin."])
        with self.assertRaisesRegex(ValueError, "names no hive"):
            _validate_narrative(body, ALLOWED, "tr")

    def test_unknown_hive_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown hives"):
            _validate_narrative(payload(summary=padded("H9 kovanı alarm verdi.")), ALLOWED, "tr")

    def test_lowercase_hive_reference_is_still_checked(self):
        with self.assertRaisesRegex(ValueError, "unknown hives"):
            _validate_narrative(payload(summary=padded("h9 kovanı alarm verdi.")), ALLOWED, "tr")

    def test_markup_and_links_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "markup or a link"):
            _validate_narrative(payload(summary=padded("H3 detayı: https://example.com")), ALLOWED, "tr")

    def test_prompt_leakage_is_rejected(self):
        for summary in (
            "H3 için kesinlik iddiası etmeden, yalnızca yeni olgu alınmalı ve fiziksel olarak incelenmelidir.",
            "H3 recorded a change and we are checking the queen'dict for the period.",
            "H3 status_counts show a persistent change across the reporting period.",
            "H3 için allowed_output alanına göre değerlendirme yapılmıştır bu dönemde.",
        ):
            with self.subTest(summary):
                with self.assertRaisesRegex(ValueError, "leaks its own prompt"):
                    _validate_narrative(payload(summary=padded(summary)), ALLOWED, "tr")

    def test_turkish_diagnosis_claims_are_rejected(self):
        for summary in (
            "H3 kovanının kraliçesi öldü.",
            "H3 için kraliçe kayıp durumda.",
            "H3 kovanında kraliçe kaybı gerçekleşti.",
            "H3 için teşhis edildi: kraliçe yok.",
            "H3 kovanında hastalık tespit edildi.",
            "H3 kolonisi ölmüş.",
        ):
            with self.subTest(summary):
                with self.assertRaisesRegex(ValueError, "diagnosis"):
                    _validate_narrative(payload(summary=padded(summary)), ALLOWED, "tr")

    def test_english_diagnosis_claims_are_rejected(self):
        for summary in (
            "The queen is dead in H3.",
            "H3 queen has died.",
            "H3 was diagnosed with queen loss.",
            "Disease is detected in H3.",
            "Disease was confirmed in H3.",
            "The H3 colony has died.",
        ):
            with self.subTest(summary):
                body = {"summary": padded(summary, "en"), "recommendations": ["Inspect H3 today."]}
                with self.assertRaisesRegex(ValueError, "diagnosis"):
                    _validate_narrative(body, ALLOWED, "en")

    def test_hedged_disclaimer_is_not_a_diagnosis_claim(self):
        """The disclaimer the prompt itself demands must survive the filter."""
        _validate_narrative(payload(summary=GOOD_TR), ALLOWED, "tr")
        _validate_narrative({"summary": GOOD_EN, "recommendations": ["Inspect H3 today."]}, ALLOWED, "en")

    def test_deterministic_template_survives_its_own_guardrails(self):
        for language in ("tr", "en"):
            with self.subTest(language):
                draft = render_report(EVENTS, ALARM_ASSESSMENT, language, "foundry-local:test")
                summary, recommendations = _validate_narrative(
                    {"summary": draft.summary, "recommendations": draft.recommendations},
                    ALLOWED,
                    language,
                    hedge_required=True,
                )
                self.assertTrue(summary)
                self.assertTrue(recommendations)

    def test_queen_loss_without_a_hedge_is_rejected(self):
        unhedged_tr = padded("H3 kovanında kalıcı bir akustik değişim ölçüldü ve durum sürüyor.")
        with self.assertRaisesRegex(ValueError, "hedge"):
            _validate_narrative(payload(summary=unhedged_tr), ALLOWED, "tr", hedge_required=True)

        unhedged_en = padded("H3 recorded a persistent acoustic change across the whole reporting period.", "en")
        with self.assertRaisesRegex(ValueError, "hedge"):
            _validate_narrative({"summary": unhedged_en, "recommendations": ["Inspect H3 today."]}, ALLOWED, "en", hedge_required=True)

    def test_hedged_queen_loss_is_accepted(self):
        _validate_narrative(payload(summary=GOOD_TR), ALLOWED, "tr", hedge_required=True)
        _validate_narrative({"summary": GOOD_EN, "recommendations": ["Inspect H3 today."]}, ALLOWED, "en", hedge_required=True)

    def test_uppercase_turkish_hedge_is_recognised(self):
        """Turkish dotted and dotless i break casefold, so folding must be explicit."""
        for summary in (
            "H3 KOVANINDA OLASI BİR DEĞİŞİM VAR VE BU DURUM İZLENMEYE DEVAM EDİLMELİDİR ŞİMDİLİK.",
            "H3 için kesin değil, ERKEN UYARI niteliğinde bir sinyal alındı ve takip sürüyor bu dönemde.",
        ):
            with self.subTest(summary):
                _validate_narrative(
                    {"summary": padded(summary), "recommendations": ["H3 kovanını kontrol edin."]},
                    ALLOWED,
                    "tr",
                    hedge_required=True,
                )

    def test_banned_phrase_cannot_be_assembled_across_fields(self):
        """Scanning each string separately must not create a match at the join."""
        _validate_narrative(
            {
                "summary": (
                    "H1 kovanının durumu normal görünüyor ve ölçümler dönem boyunca beklenen aralıkta kaldı. "
                    "Kayıtlarda dikkat çeken bir sapma yok, gözlenen tek şey kraliçe"
                ),
                "recommendations": ["yok denecek kadar az kayıt var."],
            },
            ALLOWED,
            "tr",
        )


class JsonExtractionTests(unittest.TestCase):
    def test_trailing_commentary_is_ignored(self):
        """Small models append prose after the JSON; the first object must still parse."""
        text = '{"summary": "ok", "recommendations": ["a"]}\n\nI hope this helps!'
        self.assertEqual(_extract_json(text)["summary"], "ok")

    def test_second_object_is_ignored(self):
        text = '{"summary": "first"}\n{"summary": "second"}'
        self.assertEqual(_extract_json(text)["summary"], "first")

    def test_leading_prose_is_skipped(self):
        text = 'Here is the report:\n{"summary": "ok"}'
        self.assertEqual(_extract_json(text)["summary"], "ok")

    def test_non_object_json_is_rejected(self):
        with self.assertRaises(ValueError):
            _extract_json("[1, 2, 3]")

    def test_text_without_json_is_rejected(self):
        with self.assertRaises(ValueError):
            _extract_json("no json here at all")


class NarrativeFactsTests(unittest.TestCase):
    def test_facts_expose_only_derived_values(self):
        facts = _narrative_facts(EVENTS, ALARM_ASSESSMENT, "tr")
        self.assertEqual(facts["event_count"], 3)
        self.assertEqual(facts["status_counts"], {"NORMAL": 1, "WATCH": 1, "ALARM": 1})
        self.assertEqual(facts["alarm_hives"], ["H3"])
        self.assertEqual(facts["confirmed_hives"], ["H3"])
        self.assertEqual(facts["peak_anomaly_percent"], 90)
        self.assertEqual(facts["priority"], "immediate")
        self.assertNotIn("timestamp", facts)


class NarrativeSubstitutionTests(unittest.TestCase):
    def setUp(self):
        self.previous = os.environ.get("WAGGLE_LLM_NARRATIVE")
        os.environ["WAGGLE_LLM_NARRATIVE"] = "1"
        self.addCleanup(self._restore)

    def _restore(self):
        if self.previous is None:
            os.environ.pop("WAGGLE_LLM_NARRATIVE", None)
        else:
            os.environ["WAGGLE_LLM_NARRATIVE"] = self.previous

    def test_rejected_narrative_keeps_the_template_draft(self):
        draft = render_report(EVENTS, ALARM_ASSESSMENT, "tr", "foundry-local:test")

        with patch("brain.foundry_report.compose_narrative", side_effect=RuntimeError("model unreachable")):
            result = _with_model_narrative(draft, EVENTS, ALARM_ASSESSMENT, [], "tr", "test")

        self.assertEqual(result.summary, draft.summary)
        self.assertEqual(result.generator, "foundry-local:test")

    def test_accepted_narrative_marks_the_generator(self):
        draft = render_report(EVENTS, ROUTINE_ASSESSMENT, "tr", "foundry-local:test")
        written = (GOOD_TR, ["H3 kovanını kontrol edin.", "H2 için kayıt alın."])

        with patch("brain.foundry_report.compose_narrative", return_value=written):
            result = _with_model_narrative(draft, EVENTS, ROUTINE_ASSESSMENT, [], "tr", "test")

        self.assertEqual(result.summary, GOOD_TR)
        self.assertEqual(result.recommendations, list(written[1]))
        self.assertNotEqual(result.recommendations, draft.recommendations)
        self.assertEqual(result.generator, "foundry-local:test+llm-narrative")
        self.assertEqual(result.assessment, draft.assessment)

    def test_mandated_inspection_steps_are_not_paraphrased(self):
        draft = render_report(EVENTS, ALARM_ASSESSMENT, "tr", "foundry-local:test")

        with patch("brain.foundry_report.compose_narrative", return_value=(GOOD_TR, ["Bir ara bakarsınız."])):
            result = _with_model_narrative(draft, EVENTS, ALARM_ASSESSMENT, [], "tr", "test")

        self.assertEqual(result.summary, GOOD_TR)
        self.assertEqual(result.recommendations, draft.recommendations)
        self.assertEqual(result.generator, "foundry-local:test+llm-narrative")

    def test_inspection_codes_alone_protect_the_recommendations(self):
        """A model may clear inspection_required; the action codes still bind."""
        assessment = dict(ALARM_ASSESSMENT, inspection_required=False)
        draft = render_report(EVENTS, assessment, "tr", "foundry-local:test")

        with patch("brain.foundry_report.compose_narrative", return_value=(GOOD_TR, ["Bir ara bakarsınız."])):
            result = _with_model_narrative(draft, EVENTS, assessment, [], "tr", "test")

        self.assertEqual(result.recommendations, draft.recommendations)

    def test_narrative_can_be_disabled(self):
        os.environ["WAGGLE_LLM_NARRATIVE"] = "0"
        draft = render_report(EVENTS, ROUTINE_ASSESSMENT, "tr", "foundry-local:test")

        with patch("brain.foundry_report.compose_narrative", return_value=(GOOD_TR, ["a", "b"])) as composer:
            result = _with_model_narrative(draft, EVENTS, ROUTINE_ASSESSMENT, [], "tr", "test")

        composer.assert_not_called()
        self.assertEqual(result.summary, draft.summary)


if __name__ == "__main__":
    unittest.main()
