"""

It generates a safe bilingual hive report with Microsoft Foundry Local

"""

from __future__ import annotations # Postpones evaluation of type annotations which makes forward references and modern type hints easier to use
from dataclasses import dataclass, replace # Provides @dataclass for defining lightweight classes that mainly store structured data
from datetime import datetime, timedelta, timezone
from typing import Literal # Literal restricts a type hint to a fixed set of allowed string values
from urllib.parse import urlparse # It tells a host-only endpoint override apart from one that already carries a path

import argparse
import asyncio # It runs the asynchronous Agent Framework assessment from synchronous code
import json
import logging
from functools import lru_cache # It records why an optional model path degraded to the deterministic fallback
import os
import re

import subprocess # It executes Foundry CLI commands such as model load and server restart
import time # It bounds a streamed answer that arrives steadily but far too slowly
import unicodedata # It folds Turkish text so an uppercase hedge is still recognised

import requests

from brain.local_rag import PRECIPITATION_CODE, WIND_NOISE_KMH, event_profile, retrieve_guidance, search_guidance

logger = logging.getLogger(__name__)

Language = Literal["tr", "en"]

ALLOWED_PRIORITIES = {"routine", "watch", "immediate"} # Whitelist of operational priority values the model is allowed to return
ALLOWED_ACTIONS = {"continue_monitoring", "record_again", "inspect_hive", "check_queen"} # Whitelist of actions that can appear in a validated assessment
# The pattern names the shape of the change. It is descriptive where the priority is the
# decision, so an unrecognised one is corrected rather than thrown away with the whole
# assessment: a real run had a model answer "alarm", which reached the panel, the PDF and
# the export verbatim because nothing checked this field.
ALLOWED_PATTERNS = {"within_baseline", "developing_acoustic_change", "persistent_acoustic_change"}
PATTERN_FOR_PRIORITY = {
    "routine": "within_baseline",
    "watch": "developing_acoustic_change",
    "immediate": "persistent_acoustic_change",
}
POLICY_FOR_PRIORITY = {
    "routine": {
        "queen_loss_compatible": False,
        "inspection_required": False,
        "action_codes": ["continue_monitoring"],
    },
    "watch": {
        "queen_loss_compatible": False,
        "inspection_required": False,
        "action_codes": ["record_again", "continue_monitoring"],
    },
    "immediate": {
        "queen_loss_compatible": True,
        "inspection_required": True,
        "action_codes": ["inspect_hive", "check_queen"],
    },
}

# Immutable container for the final bilingual report and its assessment metadata.
@dataclass(frozen=True)
# Stores the rendered summary, recommendations, hive IDs, language, generator, and raw assessment.
class ReportDraft:
    summary: str
    recommendations: list[str]
    hive_ids: list[str]
    language: Language
    generator: str
    assessment: dict

# Foundry colours its table, and captured output keeps the escape sequences: the device
# cell arrives as "\x1b[38;2;22;163;74mGPU\x1b[0m". Parsed as-is they travel through the
# catalogue into the report's provenance and out to the panel, where a beekeeper reads
# "Çalıştığı birim: [38;2;22;163;74mGPU [0m". They are terminal formatting, not data.
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _run_foundry(*arguments: str) -> str: # It runs one Foundry CLI command and returns stdout check = True makes failures raise an exception
    result = subprocess.run( # It execute the requested Foundry command as a child process
        ["foundry", *arguments],
        check = True,
        text = True,
        capture_output = True,
    )
    return ANSI_ESCAPE.sub("", result.stdout) # Plain text, so the parser reads cells and not colours

def _llm_timeout(default: float = 180) -> float: # It reads the model call timeout so slow hardware can be accommodated without a code change
    try:
        return max(float(os.getenv("WAGGLE_LLM_TIMEOUT", default)), 1)
    except ValueError:
        logger.warning("WAGGLE_LLM_TIMEOUT is not a number; using %s seconds", default)
        return default

def _foundry_connection(alias: str) -> tuple[str, str]: # It ensures the requested local model is loaded and returns
    # An explicit endpoint bypasses CLI discovery entirely, which lets the model path
    # run against any OpenAI-compatible server and be exercised without Foundry installed.
    configured_base_url = os.getenv("WAGGLE_FOUNDRY_BASE_URL", "").strip()

    if configured_base_url:
        endpoint = configured_base_url.rstrip("/")
        # The CLI path appends /v1, so a host-only override is completed the same way.
        if urlparse(endpoint).path in ("", "/"):
            endpoint = f"{endpoint}/v1"
        return endpoint, os.getenv("WAGGLE_LLM_MODEL", alias)

    def load_and_probe() -> tuple[str, str]:
        subprocess.run(
            ["foundry", "model", "load", alias],
            check = True,
            stdout = subprocess.DEVNULL,
            stderr = subprocess.DEVNULL,
            timeout = 120,
        )

        status = json.loads(_run_foundry("server", "status", "--output", "json"))

        model = json.loads(_run_foundry("model", "info", alias, "--output", "json"))["model"]
       
        base_url = status["webUrls"][0].rstrip("/") + "/v1"
   
        probe = requests.get(f"{base_url}/models", timeout = 5)

        probe.raise_for_status()

        return base_url, model["id"]

    try:
        return load_and_probe()
    
    except requests.RequestException: # If the probe fails it assumed the Foundry daemon URL may be stale

        subprocess.run(
            ["foundry", "server", "restart"],
            check = True,
            stdout = subprocess.DEVNULL,
            stderr = subprocess.DEVNULL,
            timeout = 120,
        )

        return load_and_probe()

@lru_cache(maxsize=8)
def _model_supports_tools(alias: str) -> bool:
    """Whether this local model can call tools at all.

    Foundry's catalogue reports it per model, and most of the small ones cannot. Attaching
    tools to a model that cannot call them is not harmless: the instructions describing
    them eat context and invite a small model to answer with a tool name instead of the
    single token the pipeline expects. Better to ask first and adapt.
    """
    try:
        listing = _run_foundry("model", "list")
    except Exception as error:  # noqa: BLE001 - the CLI may be absent or slow to start
        logger.warning("Could not read the Foundry model list (%s); assuming no tool support", type(error).__name__)
        return False
    return _tool_support(listing).get(alias, False)


def _tool_support(listing: str) -> dict[str, bool]:
    """Whether each model can call tools, from the catalogue table."""
    return {name: entry["tools"] for name, entry in _catalogue(listing).items()}


@lru_cache(maxsize=8)
def model_device(alias: str) -> str | None:
    """Which device Foundry runs this model on: GPU, NPU or CPU.

    The catalogue has always reported it beside the tool column and only the tool column
    was read. It belongs in a report's provenance for the same reason the acoustic model
    file does — "this took four minutes" and "this took four minutes on the CPU" are
    different facts — and it is the first thing to look at when a run is slow.
    """
    try:
        listing = _run_foundry("model", "list")
    except Exception as error:  # noqa: BLE001 - the CLI may be absent or slow to start
        logger.info("Could not read the Foundry model list (%s); the device stays unknown", type(error).__name__)
        return None
    entry = _catalogue(listing).get(alias)
    device = ((entry or {}).get("device") or "").strip()
    return device or None


def unload_model(alias: str) -> bool:
    """Ask Foundry to drop a loaded model, freeing the memory it holds.

    Off by default and deliberately so: the panel loads the same one or two models for
    every report, and unloading between runs trades a few gigabytes of idle memory for a
    reload on the next run. It is worth switching on where the memory matters more than
    the latency, which on a field machine it may.
    """
    try:
        subprocess.run(
            ["foundry", "model", "unload", alias],
            check = True,
            stdout = subprocess.DEVNULL,
            stderr = subprocess.DEVNULL,
            timeout = 60,
        )
        logger.info("Unloaded %s", alias)
        return True
    except Exception as error:  # noqa: BLE001 - freeing memory must never fail a finished report
        logger.warning("Could not unload %s (%s)", alias, type(error).__name__)
        return False


def unload_after_report() -> bool:
    """Whether a finished report run should release the models it loaded."""
    return os.getenv("WAGGLE_LLM_UNLOAD_AFTER_REPORT", "0") == "1"


def _catalogue(listing: str) -> dict[str, dict]:
    """Tool support and device per model name, read from Foundry's `model list` table.

    The table wraps a name that does not fit its column onto a following row whose other
    cells are blank — `ministral-3-3b-instruct-251` then `2`. Comparing a name against a
    single row therefore never matches those models, and the silent answer is "no tool
    support", which is indistinguishable from a real no. Rejoin the fragments first.
    """
    catalogue: dict[str, dict] = {}
    last_name: str | None = None
    for line in listing.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        # | name | type | size | device | tools | cached |
        if len(cells) < 7 or not cells[1] or set(cells[1]) <= {"-", "+"}:
            continue
        if cells[2]:  # A row of its own: a name with a type beside it.
            if cells[1] == "Model Name":
                continue
            last_name = cells[1]
            catalogue[last_name] = {"tools": "\u25cf" in cells[5], "device": cells[4]}
        elif last_name is not None:  # The tail of the name above.
            catalogue[last_name + cells[1]] = catalogue.pop(last_name)
            last_name += cells[1]
    return catalogue


def _extract_json(text: str) -> dict: # It extracts the first JSON object from model text and rejects non dictionary output

    decoder = json.JSONDecoder()

    # Small models often append commentary, or a second object, after the JSON they were
    # asked for. raw_decode stops at the end of the first complete value, so trailing
    # noise no longer swallows the whole response the way a greedy regex did.
    for start in (index for index, character in enumerate(text) if character == "{"):
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue

        if isinstance(value, dict):
            return _unwrap_envelope(value)

    raise ValueError("Foundry response did not contain a JSON object")

def _unwrap_envelope(value: dict) -> dict:
    """Look inside a single-key wrapper such as {"response": {...}}.

    Models differ in how they hand back an object. `qwen2.5-1.5b` answers correctly but
    nests it under "response", and the assessment was rejected as unsupported when the only
    real problem was the depth — the cross-check with that model had never once succeeded.
    Only a lone dictionary value is unwrapped, so a real assessment is never mistaken for a
    wrapper: it has five keys of its own.
    """
    if "priority" in value or len(value) != 1:
        return value
    inner = next(iter(value.values()))
    return inner if isinstance(inner, dict) and "priority" in inner else value

def _outstanding_alarms(events: list[dict]) -> list[dict]:
    """The alarms still asking for something.

    An alarm is a request to go and look at a hive. Once someone has looked and recorded
    that it was sound, the request has been answered — and leaving the report at
    "immediate" made it ask for the inspection that had just been done, directly beneath
    its own sentence saying the inspection found nothing.

    Only that one outcome takes an alarm off the list. A confirmed issue is a reason to
    stay urgent, an inconclusive visit did not settle the question, and an alarm nobody
    has been to yet is the reason the priority exists. Downgrading only what was seen and
    found sound is the single direction that cannot cost a colony.
    """
    return [
        event for event in events
        if event.get("status") == "ALARM" and event.get("inspection_result") != "no_issue_found"
    ]

def _fallback_assessment(events: list[dict]) -> dict: # It is deterministic safety fallback used when the local model or its output cannot be trusted

    statuses = {event["status"] for event in events}

    if _outstanding_alarms(events): # An alarm nobody has answered forces inspection-oriented guidance
        return {
            "priority": "immediate",
            "pattern": "persistent_acoustic_change",
            "queen_loss_compatible": True,
            "inspection_required": True,
            "action_codes": ["inspect_hive", "check_queen"],
        }

    # An alarm that was inspected and found sound is not routine either: the sound did
    # change, and a period that changed is watched rather than filed away.
    if "WATCH" in statuses or "ALARM" in statuses:
        return {
            "priority": "watch",
            "pattern": "developing_acoustic_change",
            "queen_loss_compatible": False,
            "inspection_required": False,
            "action_codes": ["record_again", "continue_monitoring"],
        }
    
    return {
        "priority": "routine",
        "pattern": "within_baseline",
        "queen_loss_compatible": False,
        "inspection_required": False,
        "action_codes": ["continue_monitoring"],
    }

def _validate_assessment(value: dict, events: list[dict]) -> dict: # It validates model output against strict whitelists and reinforces hard safety rules
    priority = value.get("priority") # It reads the model proposed operational priority
    actions = value.get("action_codes") # It reads the model proposed action list

    if priority not in ALLOWED_PRIORITIES: # It rejects any priority outside the predefined safe vocabulary
        # Naming the value is what turns a demo-day log line into a diagnosis: a small model
        # echoing "ALARM" back into this field reads very differently from one inventing a
        # word of its own, and only the first is worth waiting out.
        raise ValueError(f"Unsupported Foundry priority: {priority!r}")
    
    if not isinstance(actions, list) or not actions or any(action not in ALLOWED_ACTIONS for action in actions):
        raise ValueError("Unsupported Foundry action")

    boolean_fields = ("queen_loss_compatible", "inspection_required")
    if any(type(value.get(field)) is not bool for field in boolean_fields):
        # bool("false") is True in Python. Model output is external input, so accepting
        # truthy strings here can turn an explicitly negative answer into an inspection.
        raise ValueError("Foundry boolean fields must be JSON booleans")
    
    pattern = str(value.get("pattern", ""))
    if pattern not in ALLOWED_PATTERNS:
        logger.info("Model returned the pattern %r; using the one its priority implies", pattern)
        pattern = PATTERN_FOR_PRIORITY[priority]
    result = {
        "priority": priority,
        "pattern": pattern,
        "queen_loss_compatible": value["queen_loss_compatible"],
        "inspection_required": value["inspection_required"],
        "action_codes": list(dict.fromkeys(actions)),
    }

    if _outstanding_alarms(events): # an unanswered ALARM always overrides weaker model output
        # The pattern moves with the priority. An ALARM *is* a sustained run of anomalous
        # windows, so leaving the model's calmer wording would put "Acil" and "Normal
        # aralıkta" side by side on the same card.
        result.update(
            priority = "immediate",
            pattern = "persistent_acoustic_change",
            queen_loss_compatible = True,
            inspection_required = True,
        )

        for action in ("inspect_hive", "check_queen"):
            if action not in result["action_codes"]:
                result["action_codes"].append(action)

    elif any(event["status"] == "ALARM" for event in events) and PRIORITY_ORDER[result["priority"]] < PRIORITY_ORDER["watch"]:
        # Every alarm here was inspected and found sound, so nothing is outstanding — but
        # the model must not file the period as routine, because the sound did change.
        result["priority"] = "watch"
        result["pattern"] = PATTERN_FOR_PRIORITY["watch"]

    # The model chooses the operational priority; the product safety policy chooses what
    # that priority means. Keeping model-supplied actions independently allowed incoherent
    # combinations such as ROUTINE + record_again and WATCH + inspect_hive/check_queen.
    # Canonicalising after the ALARM override guarantees every surfaced field agrees.
    result.update(POLICY_FOR_PRIORITY[result["priority"]])

    return result

def _assessment_prompt(events: list[dict], knowledge: list[dict] | None = None) -> dict: # It builds a tightly constrained prompt containing events, allowed outputs, safety rules and local RAG passages
    return {
        "task": "Classify the operational response to acoustic hive events.",
        "events": events,
        "allowed_priority": sorted(ALLOWED_PRIORITIES),
        "allowed_pattern": sorted(ALLOWED_PATTERNS),
        "allowed_action_codes": sorted(ALLOWED_ACTIONS),
        "rules": [
            "ALARM is persistent acoustic change, not proof of queen death.",
            "ALARM requires inspect_hive and check_queen.",
            "WATCH requires continued monitoring or another recording.",
            "Wind or rain on an event lowers confidence in that record and is never evidence of queen loss; when a decisive record was taken in those conditions, prefer record_again.",
        ],
        # Ground the model with offline local knowledge uses an empty list when none is available
        "local_knowledge": knowledge or [],
        # Explicitly prevents the model from presenting acoustic signals as a medical or biological certainty
        "grounding_rule": "Use local_knowledge as operational guidance; never present acoustic output as a definitive diagnosis.",
        # Naming the list each field must be copied from, rather than describing its shape.
        # "short snake_case identifier" invited a model to write the event status into the
        # pattern, and a vague "one allowed priority" invited "ALARM" into the priority — a
        # measured failure, not a hypothetical one.
        "output_schema": {
            "priority": "copy exactly one value from allowed_priority; it is your decision, not an event status",
            "pattern": "copy exactly one value from allowed_pattern",
            "queen_loss_compatible": "boolean",
            "inspection_required": "boolean",
            "action_codes": "list of values copied from allowed_action_codes",
        },
    }

# Whether an endpoint accepted the optional parameters below. Remembered per endpoint so
# the probe costs one rejected request for the life of the process, not one per report.
_EXTRA_PARAMETER_SUPPORT: dict[str, bool] = {}

def _stall_timeout(default: float = 45) -> float: # How long the model may go silent before the run is treated as stalled rather than slow
    try:
        return max(float(os.getenv("WAGGLE_LLM_STALL_TIMEOUT", default)), 1)
    except ValueError:
        logger.warning("WAGGLE_LLM_STALL_TIMEOUT is not a number; using %s seconds", default)
        return default

def _blocking_chat(base_url: str, payload: dict) -> str: # It waits for the whole answer and returns the assistant text
    response = requests.post(
        f"{base_url}/chat/completions",
        json = payload,
        timeout = _llm_timeout(),
    )
    response.raise_for_status()

    return response.json()["choices"][0]["message"]["content"]

def _streamed_chat(base_url: str, payload: dict, on_progress = None) -> str:
    """Read the answer as it is generated and assemble it.

    A stalled model and a slow one are indistinguishable over a blocking request: both are
    silence until the timeout expires, so the only safe timeout was one long enough for the
    slowest legitimate run — three minutes of the panel showing a counter and knowing
    nothing. Streaming separates them. The read timeout applies between chunks, so silence
    is given up on in well under a minute while a model that is still emitting tokens is
    left alone, and the total budget is still enforced on top.
    """
    deadline = time.monotonic() + _llm_timeout()

    response = requests.post(
        f"{base_url}/chat/completions",
        json = payload,
        # (connect, read): the read half is the gap between chunks, not the whole answer.
        timeout = (10, _stall_timeout()),
        stream = True,
    )

    try:
        response.raise_for_status()

        pieces: list[str] = []

        # Decoded per line rather than through decode_unicode, which can split a multi-byte
        # character across chunk boundaries and corrupt Turkish prose. A newline byte cannot
        # occur inside a UTF-8 sequence, so a complete line is always safe to decode.
        for raw in response.iter_lines():
            line = raw.decode("utf-8", "replace")

            if time.monotonic() > deadline: # Emitting steadily but far too slowly to be useful
                raise requests.Timeout(f"The model exceeded its {_llm_timeout():.0f} second budget")

            if not line or not line.startswith("data:"):
                continue

            body = line[len("data:"):].strip()

            if body == "[DONE]":
                break

            try:
                chunk = json.loads(body)
            except json.JSONDecodeError: # A keep-alive or a comment frame, not an answer
                continue

            piece = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")

            if piece:
                pieces.append(piece)

                if on_progress is not None:
                    on_progress(sum(len(item) for item in pieces))
    finally:
        response.close()

    if not pieces: # A stream that closed without content is a failure, not an empty answer
        raise ValueError("The model streamed no content")

    return "".join(pieces)

def _chat_json(base_url: str, payload: dict, on_progress = None) -> str: # It asks for JSON, and for it token by token, where the endpoint supports both
    """Ask for the answer as a constrained JSON object, streamed.

    Two optional parameters travel together. response_format constrains generation to a
    valid object at the server instead of asking for one in prose and hoping — the two
    failures _extract_json exists to survive. stream makes the answer arrive token by
    token, which is what tells a stalled model from a slow one.

    They are probed as a pair because a client error names no parameter: an endpoint that
    rejects either is asked again without both, and remembered. One retry for the pair
    beats one retry each, and an OpenAI-compatible server old enough to reject one
    generally rejects the other. The negative is only recorded once the plain retry
    succeeds: a 400 raised by something else, a prompt too long for the context, must not
    be misread as "this server supports neither" for every later report.
    """
    if _EXTRA_PARAMETER_SUPPORT.get(base_url, True):
        try:
            return _streamed_chat(
                base_url,
                {**payload, "response_format": {"type": "json_object"}, "stream": True},
                on_progress,
            )
        except requests.HTTPError as error:
            status = getattr(error.response, "status_code", None)

            if status is None or not 400 <= status < 500:
                raise

            content = _blocking_chat(base_url, payload)

            logger.info("%s rejected JSON mode or streaming (HTTP %s); falling back to one blocking request", base_url, status)
            _EXTRA_PARAMETER_SUPPORT[base_url] = False

            return content

    return _blocking_chat(base_url, payload)

def assess_with_foundry(events: list[dict], alias: str = "phi-3.5-mini", knowledge: list[dict] | None = None, on_progress = None) -> dict:
    base_url, model_id = _foundry_connection(alias)

    prompt = _assessment_prompt(events, knowledge)

    payload = { # It asks the local model for the assessment object
        "model": model_id,
        "messages": [
            {
                # Measured against both local models with the real prompt: phi-3.5-mini
                # answers correctly either way, but the longer wording — specifically
                # the "do not write prose or markdown" clause — sends qwen2.5-1.5b into
                # token soup that never closes its JSON. That is why the cross-check had
                # never once succeeded. Say what to do, not what to avoid.
                "role": "system",
                "content": "Answer with one JSON object only.",
            },
            {"role": "user", "content": json.dumps(prompt)},
        ],
        # Makes the assessment as deterministic and repeatable as possible
        "temperature": 0,
        # The limit output size because only one compact JSON object is expected
        "max_tokens": 420,
    }

    content = _chat_json(base_url, payload, on_progress)

    try:
        return _validate_assessment(_extract_json(content), events)
    except ValueError as first_error:
        # Small local models occasionally truncate a key, uppercase an enum, or append
        # prose despite JSON mode. One bounded repair attempt recovers transient formatting
        # errors without turning reporting into an unbounded retry loop. The second answer
        # still passes the exact same strict validator; no malformed value is repaired in code.
        logger.info("Foundry output was invalid (%s); requesting one corrected JSON object", first_error)
        repair_payload = {
            **payload,
            "messages": [
                *payload["messages"],
                {"role": "assistant", "content": content[:2000]},
                {
                    "role": "user",
                    "content": (
                        "Rewrite your answer as one valid JSON object with exactly these keys: "
                        "priority, pattern, queen_loss_compatible, inspection_required, action_codes. "
                        "Copy priority, pattern and action values exactly from the allowed lists. "
                        "Use JSON true or false for both boolean fields. Add no explanation."
                    ),
                },
            ],
            "max_tokens": 220,
        }
        corrected = _chat_json(base_url, repair_payload)

        try:
            return _validate_assessment(_extract_json(corrected), events)
        except ValueError as second_error:
            raise ValueError(
                f"Foundry output remained invalid after one repair attempt: {second_error}"
            ) from second_error

async def assess_with_agent_framework( # The alternative path that performs the priority assessment through Microsoft Agent Framework
    events: list[dict],
    alias: str = "phi-3.5-mini",
    knowledge: list[dict] | None = None,
    language: Language = "tr",
) -> dict:
    """
    
    It runs the constrained assessment through Microsoft Agent Framework
    
    """

    from agent_framework import Agent

    # Foundry Local serves /v1/chat/completions, so the Chat Completions client is
    # required here. OpenAIChatClient targets the Responses API and would fail.
    from agent_framework.openai import OpenAIChatCompletionClient

    base_url, model_id = _foundry_connection(alias)

    # Tools, rather than one pre-filled prompt: the agent decides what it still needs to
    # know. Every tool is a pure read over data the panel already holds — none of them can
    # change anything, so a confused model can waste a turn but never cause harm.
    tool_calls: list[str] = []

    def look_up_guidance(query: str) -> str:
        """Search the beekeeper's reviewed local guidance notes for a topic.

        Args:
            query: What to look for, such as "swarming" or "queen loss" or "varroa".
        """
        tool_calls.append(f"look_up_guidance({query!r})")
        # The passages the tool returns are the ones the report will rest on, so they come
        # back in the language the report is being written in. Pinning them to English meant
        # a Turkish report was grounded in text it could not quote.
        found = search_guidance(query, language, limit=3)
        return json.dumps(found) if found else "No guidance matches that topic."

    def hive_history(hive_id: str) -> str:
        """Return how one hive behaved across the period being assessed.

        Args:
            hive_id: The hive identifier, for example "H3".
        """
        tool_calls.append(f"hive_history({hive_id!r})")
        own = [event for event in events if event.get("hive_id") == hive_id]
        if not own:
            return f"No records for {hive_id} in this period."
        fractions = [float(event.get("anomaly_fraction") or 0) for event in own]
        runs = [int(event.get("consecutive_anomalies") or 0) for event in own]
        return json.dumps({
            "hive_id": hive_id,
            "records": len(own),
            "statuses": sorted({str(event.get("status", "")).upper() for event in own}),
            "highest_anomaly_fraction": round(max(fractions), 3),
            "mean_anomaly_fraction": round(sum(fractions) / len(fractions), 3),
            "longest_anomalous_run": max(runs),
        })

    def period_overview() -> str:
        """Return the shape of the whole period: which hives, how loud, how sustained."""
        tool_calls.append("period_overview()")
        return json.dumps(event_profile(events), default=sorted)

    tools = [look_up_guidance, hive_history, period_overview] if _model_supports_tools(alias) else []
    if not tools:
        logger.info("%s cannot call tools; the agent runs on the pre-filled prompt alone", alias)

    client = OpenAIChatCompletionClient(
        model = model_id,
        base_url = base_url,
        api_key = "foundry-local",
    )

    agent = Agent( # It creates a constrained offline reporting agent backed by the local Foundry model
        client = client,
        name = "WaggleWeeklyReportAgent",
        instructions = (
            "You are Waggle's offline hive monitoring report agent. "
            "Use only the supplied events, the rules, and what the tools return. "
            + (
                # Offered, not compelled. Forcing the first call was tried and made things
                # worse: a small local model that is ordered to use a tool spends its
                # budget on the call and loses the answer it was asked for.
                "You may call period_overview, hive_history and look_up_guidance before "
                "deciding; call them when the events alone do not settle the question. "
                if tools else ""
            ) +
            "Never present an acoustic alarm as proof of queen loss. "
            "Finish by returning exactly one uppercase token: ROUTINE, WATCH or IMMEDIATE."
        ),
        tools = tools,
    )

    prompt = {
        "task": "Choose the operational priority for these acoustic hive events",
        "events": events,
        "local_knowledge": knowledge or [],
        "rules": [
            "ALARM requires IMMEDIATE",
            "WATCH normally requires WATCH",
            "NORMAL without persistent change requires ROUTINE",
            "Acoustic output is never a definitive diagnosis",
        ],
        "allowed_output": ["ROUTINE", "WATCH", "IMMEDIATE"],
    }

    try:
        response = await agent.run(json.dumps(prompt))
    finally:
        # asyncio.run() closes this loop on its way out, and the HTTP pool underneath the
        # client is released by a finaliser that runs after that — so a weekly run that
        # succeeded still printed "RuntimeError: Event loop is closed" and a page of
        # traceback over the report it had just written. Closing the pool here returns it
        # inside the loop that opened it. Reached through getattr because it is the SDK's
        # own client, not ours, and a report must not fail over how it is spelled.
        inner = getattr(client, "client", None)
        if inner is not None:
            await inner.close()
    if tool_calls:
        logger.info("Agent Framework used its tools: %s", ", ".join(tool_calls))

    match = re.search(r"\b(ROUTINE|WATCH|IMMEDIATE)\b", response.text.upper())

    if not match:
        # The text is the only evidence of why the run failed, and losing it turns every
        # agent problem into the same unhelpful sentence.
        logger.warning("Agent Framework returned no allowed priority; response was: %s", response.text[:400])
        raise ValueError("Agent Framework response did not contain an allowed priority")
    
    priority = match.group(1).lower()

    assessments = {
        "routine": {
            "priority": "routine",
            "pattern": "within_baseline",
            "queen_loss_compatible": False,
            "inspection_required": False,
            "action_codes": ["continue_monitoring"],
        },

        "watch": {
            "priority": "watch",
            "pattern": "developing_acoustic_change",
            "queen_loss_compatible": False,
            "inspection_required": False,
            "action_codes": ["record_again", "continue_monitoring"],
        },

        "immediate": {
            "priority": "immediate",
            "pattern": "persistent_acoustic_change",
            "queen_loss_compatible": True,
            "inspection_required": True,
            "action_codes": ["inspect_hive", "check_queen"],
        },
    }
    return _validate_assessment(assessments[priority], events)

def recording_conditions(events: list[dict]) -> dict | None:
    """The weather behind the decisions in this period, when it was observed and it matters.

    Only WATCH and ALARM records are weighed: weather is here to question a decision a
    beekeeper would act on, and a calm-day NORMAL record raises no question. Returns None
    when weather was never stamped or when the conditions were good — a report that
    announces the weather was fine has spent a sentence saying nothing.
    """
    def adverse(event: dict) -> bool:
        windy = event.get("wind_kmh") is not None and float(event["wind_kmh"]) >= WIND_NOISE_KMH
        wet = event.get("weather_code") is not None and int(event["weather_code"]) >= PRECIPITATION_CODE
        return windy or wet

    deciding = [event for event in events if str(event.get("status", "")).upper() in ("WATCH", "ALARM")]
    affected = [event for event in deciding if adverse(event)]
    if not affected:
        return None
    winds = [float(event["wind_kmh"]) for event in affected if event.get("wind_kmh") is not None]
    return {
        "hives": list(dict.fromkeys(event["hive_id"] for event in affected)),
        "record_count": len(affected),
        "wind": any(wind >= WIND_NOISE_KMH for wind in winds),
        "peak_wind_kmh": round(max(winds, default=0.0)),
        "precipitation": any(
            event.get("weather_code") is not None and int(event["weather_code"]) >= PRECIPITATION_CODE
            for event in affected
        ),
    }


def render_report(events: list[dict], assessment: dict, language: Language, generator: str) -> ReportDraft: # It converts structured assessment data into a safe human readable Turkish or English report
    hive_ids = list(dict.fromkeys(event["hive_id"] for event in events)) # Collect unique hive IDs while preserving event order

    alarm_hives = list(dict.fromkeys(event["hive_id"] for event in events if event["status"] == "ALARM")) # Identify hives requiring immediate inspection language

    watch_hives = list(dict.fromkeys(event["hive_id"] for event in events if event["status"] == "WATCH")) # Identify hives with developing acoustic change

    normal_hives = list(dict.fromkeys(event["hive_id"] for event in events if event["status"] == "NORMAL")) # It identifies hives remaining within their learned baseline

    status_counts = {status: sum(event["status"] == status for event in events) for status in ("NORMAL", "WATCH", "ALARM")}
    fractions = [float(event.get("anomaly_fraction", 0)) for event in events]
    average_fraction = sum(fractions) / len(fractions) if fractions else 0
    maximum_fraction = max(fractions, default=0)
    # Absent on events recorded before the acoustic model reported depth, so the sentence
    # about it is written only when there is something to write.
    severities = [float(event["anomaly_severity"]) for event in events if event.get("anomaly_severity") is not None]

    confirmed_hives = list(dict.fromkeys(event["hive_id"] for event in events if event.get("inspection_result") == "issue_confirmed"))
    cleared_hives = list(dict.fromkeys(event["hive_id"] for event in events if event.get("inspection_result") == "no_issue_found"))
    uncertain_hives = list(dict.fromkeys(event["hive_id"] for event in events if event.get("inspection_result") == "uncertain"))
    # Weather only ever weakens an acoustic decision. It is never evidence for one, so the
    # clause it produces reads as a caveat and the step it adds is another measurement,
    # appended after the inspection rather than in place of it.
    conditions = recording_conditions(events)
    condition_action = None

    if language == "tr": # Render Turkish summary sentences and Turkish recommendation texts here
        parts = [f"Bu değerlendirme {len(hive_ids)} kovandan gelen {len(events)} akustik olayı kapsıyor. Kayıtların {status_counts['NORMAL']} tanesi normal, {status_counts['WATCH']} tanesi izleme ve {status_counts['ALARM']} tanesi alarm durumunda. Dönem genelindeki ortalama aykırı pencere oranı %{average_fraction * 100:.0f}, en yüksek oran ise %{maximum_fraction * 100:.0f} olarak ölçüldü."]
        if severities:
            parts.append(
                f"Sapma görülen kayıtlarda sapmanın şiddeti ortalama %{sum(severities) / len(severities) * 100:.0f}, en yüksek %{max(severities) * 100:.0f} ölçüldü; bu, kaç kaydın sapmış olduğundan ayrı olarak ne kadar saptığını gösterir."
            )
        if normal_hives:
            parts.append(f"{', '.join(normal_hives)} normal akustik profili içinde kaldı")
        if watch_hives:
            parts.append(f"{', '.join(watch_hives)} için gelişen akustik değişim izleniyor")
        if alarm_hives:
            parts.append(
                f"{', '.join(alarm_hives)} için kraliçe kaybıyla uyumlu olabilecek kalıcı akustik değişim algılandı, bu kesin tanı değildir"
            )
        if confirmed_hives:
            parts.append(f"{', '.join(confirmed_hives)} için saha kontrolünde sorun doğrulandı")
        if cleared_hives:
            parts.append(f"{', '.join(cleared_hives)} için saha kontrolünde belirgin sorun görülmedi")
        if uncertain_hives:
            parts.append(f"{', '.join(uncertain_hives)} için saha kontrolü belirsiz kaldı")
        if conditions:
            detail = []
            if conditions["wind"]:
                detail.append(f"rüzgâr {conditions['peak_wind_kmh']} km/s'ye çıktı")
            if conditions["precipitation"]:
                detail.append("yağış vardı")
            parts.append(
                f"{', '.join(conditions['hives'])} için karar veren kayıtların {conditions['record_count']} tanesi "
                f"ölçüm koşulunun şüpheli olduğu bir anda alındı ({' ve '.join(detail)}); rüzgâr ve yağmur mikrofona "
                "kendi sesini bindirir, bu yüzden aykırılık oranı olduğundan yüksek çıkmış olabilir"
            )
            condition_action = "Ölçümü sakin ve yağışsız bir havada tekrarlayın; rüzgârlı kayıt aykırılık oranını tek başına yükseltebilir"
        actions = {
            "continue_monitoring": "Rutin akustik izlemeye devam edin",
            "record_again": "Yeni bir ses kaydı alın ve değişimin sürüp sürmediğini kontrol edin",
            "inspect_hive": "Alarm veren kovanı fiziksel olarak kontrol edin",
            "check_queen": "Kraliçenin varlığını ve koloni durumunu doğrulayın",
        }

    else: # English versions are here
        # English marks the plural and Turkish does not, so the shared template read
        # "1 acoustic events from 1 hives" on the reports a single hive most often produces.
        events_noun = "event" if len(events) == 1 else "events"
        hives_noun = "hive" if len(hive_ids) == 1 else "hives"
        parts = [f"This assessment covers {len(events)} acoustic {events_noun} from {len(hive_ids)} {hives_noun}. The period contains {status_counts['NORMAL']} normal, {status_counts['WATCH']} watch, and {status_counts['ALARM']} alarm records. The mean anomalous-window ratio was {average_fraction * 100:.0f}%, with a maximum of {maximum_fraction * 100:.0f}%."]
        if severities:
            parts.append(
                f"Across the deviating recordings the severity averaged {sum(severities) / len(severities) * 100:.0f}% and peaked at {max(severities) * 100:.0f}%, which says how far the sound moved rather than how often it moved."
            )
        if normal_hives:
            parts.append(f"{', '.join(normal_hives)} remained within the learned acoustic baseline")

        if watch_hives:
            parts.append(f"A developing acoustic change is being monitored for {', '.join(watch_hives)}")

        if alarm_hives:
            parts.append(
                f"Persistent acoustic change compatible with possible queen loss was detected for {', '.join(alarm_hives)}; this is not a definitive diagnosis"
            )
        if confirmed_hives:
            parts.append(f"A field inspection confirmed an issue for {', '.join(confirmed_hives)}")
        if cleared_hives:
            parts.append(f"No evident issue was found during field inspection for {', '.join(cleared_hives)}")
        if uncertain_hives:
            parts.append(f"The field inspection remained inconclusive for {', '.join(uncertain_hives)}")
        if conditions:
            detail = []
            if conditions["wind"]:
                detail.append(f"wind reached {conditions['peak_wind_kmh']} km/h")
            if conditions["precipitation"]:
                detail.append("there was precipitation")
            parts.append(
                f"{conditions['record_count']} of the records deciding {', '.join(conditions['hives'])} were taken in "
                f"questionable measurement conditions ({' and '.join(detail)}); wind and rain lay their own sound over "
                "the microphone, so the anomaly ratio may read higher than the colony warrants"
            )
            condition_action = "Repeat the recording in calm, dry weather; wind alone can raise the anomaly ratio"

        actions = {
            "continue_monitoring": "Continue routine acoustic monitoring",
            "record_again": "Capture another recording and confirm whether the change persists",
            "inspect_hive": "Perform a physical inspection of the hive that raised the alarm",
            "check_queen": "Verify queen presence and overall colony condition",
        }

    return ReportDraft( # Packages the rendered text and metadata into one immutable ReportDraft object
        # Each clause is a sentence, so each one is closed. Joining them on a bare space
        # ran them together — "H1 normal akustik profili içinde kaldı H2 için gelişen
        # akustik değişim izleniyor" — in the text a beekeeper actually reads whenever the
        # model's prose is rejected, which is the common case rather than the rare one.
        summary = " ".join(part if part.endswith(".") else part + "." for part in parts),
        recommendations = [actions[code] for code in assessment["action_codes"]] + ([condition_action] if condition_action else []),
        hive_ids = hive_ids,
        language = language,
        generator = generator,
        assessment = assessment,
    )

MAX_SUMMARY_CHARACTERS = 700 # An upper bound on model prose so a runaway generation cannot fill the report card
# A summary shorter than this carries less than the deterministic template it would replace.
MIN_SUMMARY_CHARACTERS = 140
MAX_RECOMMENDATION_CHARACTERS = 180

# Vocabulary that only appears when the model copies its own instructions or leaks a
# serialisation artefact into the prose.
PROMPT_LEAK_PATTERNS = [
    r"\b(instruction|allowed_output|local_knowledge|event_count|status_counts|action_codes|hive_ids|adverse_recording_conditions|peak_wind_kmh)\b",
    r"\b(json|dict|list|str|bool)\b",
    r"'(dict|str|list|int|bool|json|none)\b",
    r"\b(olgu|olgular|talimat|anahtar kelime)\b",
    r"\bkesinlik iddia\w*\s+etme",
    r"\bdo not claim\b",
]
# A routine period yields a single action code, so one recommendation must stay valid.
RECOMMENDATION_RANGE = (1, 5)

# Phrasings that assert a diagnosis or certainty. The panel promises early warning, never
# a verdict, so prose containing any of these is rejected in favour of the template text.
BANNED_NARRATIVE_PATTERNS = {
    "tr": [
        # "kraliçe kaybıyla uyumlu olabilir" is the hedged wording the prompt and the
        # knowledge base both use, so a hedging continuation cancels the match.
        r"kraliçe\w*\s+(öl\w+|kayıp|kayb\w+|yok|gitmiş)(?!\w*\s+(uyumlu|olabil|olası|şüphe))",
        r"tanı\s+(kondu|konuldu)",
        r"teşhis\s+(kondu|konuldu|edildi)",
        r"hastalık\w*\s+\w*\s*(tespit\s+edil|saptan|doğruland)",
        r"koloni\w*\s+(öldü|ölmüş)",
    ],
    "en": [
        r"\bqueen\w*\s+(is|has|was|had)?\s*(dead|died|lost|missing|gone)",
        r"\bdiagnos(ed|ing)\b",
        r"\bdisease\s+\w*\s*(is\s+)?(present|detected|confirmed)",
        r"\bcolony\s+(is|has)?\s*(dead|died)",
    ],
}

# A report that raises the possibility of queen loss must carry a hedge. Requiring the
# disclaimer is a stronger guarantee than trying to enumerate every way of denying it.
REQUIRED_HEDGE_MARKERS = {
    "tr": ("olabil", "olasi", "erken uyari", "kesin degil", "kesin tani degil", "kesin teshis degil", "suphe"),
    "en": ("possible", "possibly", "may ", "might ", "early warning", "not a definitive", "not a diagnosis", "suggest"),
}

def _fold(text: str) -> str: # Turkish dotted and dotless i survive neither casefold nor a naive lower(), so folding is explicit
    # NFKD never decomposes ı (U+0131), so it is mapped explicitly; every marker is
    # written with a plain i.
    lowered = text.replace("İ", "i").replace("I", "i").casefold().replace("ı", "i")
    stripped = unicodedata.normalize("NFKD", lowered)
    return "".join(character for character in stripped if not unicodedata.combining(character))

def _narrative_enabled() -> bool:
    """Whether the model phrases the report, rather than only deciding it. Off by default.

    It used to default on, which was safe only by accident: the example named hives the
    period did not hold, so the unknown-hive check threw the prose away before a beekeeper
    saw it. With the example built from the period's own hives that rejection is gone, and
    what phi-3.5-mini actually writes reaches the report. Measured on this machine, it
    writes Turkish that passes every guard and still says nothing: "H1 kovanı dönem boyunca
    91'un alt sınırına ulaştı, bu da kesin tanı değildir." The other two cached models do
    no better — gemma-4-e2b-it fails inside the Foundry runtime, qwen2.5-1.5b returns no
    JSON at all.

    So the prose stays off until a local model can be trusted with it, and the template
    writes the report: it is bilingual, it states the same measurements, and it is correct.
    None of this touches the assessment — the model still decides priority, pattern and
    actions, which is the part it is good at and the part the whitelists can check. Set
    WAGGLE_LLM_NARRATIVE=1 to weigh a new model against the template.
    """
    return os.getenv("WAGGLE_LLM_NARRATIVE", "0") != "0"

def _narrative_facts(events: list[dict], assessment: dict, language: Language) -> dict: # The closed set of facts the narrative may draw on
    def hives_with(predicate) -> list[str]:
        return list(dict.fromkeys(event["hive_id"] for event in events if predicate(event)))

    fractions = [float(event.get("anomaly_fraction", 0)) for event in events]
    severities = [float(event["anomaly_severity"]) for event in events if event.get("anomaly_severity") is not None]

    facts = {
        "language": language,
        "event_count": len(events),
        "status_counts": {status: sum(event["status"] == status for event in events) for status in ("NORMAL", "WATCH", "ALARM")},
        "average_anomaly_percent": round((sum(fractions) / len(fractions) if fractions else 0) * 100),
        "peak_anomaly_percent": round(max(fractions, default=0) * 100),
        "normal_hives": hives_with(lambda event: event["status"] == "NORMAL"),
        "watch_hives": hives_with(lambda event: event["status"] == "WATCH"),
        "alarm_hives": hives_with(lambda event: event["status"] == "ALARM"),
        "confirmed_hives": hives_with(lambda event: event.get("inspection_result") == "issue_confirmed"),
        "cleared_hives": hives_with(lambda event: event.get("inspection_result") == "no_issue_found"),
        "uncertain_hives": hives_with(lambda event: event.get("inspection_result") == "uncertain"),
        "priority": assessment["priority"],
        "inspection_required": assessment["inspection_required"],
        "action_codes": assessment["action_codes"],
    }

    # Given to the model only when it was measured. A null here reads to a small model as a
    # number it may reason about, and the safest thing to say about an unmeasured depth is
    # nothing at all.
    if severities:
        facts["average_severity_percent"] = round(sum(severities) / len(severities) * 100)
        facts["peak_severity_percent"] = round(max(severities) * 100)

    # Given only when weather was actually observed and actually poor. Absent otherwise,
    # for the same reason severity is: a null invites a small model to reason about a
    # measurement nobody took.
    conditions = recording_conditions(events)
    if conditions:
        facts["adverse_recording_conditions"] = conditions

    return facts

def _validate_narrative(payload: dict, allowed_hive_ids: set[str], language: Language, hedge_required: bool = False, example_summary: str = "") -> tuple[str, list[str]]: # It rejects prose that is malformed, invents hives, asserts a diagnosis or simply hands back the example it was shown
    if not isinstance(payload, dict):
        raise ValueError("Narrative payload is not an object")

    summary = payload.get("summary")
    recommendations = payload.get("recommendations")

    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Narrative summary is missing")

    if not isinstance(recommendations, list) or not all(isinstance(item, str) and item.strip() for item in recommendations):
        raise ValueError("Narrative recommendations are malformed")

    summary = " ".join(summary.split())
    recommendations = [" ".join(item.split()) for item in recommendations]

    if len(summary) > MAX_SUMMARY_CHARACTERS:
        raise ValueError("Narrative summary is too long")

    if len(summary) < MIN_SUMMARY_CHARACTERS:
        raise ValueError("Narrative summary is too thin to replace the template")

    minimum, maximum = RECOMMENDATION_RANGE
    if not minimum <= len(recommendations) <= maximum:
        raise ValueError("Narrative recommendation count is out of range")

    if any(len(item) > MAX_RECOMMENDATION_CHARACTERS for item in recommendations):
        raise ValueError("A narrative recommendation is too long")

    # Each string is scanned on its own so a banned phrase cannot be assembled across the
    # boundary between the summary and a recommendation.
    named_hives: set[str] = set()

    for text in (summary, *recommendations):
        if re.search(r"https?://|[#*`|]", text):
            raise ValueError("Narrative contains markup or a link")

        mentioned = {token.upper() for token in re.findall(r"\bH\d+\b", text, flags=re.IGNORECASE)}
        if not mentioned <= allowed_hive_ids:
            raise ValueError(f"Narrative mentions unknown hives: {sorted(mentioned - allowed_hive_ids)}")

        named_hives |= mentioned

        for pattern in PROMPT_LEAK_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                raise ValueError(f"Narrative leaks its own prompt: {pattern}")

        for pattern in BANNED_NARRATIVE_PATTERNS[language]:
            if re.search(pattern, text, flags=re.IGNORECASE):
                raise ValueError(f"Narrative asserts a diagnosis: {pattern}")

    # A report that names no hive is less useful than the template it would replace.
    if allowed_hive_ids and not named_hives:
        raise ValueError("Narrative names no hive")

    if hedge_required and not any(marker in _fold(summary) for marker in REQUIRED_HEDGE_MARKERS[language]):
        raise ValueError("Narrative raises queen loss without a hedge")

    # The example exists to teach the shape and the hedging, and a small model will
    # sometimes hand it straight back instead of writing about the events. Measured on a
    # real run: phi-3.5-mini returned the Turkish example word for word. Nothing else in
    # this function can catch that, because the example is deliberately well formed, names
    # real hives and hedges correctly. On a period that happens to resemble it the copy
    # reads as a correct report; on any other period it describes hives doing something
    # they are not.
    if example_summary and _collapsed(summary) == _collapsed(example_summary):
        raise ValueError("Narrative repeats the example it was shown")

    return summary, recommendations


def _collapsed(text: str) -> str:
    """Whitespace, case and Turkish diacritics removed, so a copy hides behind none of them.

    casefold() alone is not enough here: "kovanı".upper() is "KOVANI", which casefolds to
    "kovani" and no longer matches the dotless original. _fold already settles that, and
    folding the diacritics too only makes an evasion harder — prose that matches the
    example this closely is the example.
    """
    return " ".join(_fold(text).split())

def _narrative_example(events: list[dict], facts: dict, language: Language) -> str:
    """The shape to answer in, written about this period's own hives.

    The example used to name H1, H2 and H3 literally, and a small model copies the
    identifiers it is shown. Measured on phi-3.5-mini, a period holding only H1 and H2 had
    H3 leak into the answer on four runs out of four, and the unknown-hive check rejected
    every one. Any period that does not happen to cover all three of the example's hives
    was affected, which includes every single-hive panel and every week one hive is quiet:
    the template was not the fallback there, it was the only outcome the panel could reach.

    Naming this period's own hives removes what was being copied. It also makes a copied
    clause harmless instead of wrong: the roles below are read from the same facts the
    report rests on, so the example states only what the period actually holds. A model
    that hands the whole example back is still caught by the example-copy guard.
    """
    ordered = list(dict.fromkeys(event["hive_id"] for event in events if event.get("hive_id")))
    normal = next(iter(facts.get("normal_hives") or []), None)
    watch = next(iter(facts.get("watch_hives") or []), None)
    alarm = next(iter(facts.get("alarm_hives") or []), None)

    clauses: list[str] = []

    if language == "tr":
        if normal:
            clauses.append(f"{normal} kovanı dönem boyunca normal aralıkta kaldı.")
        if watch:
            clauses.append(f"{watch} için gelişen bir akustik değişim izleniyor.")
        if alarm:
            clauses.append(
                f"{alarm} kovanında kalıcı bir değişim ölçüldü; bu kraliçe kaybıyla uyumlu "
                "olabilir, tek başına kesin tanı değildir."
            )
        # Only reached when a status outside the three the panel records slips through, and
        # a shapeless example still has to teach the shape.
        if not clauses and ordered:
            clauses.append(f"{ordered[0]} kovanının dönem kayıtları değerlendirildi.")
    else:
        if normal:
            clauses.append(f"{normal} stayed within its normal range for the period.")
        if watch:
            clauses.append(f"A developing acoustic change is being watched on {watch}.")
        if alarm:
            clauses.append(
                f"{alarm} recorded a persistent change, which may be compatible with queen "
                "loss and is not a diagnosis on its own."
            )
        if not clauses and ordered:
            clauses.append(f"The period's records for {ordered[0]} were reviewed.")

    # The recommendation is shown at the priority the period actually carries, so the
    # example cannot teach an inspection where none was decided.
    if alarm:
        recommendation = (
            f"{alarm} kovanını 24 saat içinde fiziksel olarak kontrol edin."
            if language == "tr" else f"Inspect {alarm} physically within 24 hours."
        )
    elif watch:
        recommendation = (
            f"{watch} için yeni bir ses kaydı alın."
            if language == "tr" else f"Record {watch} again."
        )
    elif ordered:
        recommendation = (
            f"{ordered[0]} için rutin takibe devam edin."
            if language == "tr" else f"Continue routine monitoring for {ordered[0]}."
        )
    else:
        recommendation = (
            "Rutin takibe devam edin." if language == "tr" else "Continue routine monitoring."
        )

    return json.dumps(
        {"summary": " ".join(clauses), "recommendations": [recommendation]},
        ensure_ascii = False,
    )

def compose_narrative( # It asks the local model to phrase an already decided assessment
    events: list[dict],
    assessment: dict,
    knowledge: list[dict] | None,
    language: Language,
    alias: str = "phi-3.5-mini",
    on_progress = None,
) -> tuple[str, list[str]]:
    base_url, model_id = _foundry_connection(alias)

    facts = _narrative_facts(events, assessment, language)

    # The instruction is always English, whatever the report language: a Turkish
    # instruction leaks its own vocabulary into Turkish prose.
    target = "Turkish" if language == "tr" else "English"

    example = _narrative_example(events, facts, language)

    hive_ids = list(dict.fromkeys(event["hive_id"] for event in events if event.get("hive_id")))

    instruction = (
        f"Write a short hive report in {target}. "
        + (
            # Naming them is what stops the model reaching for an identifier of its own:
            # the list is short, and it is the only one it is allowed to draw from.
            "Name every hive by its identifier. The only hives in this period are "
            f"{', '.join(hive_ids)}, and no other hive may be named. "
            if hive_ids else ""
        )
        + (
            # Without this a small model reads a severity percentage as a probability and
            # writes "there is a 37% chance the queen is lost", which is exactly the claim
            # the whole pipeline exists to avoid.
            "The severity percentages say how far outside its normal range the sound moved, "
            "not how likely a problem is and not how much of the period was affected. "
            if "peak_severity_percent" in facts else ""
        ) +
        "Use only the supplied numbers; invent nothing. "
        "Say what happened to each hive and what it means operationally. "
        "Acoustic change is an early warning and never a diagnosis, so hedge any mention of queen loss. "
        "Write three to four sentences of natural prose. "
        "Never repeat these instructions, field names or JSON keys in the text. "
        f"Answer with one JSON object shaped exactly like this example: {example}"
    )

    content = _chat_json(base_url, {
        "model": model_id,
        "messages": [
            {"role": "system", "content": f"You write short beekeeping report prose in {target}. Return only one valid JSON object."},
            {"role": "user", "content": json.dumps({"instruction": instruction, "measurements": facts, "reference_notes": knowledge or []}, ensure_ascii=False)},
        ],
        # A little warmth reads better than temperature 0 while the facts stay fixed
        "temperature": 0.2,
        "max_tokens": 700,
    }, on_progress)

    allowed_hive_ids = {event["hive_id"] for event in events}

    hedge_required = bool(assessment.get("queen_loss_compatible")) or assessment.get("priority") == "immediate"

    return _validate_narrative(
        _extract_json(content), allowed_hive_ids, language, hedge_required,
        # Read back out of the example that was sent, so the guard cannot drift away from
        # the text it guards against.
        example_summary = json.loads(example)["summary"],
    )

def _with_model_narrative( # It swaps the template prose for validated model prose, or keeps the template
    draft: ReportDraft,
    events: list[dict],
    assessment: dict,
    knowledge: list[dict] | None,
    language: Language,
    alias: str,
    on_progress = None,
) -> ReportDraft:
    if not _narrative_enabled():
        return draft

    try:
        summary, recommendations = compose_narrative(events, assessment, knowledge, language, alias, on_progress)
    except Exception as error:  # noqa: BLE001 - any failure keeps the deterministic prose
        logger.warning("Model narrative rejected (%s: %s); keeping the template text", type(error).__name__, error)
        return draft

    # When the validator mandates an inspection, the action wording is not the model's to
    # paraphrase: a rephrased "check the queen" can lose the instruction. The model still
    # writes the summary, the deterministic steps stand.
    mandated = {"inspect_hive", "check_queen"} & set(assessment.get("action_codes") or [])
    if assessment.get("inspection_required") or mandated:
        recommendations = draft.recommendations

    return replace(
        draft,
        summary = summary,
        recommendations = recommendations,
        generator = f"{draft.generator}+llm-narrative",
    )

def generate_report(events: list[dict], language: Language, alias: str = "phi-3.5-mini", on_progress = None) -> ReportDraft:
    knowledge = retrieve_guidance(events, language, limit=4)

    try: # Asks the local model for the constrained operational assessment
        assessment = assess_with_foundry(events, alias, knowledge, on_progress)

        generator = f"foundry-local:{alias}"

    except (OSError, subprocess.SubprocessError, requests.RequestException, KeyError, ValueError, json.JSONDecodeError) as error:
        logger.warning("Foundry Local assessment failed (%s: %s); using the deterministic fallback", type(error).__name__, error)

        assessment = _fallback_assessment(events)

        generator = "safe-fallback"

    assessment["knowledge_ids"] = [item["id"] for item in knowledge] # Preserves the IDs of grounding passages for traceability or auditing

    draft = render_report(events, assessment, language, generator)

    if generator == "safe-fallback": # No model reached the assessment, so none is asked for the prose
        return draft

    return _with_model_narrative(draft, events, assessment, knowledge, language, alias, on_progress)

# Two local models, each strong where the other is weak: the small tool-capable one
# settles the priority in a couple of seconds, the larger one writes reliable JSON and
# readable Turkish. Asking both and keeping the more cautious answer means a single
# model's slip cannot quietly set the priority on its own.
PRIORITY_ORDER = {"routine": 0, "watch": 1, "immediate": 2}


def _cross_check_model() -> str:
    """Read the setting when it is needed, not when this module happens to be imported.

    Reading it at import time made the behaviour depend on import order: whichever module
    loaded the .env file first decided whether a second model would be called, and a test
    run that touched the panel first started reaching for a real model.
    """
    return os.getenv("WAGGLE_CROSS_CHECK_MODEL", "")


def _cross_check(events: list[dict], knowledge: list[dict], primary: dict, alias: str, language: Language = "tr") -> dict:
    """Ask a second local model and keep the more cautious of the two priorities.

    A cross-check that could fail the report would be worse than none, so every problem
    here leaves the primary assessment exactly as it was.
    """
    second = _cross_check_model()
    if not second or second == alias:
        return primary
    try:
        try:
            other = asyncio.run(assess_with_agent_framework(events, second, knowledge, language))
        except Exception:  # noqa: BLE001 - the framework may be absent or the model weak
            other = assess_with_foundry(events, second, knowledge)
    except Exception as error:  # noqa: BLE001 - a second opinion is a bonus, never a gate
        logger.warning("Cross-check with %s failed (%s); keeping the single assessment", second, error)
        return primary

    agreed = other["priority"] == primary["priority"]
    if agreed:
        logger.info("Cross-check: %s agrees (%s)", second, primary["priority"])
        primary["cross_check"] = {"model": second, "agreed": True, "priority": other["priority"]}
        return primary

    # They disagree, so the safer reading wins. Under-calling an alarm is the failure that
    # costs a colony; over-calling one costs an inspection.
    logger.warning("Cross-check: %s says %s, %s says %s — taking the more cautious",
                   alias, primary["priority"], second, other["priority"])
    chosen = primary if PRIORITY_ORDER[primary["priority"]] >= PRIORITY_ORDER[other["priority"]] else other
    chosen = _validate_assessment(dict(chosen), events)
    chosen["cross_check"] = {
        "model": second,
        "agreed": False,
        "priority": other["priority"],
        "resolved_to": chosen["priority"],
    }
    return chosen


def generate_agent_report(events: list[dict], language: Language, alias: str = "phi-3.5-mini", on_progress = None) -> ReportDraft: # The agent Framework variant of the weekly report pipeline
    """
    
    It generates a weekly report with Agent Framework and a deterministic fallback

    """

    knowledge = retrieve_guidance(events, language, limit=4)

    try:
        assessment = asyncio.run(assess_with_agent_framework(events, alias, knowledge, language))
        generator = f"agent-framework:foundry-local:{alias}"
    except Exception as error:  # noqa: BLE001 - ImportError on 3.9, SDK errors elsewhere
        # Losing the framework should not cost the model's judgement as well. The same
        # local model is reachable over plain HTTP, so try that before giving up on the
        # model layer entirely — the deterministic fallback is the last resort, not the
        # second one.
        if isinstance(error, ImportError):
            logger.warning("Agent Framework is not installed; falling back to the direct Foundry Local call")
        else:
            logger.warning("Agent Framework assessment failed (%s: %s); falling back to the direct Foundry Local call", type(error).__name__, error)
        try:
            assessment = assess_with_foundry(events, alias, knowledge, on_progress)
            generator = f"foundry-local:{alias}"
        except Exception as direct_error:  # noqa: BLE001 - the model itself may be down
            logger.warning("Foundry Local assessment also failed (%s: %s); using the deterministic fallback", type(direct_error).__name__, direct_error)
            assessment = _fallback_assessment(events)
            generator = "safe-fallback"

    if generator != "safe-fallback":
        assessment = _cross_check(events, knowledge, assessment, alias, language)
        # The generator string is the report's provenance record, and "two models looked
        # at this" belongs in it as much as which one wrote the text.
        cross = assessment.get("cross_check")
        if cross:
            generator += f"+{cross['model']}" + ("" if cross["agreed"] else "(disagreed)")

    assessment["knowledge_ids"] = [item["id"] for item in knowledge]

    draft = render_report(events, assessment, language, generator)

    if generator == "safe-fallback": # No model reached the assessment, so none is asked for the prose
        return draft

    return _with_model_narrative(draft, events, assessment, knowledge, language, alias, on_progress)

def main() -> None: # Command line entry point for generating, displaying, and optionally posting a sample weekly report
    parser = argparse.ArgumentParser(description = __doc__)

    parser.add_argument("--language", choices=("tr", "en"), default="tr")

    parser.add_argument("--model", default="phi-3.5-mini")

    parser.add_argument("--panel-url", default="http://127.0.0.1:8000/api/reports")

    parser.add_argument("--device-key", default = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo"))

    parser.add_argument("--no-post", action = "store_true")

    args = parser.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond = 0)

    events = [
        {"hive_id": "H1", "status": "NORMAL", "anomaly_fraction": .08, "consecutive_anomalies": 0},
        {"hive_id": "H2", "status": "WATCH", "anomaly_fraction": .66, "consecutive_anomalies": 5},
        {"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 1.0, "consecutive_anomalies": 30},
    ]

    report = generate_report(events, args.language, args.model) # It generates the report using the selected language and local model alias

    payload = {
        "period_start": (now - timedelta(days=7)).isoformat(),
        "period_end": now.isoformat(),
        "summary": report.summary,
        "recommendations": report.recommendations,
        "hive_ids": report.hive_ids,
        "language": report.language,
        "generator": report.generator,
        "grounding_sources": report.assessment.get("knowledge_ids", []),
    }

    print( # It prints a readable local copy, including the internal assessment for inspection and debugging
        json.dumps(
            {**payload, "assessment": report.assessment},
            ensure_ascii = False,
            indent = 2,
        )
    )
                     
    if not args.no_post: # Skip network persistence when --no-post is enabled
        response = requests.post(
            args.panel_url,
            json = payload,
            headers = {"X-Device-Key": args.device_key},
            timeout = 10,
        )

        response.raise_for_status() # It raises an exception for HTTP failures instead of silently continuing

        print(f"report_id = {response.json()['id']}")

if __name__ == "__main__":
    main()
