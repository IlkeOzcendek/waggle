import asyncio
import json
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests

from brain import foundry_report
from brain.foundry_report import _foundry_connection, generate_agent_report, generate_report, recording_conditions, render_report

EVENTS = [ # A list in order to use in tests
    {"hive_id": "H1", "status": "NORMAL", "anomaly_fraction": .08, "consecutive_anomalies": 0},
    {"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 1.0, "consecutive_anomalies": 30},
]


class LocalModelTransportTest(unittest.TestCase):
    """The assessment is asked for as JSON, and streamed, at the server.

    response_format constrains generation to a valid object instead of leaving
    _extract_json to salvage one out of prose; stream is what tells a stalled model from a
    slow one. Not every OpenAI-compatible endpoint knows either, so the model path has to
    work on both kinds.
    """

    ROUTINE = {
        "priority": "routine",
        "pattern": "within_baseline",
        "queen_loss_compatible": False,
        "inspection_required": False,
        "action_codes": ["continue_monitoring"],
    }
    CALM = [{"hive_id": "H1", "status": "NORMAL", "anomaly_fraction": .05, "consecutive_anomalies": 0}]
    ENDPOINT = "http://127.0.0.1:5273/v1"

    def setUp(self):
        # The support map outlives one call by design, so a test must not inherit another's.
        foundry_report._EXTRA_PARAMETER_SUPPORT.clear()

    @classmethod
    def _streaming(cls, pieces=None):
        """A server-sent-event response carrying the assessment in pieces."""
        pieces = pieces if pieces is not None else [json.dumps(cls.ROUTINE)]
        lines = [f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]})}" for piece in pieces]
        lines = [line.encode("utf-8") for line in lines + ["", "data: [DONE]"]]
        response = Mock(status_code=200)
        # A fresh iterator per call, so one mock can serve more than one request.
        response.iter_lines.side_effect = lambda **kwargs: iter(lines)
        return response

    @classmethod
    def _blocking(cls):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": json.dumps(cls.ROUTINE)}}]}
        return response

    @staticmethod
    def _rejected(status=400):
        response = Mock(status_code=status)
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        return response

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_the_assessment_is_requested_as_streamed_json(self, post, _connection):
        post.return_value = self._streaming()

        assessment = foundry_report.assess_with_foundry(self.CALM)

        self.assertEqual(assessment["priority"], "routine")
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["response_format"], {"type": "json_object"})
        self.assertTrue(sent["stream"])

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_a_streamed_answer_is_assembled_in_order(self, post, _connection):
        post.return_value = self._streaming(['{"priority": "rou', 'tine", "pattern": "within_baseline", ',
                                             '"queen_loss_compatible": false, "inspection_required": false, ',
                                             '"action_codes": ["continue_monitoring"]}'])

        self.assertEqual(foundry_report.assess_with_foundry(self.CALM)["priority"], "routine")

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_progress_is_reported_as_the_answer_arrives(self, post, _connection):
        """The panel showed a climbing counter and nothing else for minutes. What it was
        missing is the one fact that separates a working model from a hung one."""
        body = json.dumps(self.ROUTINE)
        pieces = [body[:20], body[20:60], body[60:]]
        post.return_value = self._streaming(pieces)
        seen = []

        foundry_report.assess_with_foundry(self.CALM, on_progress=seen.append)

        # The count is cumulative, so the panel can show it climbing rather than resetting.
        self.assertEqual(seen, [20, 60, len(body)])

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_keep_alive_frames_are_not_mistaken_for_content(self, post, _connection):
        response = self._streaming()
        lines = [b": keep-alive", b"", b"data: not json at all"] + list(response.iter_lines())
        response.iter_lines.side_effect = lambda **kwargs: iter(lines)
        post.return_value = response

        self.assertEqual(foundry_report.assess_with_foundry(self.CALM)["priority"], "routine")

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_a_stream_that_closes_empty_is_a_failure_not_an_empty_answer(self, post, _connection):
        post.return_value = self._streaming([])

        with self.assertRaises(ValueError):
            foundry_report.assess_with_foundry(self.CALM)

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_silence_between_chunks_ends_the_run_rather_than_waiting_out_the_budget(self, post, _connection):
        """The read half of the timeout is the gap between chunks, so a model that stops
        emitting is given up on in well under a minute instead of at three minutes."""
        response = self._streaming()
        response.iter_lines.side_effect = requests.ReadTimeout("no chunk")
        post.return_value = response

        with self.assertRaises(requests.RequestException):
            foundry_report.assess_with_foundry(self.CALM)

        # (connect, read): the read timeout is the stall detector, well below the total.
        self.assertLess(post.call_args.kwargs["timeout"][1], foundry_report._llm_timeout())

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_a_stream_that_never_ends_still_meets_the_total_budget(self, post, _connection):
        """Emitting steadily but far too slowly passes every gap and would otherwise run
        for as long as the model felt like."""
        response = self._streaming(["tick"] * 50)
        post.return_value = response

        with patch("brain.foundry_report.time.monotonic", side_effect=[0, 10_000, 20_000]):
            with self.assertRaises(requests.Timeout):
                foundry_report.assess_with_foundry(self.CALM)

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_turkish_prose_survives_being_streamed(self, post, _connection):
        """The report is written in Turkish, so the transport has to carry ş, ğ and İ.

        requests can split a multi-byte character across chunk boundaries when it decodes
        the stream for you, which would land mangled words in the report a beekeeper reads.
        """
        summary = (
            "H3 kovanında ölçülen değişim dönem boyunca sürdü ve kayıtların tamamına yayıldı. "
            "Bu durum kraliçe kaybıyla uyumlu olabilir, ancak tek başına kesin tanı değildir. "
            "İlk adım olarak kovanı yerinde görmek gerekiyor; şiddetin yüksekliği beklemeyi zorlaştırıyor."
        )
        body = json.dumps({"summary": summary, "recommendations": ["H3 kovanını 24 saat içinde kontrol edin."]},
                          ensure_ascii=False)
        # Pieces cut at arbitrary offsets, exactly where a naive decoder would break.
        post.return_value = self._streaming([body[index:index + 7] for index in range(0, len(body), 7)])

        written, recommendations = foundry_report.compose_narrative(
            [{"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 1.0, "consecutive_anomalies": 30}],
            {"priority": "immediate", "pattern": "persistent_acoustic_change", "queen_loss_compatible": True,
             "inspection_required": True, "action_codes": ["inspect_hive", "check_queen"]},
            None, "tr",
        )

        self.assertEqual(written, summary)
        self.assertEqual(recommendations, ["H3 kovanını 24 saat içinde kontrol edin."])

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_an_endpoint_that_rejects_the_extras_is_asked_again_without_them(self, post, _connection):
        post.side_effect = [self._rejected(), self._blocking()]

        assessment = foundry_report.assess_with_foundry(self.CALM)

        self.assertEqual(assessment["priority"], "routine")
        sent = post.call_args.kwargs["json"]
        self.assertNotIn("response_format", sent)
        self.assertNotIn("stream", sent)

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_a_rejection_is_remembered_so_it_costs_one_request_not_one_per_report(self, post, _connection):
        post.side_effect = [self._rejected(), self._blocking(), self._blocking()]

        foundry_report.assess_with_foundry(self.CALM)
        foundry_report.assess_with_foundry(self.CALM)

        self.assertEqual(post.call_count, 3)
        self.assertNotIn("stream", post.call_args.kwargs["json"])

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_a_client_error_from_something_else_is_not_read_as_a_missing_capability(self, post, _connection):
        """A prompt too long for the context also comes back as a 400. Recording that as
        "this server supports neither" would silently disable both for every later report,
        so the negative is only kept once the plain retry has succeeded."""
        post.side_effect = [self._rejected(), self._rejected()]

        with self.assertRaises(requests.HTTPError):
            foundry_report.assess_with_foundry(self.CALM)

        self.assertEqual(foundry_report._EXTRA_PARAMETER_SUPPORT, {})

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report.requests.post")
    def test_a_server_error_is_raised_rather_than_retried(self, post, _connection):
        post.side_effect = [self._rejected(500)]

        with self.assertRaises(requests.HTTPError):
            foundry_report.assess_with_foundry(self.CALM)

        self.assertEqual(post.call_count, 1)

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report._chat_json")
    def test_one_invalid_answer_is_repaired_once(self, chat, _connection):
        chat.side_effect = [
            '{"priority": "ROUTINE"}',
            json.dumps(self.ROUTINE),
        ]

        assessment = foundry_report.assess_with_foundry(self.CALM)

        self.assertEqual(assessment["priority"], "routine")
        self.assertEqual(chat.call_count, 2)
        repair = chat.call_args.args[1]
        self.assertEqual(repair["max_tokens"], 220)
        self.assertIn("JSON true or false", repair["messages"][-1]["content"])

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report._chat_json", return_value="not json")
    def test_repair_is_bounded_to_one_attempt(self, chat, _connection):
        with self.assertRaisesRegex(ValueError, "after one repair attempt"):
            foundry_report.assess_with_foundry(self.CALM)

        self.assertEqual(chat.call_count, 2)

    @patch("brain.foundry_report._foundry_connection", return_value=(ENDPOINT, "test-model"))
    @patch("brain.foundry_report._chat_json", return_value=json.dumps(ROUTINE))
    def test_valid_answer_is_never_retried(self, chat, _connection):
        foundry_report.assess_with_foundry(self.CALM)
        self.assertEqual(chat.call_count, 1)


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

    def test_the_template_summary_closes_every_sentence(self):
        """The clauses used to run together on a bare space.

        This is the text a beekeeper reads whenever the model's prose is rejected, which
        the example-copy guard makes the common case rather than the rare one.
        """
        events = [
            {"hive_id": "H1", "status": "NORMAL", "anomaly_fraction": .08},
            {"hive_id": "H2", "status": "WATCH", "anomaly_fraction": .66},
            {"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 1.0},
        ]

        for language, run_on in (("tr", "kaldı H2"), ("en", "baseline A developing")):
            with self.subTest(language=language):
                summary = render_report(events, foundry_report._fallback_assessment(events), language, "test").summary
                self.assertNotIn(run_on, summary)
                self.assertTrue(summary.endswith("."))
                # No clause is closed twice by the joining.
                self.assertNotIn("..", summary)

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


class ToolSupportTableTest(unittest.TestCase):
    """Foundry reports tool support per model, and the panel believes that table."""

    # Trimmed from a real `foundry model list`. The wrapping is the point: a name that does
    # not fit its column continues on the next row, whose other cells are blank.
    LISTING = """+------------------------------------------------------------------------------+
| Model Name                  | Type       | Size    | Device | Tools | Cached |
|-----------------------------+------------+---------+--------+-------+--------|
| gemma-4-e2b-it              | Multimodal | 6.9 GB  | GPU    | ●     | ●      |
| phi-3.5-mini                | Chat       | 2.2 GB  | GPU    | ○     | ●      |
| qwen2.5-1.5b                | Chat       | 1.5 GB  | GPU    | ●     | ●      |
| ministral-3-3b-instruct-251 | Multimodal | 3.6 GB  | GPU    | ●     | ○      |
| 2                           |            |         |        |       |        |
| nemotron-speech-streaming-e | Speech     | 696 MB  | CPU    | ○     | ○      |
| n-0.6b                      |            |         |        |       |        |
"""

    def test_a_wrapped_name_is_rejoined_before_it_is_matched(self):
        """Otherwise the answer for these models is a silent, indistinguishable 'no'."""
        support = foundry_report._tool_support(self.LISTING)
        self.assertTrue(support["ministral-3-3b-instruct-2512"])
        self.assertFalse(support["nemotron-speech-streaming-en-0.6b"])
        self.assertNotIn("ministral-3-3b-instruct-251", support)

    def test_the_marker_column_decides(self):
        support = foundry_report._tool_support(self.LISTING)
        self.assertTrue(support["qwen2.5-1.5b"])
        self.assertFalse(support["phi-3.5-mini"])

    def test_the_header_and_rules_are_not_models(self):
        support = foundry_report._tool_support(self.LISTING)
        self.assertNotIn("Model Name", support)
        self.assertEqual(len(support), 5)

    @patch("brain.foundry_report._run_foundry")
    def test_an_unreadable_listing_denies_tools_rather_than_guessing(self, run):
        """Attaching tools to a model that cannot call them derails its answer."""
        run.side_effect = RuntimeError("foundry is not installed")
        self.assertFalse(foundry_report._model_supports_tools("qwen2.5-1.5b"))

    @patch("brain.foundry_report._run_foundry")
    def test_a_model_missing_from_the_catalogue_gets_no_tools(self, run):
        run.return_value = self.LISTING
        self.assertFalse(foundry_report._model_supports_tools("a-model-that-is-not-listed"))
        self.assertTrue(foundry_report._model_supports_tools("ministral-3-3b-instruct-2512"))

    @patch("brain.foundry_report._run_foundry")
    def test_the_device_column_is_read_as_well_as_the_tool_column(self, run):
        """"This took four minutes" and "this took four minutes on the CPU" are different
        facts, and the catalogue had been reporting the second one into nothing."""
        run.return_value = self.LISTING
        foundry_report.model_device.cache_clear()
        self.assertEqual(foundry_report.model_device("phi-3.5-mini"), "GPU")
        foundry_report.model_device.cache_clear()
        self.assertEqual(foundry_report.model_device("nemotron-speech-streaming-en-0.6b"), "CPU")

    @patch("brain.foundry_report._run_foundry", side_effect=RuntimeError("foundry is not installed"))
    def test_an_unreadable_listing_leaves_the_device_unknown_rather_than_guessing(self, _run):
        foundry_report.model_device.cache_clear()
        self.assertIsNone(foundry_report.model_device("phi-3.5-mini"))


class UnloadTest(unittest.TestCase):
    """Releasing the model is off by default: it trades idle memory for a reload."""

    def test_it_is_off_unless_it_is_switched_on(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WAGGLE_LLM_UNLOAD_AFTER_REPORT", None)
            self.assertFalse(foundry_report.unload_after_report())
            os.environ["WAGGLE_LLM_UNLOAD_AFTER_REPORT"] = "1"
            self.assertTrue(foundry_report.unload_after_report())
            os.environ.pop("WAGGLE_LLM_UNLOAD_AFTER_REPORT", None)

    @patch("brain.foundry_report.subprocess.run")
    def test_it_asks_foundry_to_drop_the_model(self, run):
        self.assertTrue(foundry_report.unload_model("phi-3.5-mini"))
        self.assertEqual(run.call_args.args[0], ["foundry", "model", "unload", "phi-3.5-mini"])

    @patch("brain.foundry_report.subprocess.run", side_effect=RuntimeError("no foundry"))
    def test_a_failure_to_free_memory_never_fails_a_finished_report(self, _run):
        self.assertFalse(foundry_report.unload_model("phi-3.5-mini"))


class PatternValidationTest(unittest.TestCase):
    """The pattern is shown to people, so it may only ever be one of the three we define."""

    NORMAL = [{"hive_id": "H1", "status": "NORMAL", "anomaly_fraction": .05, "consecutive_anomalies": 0}]
    ALARMING = [{"hive_id": "H3", "status": "ALARM", "anomaly_fraction": .9, "consecutive_anomalies": 30}]

    @staticmethod
    def _model_said(**overrides):
        value = {"priority": "watch", "pattern": "developing_acoustic_change",
                 "queen_loss_compatible": False, "inspection_required": False,
                 "action_codes": ["record_again"]}
        value.update(overrides)
        return value

    def test_an_invented_pattern_is_replaced_by_the_one_the_priority_implies(self):
        """A real run had a model answer "alarm"; it reached the panel and the PDF verbatim."""
        result = foundry_report._validate_assessment(self._model_said(pattern="alarm"), self.NORMAL)
        self.assertEqual(result["pattern"], "developing_acoustic_change")

    def test_a_missing_pattern_is_filled_in_rather_than_left_blank(self):
        value = self._model_said()
        del value["pattern"]
        result = foundry_report._validate_assessment(value, self.NORMAL)
        self.assertIn(result["pattern"], foundry_report.ALLOWED_PATTERNS)

    def test_a_valid_pattern_is_kept_as_the_model_wrote_it(self):
        result = foundry_report._validate_assessment(
            self._model_said(priority="routine", pattern="within_baseline",
                             action_codes=["continue_monitoring"]), self.NORMAL)
        self.assertEqual(result["pattern"], "within_baseline")

    def test_an_alarm_moves_the_pattern_with_the_priority(self):
        """Otherwise the card reads "Acil" beside "Normal aralıkta"."""
        result = foundry_report._validate_assessment(
            self._model_said(priority="routine", pattern="within_baseline",
                             action_codes=["continue_monitoring"]), self.ALARMING)
        self.assertEqual(result["priority"], "immediate")
        self.assertEqual(result["pattern"], "persistent_acoustic_change")

    def test_the_prompt_tells_the_model_which_patterns_exist(self):
        prompt = foundry_report._assessment_prompt(self.NORMAL)
        self.assertEqual(sorted(foundry_report.ALLOWED_PATTERNS), prompt["allowed_pattern"])

    def test_string_booleans_are_rejected_instead_of_becoming_true(self):
        for field in ("queen_loss_compatible", "inspection_required"):
            with self.subTest(field=field):
                value = self._model_said(**{field: "false"})
                with self.assertRaisesRegex(ValueError, "JSON booleans"):
                    foundry_report._validate_assessment(value, self.NORMAL)

    def test_missing_boolean_fields_are_rejected(self):
        value = self._model_said()
        del value["inspection_required"]
        with self.assertRaisesRegex(ValueError, "JSON booleans"):
            foundry_report._validate_assessment(value, self.NORMAL)

    def test_actions_and_booleans_are_canonical_for_the_final_priority(self):
        cases = (
            ("routine", ["record_again"], ["continue_monitoring"], False),
            ("watch", ["inspect_hive", "check_queen"], ["record_again", "continue_monitoring"], False),
            ("immediate", ["continue_monitoring"], ["inspect_hive", "check_queen"], True),
        )
        for priority, proposed, expected, inspection in cases:
            with self.subTest(priority=priority):
                result = foundry_report._validate_assessment(
                    self._model_said(
                        priority=priority,
                        pattern=foundry_report.PATTERN_FOR_PRIORITY[priority],
                        action_codes=proposed,
                    ),
                    self.NORMAL,
                )
                self.assertEqual(result["action_codes"], expected)
                self.assertEqual(result["inspection_required"], inspection)
                self.assertEqual(result["queen_loss_compatible"], inspection)


class ResponseEnvelopeTest(unittest.TestCase):
    """Models differ in how deep they put the object they were asked for."""

    ASSESSMENT = ('{"priority": "immediate", "pattern": "persistent_acoustic_change", '
                  '"queen_loss_compatible": false, "inspection_required": true, '
                  '"action_codes": ["check_queen"]}')

    def test_a_bare_object_is_returned_as_it_is(self):
        self.assertEqual(foundry_report._extract_json(self.ASSESSMENT)["priority"], "immediate")

    def test_an_object_wrapped_in_a_single_key_is_unwrapped(self):
        """This is what qwen2.5-1.5b answers, and why the cross-check never once ran."""
        wrapped = '```json\n{"response": ' + self.ASSESSMENT + '}\n```'
        self.assertEqual(foundry_report._extract_json(wrapped)["priority"], "immediate")

    def test_any_wrapper_name_works_because_the_shape_is_what_identifies_it(self):
        for key in ("response", "result", "assessment", "output"):
            with self.subTest(key=key):
                wrapped = '{"%s": %s}' % (key, self.ASSESSMENT)
                self.assertEqual(foundry_report._extract_json(wrapped)["priority"], "immediate")

    def test_a_wrapper_without_an_assessment_inside_is_left_alone(self):
        value = foundry_report._extract_json('{"note": {"text": "no idea"}}')
        self.assertEqual(value, {"note": {"text": "no idea"}})

    def test_a_single_key_assessment_is_not_treated_as_a_wrapper(self):
        value = foundry_report._extract_json('{"priority": "routine"}')
        self.assertEqual(value, {"priority": "routine"})


class AgentToolLanguageTest(unittest.TestCase):
    """The passages a tool hands the model must be in the language of the report.

    `look_up_guidance` asked for English whatever was being written, so a Turkish report
    could be grounded in text it was unable to quote.
    """

    EVENTS = [{"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 1.0,
               "consecutive_anomalies": 30, "timestamp": "2026-09-01T10:00:00+00:00"}]

    def _tools_for(self, language):
        """Run the agent path against a stand-in framework and keep the tools it was given."""
        captured = {}

        class FakeResponse:
            text = "IMMEDIATE"

        class FakeAgent:
            def __init__(self, **kwargs):
                captured["tools"] = kwargs.get("tools")

            async def run(self, _prompt):
                return FakeResponse()

        framework = types.ModuleType("agent_framework")
        framework.Agent = FakeAgent
        openai_module = types.ModuleType("agent_framework.openai")
        openai_module.OpenAIChatCompletionClient = lambda **kwargs: None

        with patch.dict(sys.modules, {"agent_framework": framework, "agent_framework.openai": openai_module}), \
             patch.object(foundry_report, "_foundry_connection", return_value=("http://local/v1", "test-model")), \
             patch.object(foundry_report, "_model_supports_tools", return_value=True):
            asyncio.run(foundry_report.assess_with_agent_framework(self.EVENTS, "test-model", [], language))
        return {tool.__name__: tool for tool in captured["tools"]}

    def test_the_guidance_tool_answers_in_the_report_language(self):
        turkish = json.loads(self._tools_for("tr")["look_up_guidance"]("varroa"))
        english = json.loads(self._tools_for("en")["look_up_guidance"]("varroa"))
        self.assertEqual([note["id"] for note in turkish], [note["id"] for note in english])
        self.assertNotEqual(turkish[0]["text"], english[0]["text"])
        self.assertIn("varroa", turkish[0]["text"].lower())

    @patch("brain.foundry_report._cross_check_model", return_value="")
    @patch("brain.foundry_report._with_model_narrative", side_effect=lambda draft, *args, **kwargs: draft)
    @patch("brain.foundry_report.assess_with_agent_framework", new_callable=AsyncMock)
    def test_the_report_language_reaches_the_agent(self, assess, _narrative, _cross):
        assess.return_value = {"priority": "watch", "pattern": "developing_acoustic_change",
                               "queen_loss_compatible": False, "inspection_required": False,
                               "action_codes": ["record_again"]}
        generate_agent_report(self.EVENTS, "tr", "test-model")
        self.assertEqual(assess.call_args[0][3], "tr")

    def test_the_second_model_is_asked_in_the_same_language(self):
        with patch.object(foundry_report, "_cross_check_model", return_value="qwen2.5-1.5b"), \
             patch.object(foundry_report, "assess_with_agent_framework", new_callable=AsyncMock) as agent:
            agent.return_value = {"priority": "immediate", "pattern": "persistent_acoustic_change",
                                  "queen_loss_compatible": True, "inspection_required": True,
                                  "action_codes": ["inspect_hive", "check_queen"]}
            foundry_report._cross_check(self.EVENTS, [], agent.return_value.copy(), "phi-3.5-mini", "tr")
        self.assertEqual(agent.call_args[0][3], "tr")


class AnsweredAlarmTest(unittest.TestCase):
    """An alarm is a request to go and look. A field check is the answer to it.

    The report used to keep every period holding an ALARM at "immediate", so a week whose
    alarm had been inspected still opened with "1 kovan acil kontrol istiyor" and
    recommended the inspection that had just been done — directly under its own sentence
    saying the field check found nothing. Only the outcome that actually settles the
    question takes the alarm off the list.
    """

    ALARM = {"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 1.0,
             "anomaly_severity": .37, "consecutive_anomalies": 30,
             "timestamp": "2026-09-03T09:00:00+00:00"}

    def _with(self, result):
        return [{**self.ALARM, "acknowledged_at": "2026-09-04T07:00:00+00:00",
                 "inspection_result": result}]

    def test_an_uninspected_alarm_stays_urgent(self):
        self.assertEqual(foundry_report._fallback_assessment([self.ALARM])["priority"], "immediate")

    def test_an_outcome_that_settles_nothing_stays_urgent(self):
        """A confirmed issue is a reason to act; an inconclusive visit did not answer."""
        for result in ("issue_confirmed", "uncertain"):
            with self.subTest(result=result):
                self.assertEqual(
                    foundry_report._fallback_assessment(self._with(result))["priority"], "immediate"
                )

    def test_an_alarm_found_sound_in_the_field_stops_asking_for_the_inspection(self):
        assessment = foundry_report._fallback_assessment(self._with("no_issue_found"))
        self.assertEqual(assessment["priority"], "watch")
        self.assertFalse(assessment["inspection_required"])
        recommendations = render_report(self._with("no_issue_found"), assessment, "tr", "test").recommendations
        self.assertFalse(any("fiziksel olarak kontrol" in item for item in recommendations))

    def test_one_answered_alarm_does_not_answer_another(self):
        events = [*self._with("no_issue_found"), {**self.ALARM, "hive_id": "H2"}]
        self.assertEqual(foundry_report._fallback_assessment(events)["priority"], "immediate")

    def test_a_checked_period_is_still_not_routine(self):
        """The sound did change, so the model may not file the week away as ordinary."""
        calm = {"priority": "routine", "pattern": "within_baseline", "queen_loss_compatible": False,
                "inspection_required": False, "action_codes": ["continue_monitoring"]}
        self.assertEqual(
            foundry_report._validate_assessment(dict(calm), self._with("no_issue_found"))["priority"],
            "watch",
        )
        self.assertEqual(
            foundry_report._validate_assessment(dict(calm), [self.ALARM])["priority"], "immediate"
        )


class RecordingConditionsTest(unittest.TestCase):
    """Weather may only weaken an acoustic decision, never support one.

    Wind and rain put their own sound on the microphone, so a recording taken in them can
    read as anomalous on its own. The report has to say so — and has to say it without
    turning into a reason to leave an alarming hive shut.
    """

    ALARM = {"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 1.0, "consecutive_anomalies": 30}
    ASSESSMENT = {
        "priority": "immediate", "pattern": "persistent_acoustic_change",
        "queen_loss_compatible": True, "inspection_required": True,
        "action_codes": ["inspect_hive", "check_queen"],
    }

    def test_no_conditions_are_reported_when_the_weather_was_never_observed(self):
        self.assertIsNone(recording_conditions([dict(self.ALARM)]))

    def test_no_conditions_are_reported_when_the_weather_was_fine(self):
        """A sentence announcing that the weather was fine has spent a sentence on nothing."""
        self.assertIsNone(recording_conditions([dict(self.ALARM, wind_kmh=5.0, weather_code=1)]))

    def test_a_normal_record_in_bad_weather_raises_no_question(self):
        calm_decision = {"hive_id": "H1", "status": "NORMAL", "anomaly_fraction": .05,
                         "consecutive_anomalies": 0, "wind_kmh": 40.0, "weather_code": 65}
        self.assertIsNone(recording_conditions([calm_decision]))

    def test_a_windy_alarm_is_reported_with_the_hive_and_the_wind(self):
        conditions = recording_conditions([dict(self.ALARM, wind_kmh=34.0, weather_code=61)])
        self.assertEqual(conditions["hives"], ["H3"])
        self.assertEqual(conditions["peak_wind_kmh"], 34)
        self.assertTrue(conditions["wind"])
        self.assertTrue(conditions["precipitation"])

    def test_the_summary_frames_the_weather_as_doubt_about_the_measurement(self):
        draft = render_report([dict(self.ALARM, wind_kmh=34.0, weather_code=61)],
                              dict(self.ASSESSMENT), "tr", "safe-fallback")
        self.assertIn("ölçüm koşulunun şüpheli", draft.summary)
        self.assertIn("34 km/s", draft.summary)

    def test_the_extra_step_never_displaces_the_inspection(self):
        """An alarm still opens with the inspection; measuring again is added after it."""
        draft = render_report([dict(self.ALARM, wind_kmh=34.0, weather_code=61)],
                              dict(self.ASSESSMENT), "en", "safe-fallback")
        self.assertEqual(draft.recommendations[0],
                         "Perform a physical inspection of the hive that raised the alarm")
        self.assertIn("calm, dry weather", draft.recommendations[-1])

    def test_a_calm_period_gains_no_extra_step(self):
        draft = render_report([dict(self.ALARM, wind_kmh=5.0, weather_code=1)],
                              dict(self.ASSESSMENT), "tr", "safe-fallback")
        self.assertEqual(len(draft.recommendations), 2)
        self.assertNotIn("sakin", draft.summary)

    def test_the_model_is_told_that_weather_only_lowers_confidence(self):
        prompt = foundry_report._assessment_prompt([dict(self.ALARM, wind_kmh=34.0)])
        self.assertTrue(any("never evidence of queen loss" in rule for rule in prompt["rules"]))


class FoundryOutputTest(unittest.TestCase):
    """Terminal colour is formatting, not data.

    Foundry colours the device column, and captured output keeps the escape sequences. Read
    as text they travelled through the catalogue into the report's provenance and reached
    the panel, where the beekeeper was shown
    "Çalıştığı birim: [38;2;22;163;74mGPU [0m".
    """

    LISTING = (
        "Alias                          | Device | Task               | File Size | License | Model ID\n"
        "-------------------------------|--------|--------------------|-----------|---------|----------\n"
        "| phi-3.5-mini | chat-completion | 2.16 GB | \x1b[38;2;22;163;74mGPU\x1b[0m | ● | yes |\n"
    )

    def test_colour_never_reaches_the_parser(self):
        with patch.object(foundry_report, "subprocess") as fake:
            fake.run.return_value = Mock(stdout=self.LISTING)
            self.assertNotIn("\x1b", foundry_report._run_foundry("model", "list"))
            self.assertNotIn("[38;2", foundry_report._run_foundry("model", "list"))

    def test_the_device_is_read_as_a_plain_word(self):
        foundry_report.model_device.cache_clear()
        with patch.object(foundry_report, "_run_foundry", return_value=foundry_report.ANSI_ESCAPE.sub("", self.LISTING)):
            self.assertEqual(foundry_report.model_device("phi-3.5-mini"), "GPU")
        foundry_report.model_device.cache_clear()

    def test_a_device_cell_holding_only_colour_reads_as_unknown(self):
        """An empty cell is not a device name, and printing one says nothing true."""
        blank = self.LISTING.replace("\x1b[38;2;22;163;74mGPU\x1b[0m", "\x1b[0m")
        foundry_report.model_device.cache_clear()
        with patch.object(foundry_report, "_run_foundry", return_value=foundry_report.ANSI_ESCAPE.sub("", blank)):
            self.assertIsNone(foundry_report.model_device("phi-3.5-mini"))
        foundry_report.model_device.cache_clear()
