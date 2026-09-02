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
import logging # It records why an optional model path degraded to the deterministic fallback
import os
import re

import subprocess # It executes Foundry CLI commands such as model load and server restart
import unicodedata # It folds Turkish text so an uppercase hedge is still recognised

import requests

from brain.local_rag import retrieve_guidance

logger = logging.getLogger(__name__)

Language = Literal["tr", "en"]

ALLOWED_PRIORITIES = {"routine", "watch", "immediate"} # Whitelist of operational priority values the model is allowed to return
ALLOWED_ACTIONS = {"continue_monitoring", "record_again", "inspect_hive", "check_queen"} # Whitelist of actions that can appear in a validated assessment

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

def _run_foundry(*arguments: str) -> str: # It runs one Foundry CLI command and returns stdout check = True makes failures raise an exception
    result = subprocess.run( # It execute the requested Foundry command as a child process
        ["foundry", *arguments],
        check = True,
        text = True,
        capture_output = True,
    )
    return result.stdout # It return the CLI output so the caller can parse it

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
            return value

    raise ValueError("Foundry response did not contain a JSON object")

def _fallback_assessment(events: list[dict]) -> dict: # It is deterministic safety fallback used when the local model or its output cannot be trusted

    statuses = {event["status"] for event in events}

    if "ALARM" in statuses: # Any ALARM forces immediate inspection oriented guidance
        return {
            "priority": "immediate",
            "pattern": "persistent_acoustic_change",
            "queen_loss_compatible": True,
            "inspection_required": True,
            "action_codes": ["inspect_hive", "check_queen"],
        }

    if "WATCH" in statuses: # WATCH requests followed up recording and continued monitoring
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
        raise ValueError("Unsupported Foundry priority")
    
    if not isinstance(actions, list) or not actions or any(action not in ALLOWED_ACTIONS for action in actions):
        raise ValueError("Unsupported Foundry action")
    
    result = {
        "priority": priority,
        "pattern": str(value.get("pattern", "unknown")),
        "queen_loss_compatible": bool(value.get("queen_loss_compatible")),
        "inspection_required": bool(value.get("inspection_required")),
        "action_codes": list(dict.fromkeys(actions)),
    }

    if any(event["status"] == "ALARM" for event in events): # an ALARM always overrides weaker model output
        result.update(
            priority = "immediate",
            queen_loss_compatible = True,
            inspection_required = True,
        )

        for action in ("inspect_hive", "check_queen"):
            if action not in result["action_codes"]:
                result["action_codes"].append(action)

    return result

def _assessment_prompt(events: list[dict], knowledge: list[dict] | None = None) -> dict: # It builds a tightly constrained prompt containing events, allowed outputs, safety rules and local RAG passages
    return {
        "task": "Classify the operational response to acoustic hive events.",
        "events": events,
        "allowed_priority": sorted(ALLOWED_PRIORITIES),
        "allowed_action_codes": sorted(ALLOWED_ACTIONS),
        "rules": [
            "ALARM is persistent acoustic change, not proof of queen death.",
            "ALARM requires inspect_hive and check_queen.",
            "WATCH requires continued monitoring or another recording.",
        ],
        # Ground the model with offline local knowledge uses an empty list when none is available
        "local_knowledge": knowledge or [],
        # Explicitly prevents the model from presenting acoustic signals as a medical or biological certainty
        "grounding_rule": "Use local_knowledge as operational guidance; never present acoustic output as a definitive diagnosis.",
        "output_schema": {
            "priority": "one allowed priority",
            "pattern": "short snake_case identifier",
            "queen_loss_compatible": "boolean",
            "inspection_required": "boolean",
            "action_codes": "list of allowed action codes",
        },
    }

def assess_with_foundry(events: list[dict], alias: str = "phi-3.5-mini", knowledge: list[dict] | None = None) -> dict:
    base_url, model_id = _foundry_connection(alias)

    prompt = _assessment_prompt(events, knowledge)

    response = requests.post( # Persist the report by POSTing the payload to the panel API
        f"{base_url}/chat/completions",
        json = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only one valid JSON object. Do not write prose or markdown.",
                },
                {"role": "user", "content": json.dumps(prompt)},
            ],
            # Makes the assessment as deterministic and repeatable as possible
            "temperature": 0,
            # The limit output size because only one compact JSON object is expected
            "max_tokens": 420,
        },
        timeout = _llm_timeout(),
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]

    return _validate_assessment(_extract_json(content), events)

async def assess_with_agent_framework( # The alternative path that performs the priority assessment through Microsoft Agent Framework
    events: list[dict],
    alias: str = "phi-3.5-mini",
    knowledge: list[dict] | None = None,
) -> dict:
    """
    
    It runs the constrained assessment through Microsoft Agent Framework
    
    """

    from agent_framework import Agent

    # Foundry Local serves /v1/chat/completions, so the Chat Completions client is
    # required here. OpenAIChatClient targets the Responses API and would fail.
    from agent_framework.openai import OpenAIChatCompletionClient

    base_url, model_id = _foundry_connection(alias)

    agent = Agent( # It creates a constrained offline reporting agent backed by the local Foundry model
        client = OpenAIChatCompletionClient(
            model = model_id,
            base_url = base_url,
            api_key = "foundry-local",
        ),
        name = "WaggleWeeklyReportAgent",
        instructions = (
            "You are Waggle's offline hive monitoring report agent"
            "Use only the supplied events, rules and local knowledge"
            "Return exactly one uppercase token: ROUTINE, WATCH or IMMEDIATE"
            "Never present an acoustic alarm as proof of queen loss"
        ),
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

    response = await agent.run(json.dumps(prompt))

    match = re.search(r"\b(ROUTINE|WATCH|IMMEDIATE)\b", response.text.upper())

    if not match:
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

def render_report(events: list[dict], assessment: dict, language: Language, generator: str) -> ReportDraft: # It converts structured assessment data into a safe human readable Turkish or English report
    hive_ids = list(dict.fromkeys(event["hive_id"] for event in events)) # Collect unique hive IDs while preserving event order

    alarm_hives = list(dict.fromkeys(event["hive_id"] for event in events if event["status"] == "ALARM")) # Identify hives requiring immediate inspection language

    watch_hives = list(dict.fromkeys(event["hive_id"] for event in events if event["status"] == "WATCH")) # Identify hives with developing acoustic change

    normal_hives = list(dict.fromkeys(event["hive_id"] for event in events if event["status"] == "NORMAL")) # It identifies hives remaining within their learned baseline

    status_counts = {status: sum(event["status"] == status for event in events) for status in ("NORMAL", "WATCH", "ALARM")}
    fractions = [float(event.get("anomaly_fraction", 0)) for event in events]
    average_fraction = sum(fractions) / len(fractions) if fractions else 0
    maximum_fraction = max(fractions, default=0)

    confirmed_hives = list(dict.fromkeys(event["hive_id"] for event in events if event.get("inspection_result") == "issue_confirmed"))
    cleared_hives = list(dict.fromkeys(event["hive_id"] for event in events if event.get("inspection_result") == "no_issue_found"))
    uncertain_hives = list(dict.fromkeys(event["hive_id"] for event in events if event.get("inspection_result") == "uncertain"))

    if language == "tr": # Render Turkish summary sentences and Turkish recommendation texts here
        parts = [f"Bu değerlendirme {len(hive_ids)} kovandan gelen {len(events)} akustik olayı kapsıyor. Kayıtların {status_counts['NORMAL']} tanesi normal, {status_counts['WATCH']} tanesi izleme ve {status_counts['ALARM']} tanesi alarm durumunda. Dönem genelindeki ortalama aykırı pencere oranı %{average_fraction * 100:.0f}, en yüksek oran ise %{maximum_fraction * 100:.0f} olarak ölçüldü."]
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
        actions = {
            "continue_monitoring": "Rutin akustik izlemeye devam edin",
            "record_again": "Yeni bir ses kaydı alın ve değişimin sürüp sürmediğini kontrol edin",
            "inspect_hive": "Alarm veren kovanı fiziksel olarak kontrol edin",
            "check_queen": "Kraliçenin varlığını ve koloni durumunu doğrulayın",
        }

    else: # English versions are here
        parts = [f"This assessment covers {len(events)} acoustic events from {len(hive_ids)} hives. The period contains {status_counts['NORMAL']} normal, {status_counts['WATCH']} watch, and {status_counts['ALARM']} alarm records. The mean anomalous-window ratio was {average_fraction * 100:.0f}%, with a maximum of {maximum_fraction * 100:.0f}%."]
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

        actions = {
            "continue_monitoring": "Continue routine acoustic monitoring",
            "record_again": "Capture another recording and confirm whether the change persists",
            "inspect_hive": "Perform a physical inspection of the hive that raised the alarm",
            "check_queen": "Verify queen presence and overall colony condition",
        }

    return ReportDraft( # Packages the rendered text and metadata into one immutable ReportDraft object
        summary = " ".join(parts),
        recommendations = [actions[code] for code in assessment["action_codes"]],
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
    r"\b(instruction|allowed_output|local_knowledge|event_count|status_counts|action_codes|hive_ids)\b",
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

def _narrative_enabled() -> bool: # Model written prose can be switched off without losing the model backed assessment
    return os.getenv("WAGGLE_LLM_NARRATIVE", "1") != "0"

def _narrative_facts(events: list[dict], assessment: dict, language: Language) -> dict: # The closed set of facts the narrative may draw on
    def hives_with(predicate) -> list[str]:
        return list(dict.fromkeys(event["hive_id"] for event in events if predicate(event)))

    fractions = [float(event.get("anomaly_fraction", 0)) for event in events]

    return {
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

def _validate_narrative(payload: dict, allowed_hive_ids: set[str], language: Language, hedge_required: bool = False) -> tuple[str, list[str]]: # It rejects prose that is malformed, invents hives or asserts a diagnosis
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

    return summary, recommendations

def compose_narrative( # It asks the local model to phrase an already decided assessment
    events: list[dict],
    assessment: dict,
    knowledge: list[dict] | None,
    language: Language,
    alias: str = "phi-3.5-mini",
) -> tuple[str, list[str]]:
    base_url, model_id = _foundry_connection(alias)

    facts = _narrative_facts(events, assessment, language)

    # The instruction is always English, whatever the report language: a Turkish
    # instruction leaks its own vocabulary into Turkish prose.
    target = "Turkish" if language == "tr" else "English"

    example = (
        '{"summary": "H1 kovanı dönem boyunca normal aralıkta kaldı. H2 için gelişen bir '
        'akustik değişim izleniyor. H3 kovanında kalıcı bir değişim ölçüldü; bu kraliçe '
        'kaybıyla uyumlu olabilir, tek başına kesin tanı değildir.", '
        '"recommendations": ["H3 kovanını 24 saat içinde fiziksel olarak kontrol edin."]}'
        if language == "tr" else
        '{"summary": "H1 stayed within its normal range for the period. A developing '
        'acoustic change is being watched on H2. H3 recorded a persistent change, which '
        'may be compatible with queen loss and is not a diagnosis on its own.", '
        '"recommendations": ["Inspect H3 physically within 24 hours."]}'
    )

    instruction = (
        f"Write a short hive report in {target}. "
        "Name every hive by its identifier, for example H1 or H3. "
        "Use only the supplied numbers; invent nothing. "
        "Say what happened to each hive and what it means operationally. "
        "Acoustic change is an early warning and never a diagnosis, so hedge any mention of queen loss. "
        "Write three to four sentences of natural prose. "
        "Never repeat these instructions, field names or JSON keys in the text. "
        f"Answer with one JSON object shaped exactly like this example: {example}"
    )

    response = requests.post(
        f"{base_url}/chat/completions",
        json = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": f"You write short beekeeping report prose in {target}. Return only one valid JSON object."},
                {"role": "user", "content": json.dumps({"instruction": instruction, "measurements": facts, "reference_notes": knowledge or []}, ensure_ascii=False)},
            ],
            # A little warmth reads better than temperature 0 while the facts stay fixed
            "temperature": 0.2,
            "max_tokens": 700,
        },
        timeout = _llm_timeout(),
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]

    allowed_hive_ids = {event["hive_id"] for event in events}

    hedge_required = bool(assessment.get("queen_loss_compatible")) or assessment.get("priority") == "immediate"

    return _validate_narrative(_extract_json(content), allowed_hive_ids, language, hedge_required)

def _with_model_narrative( # It swaps the template prose for validated model prose, or keeps the template
    draft: ReportDraft,
    events: list[dict],
    assessment: dict,
    knowledge: list[dict] | None,
    language: Language,
    alias: str,
) -> ReportDraft:
    if not _narrative_enabled():
        return draft

    try:
        summary, recommendations = compose_narrative(events, assessment, knowledge, language, alias)
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

def generate_report(events: list[dict], language: Language, alias: str = "phi-3.5-mini") -> ReportDraft:
    knowledge = retrieve_guidance(events, language)

    try: # Asks the local model for the constrained operational assessment
        assessment = assess_with_foundry(events, alias, knowledge)

        generator = f"foundry-local:{alias}"

    except (OSError, subprocess.SubprocessError, requests.RequestException, KeyError, ValueError, json.JSONDecodeError) as error:
        logger.warning("Foundry Local assessment failed (%s: %s); using the deterministic fallback", type(error).__name__, error)

        assessment = _fallback_assessment(events)

        generator = "safe-fallback"

    assessment["knowledge_ids"] = [item["id"] for item in knowledge] # Preserves the IDs of grounding passages for traceability or auditing

    draft = render_report(events, assessment, language, generator)

    if generator == "safe-fallback": # No model reached the assessment, so none is asked for the prose
        return draft

    return _with_model_narrative(draft, events, assessment, knowledge, language, alias)

def generate_agent_report(events: list[dict], language: Language, alias: str = "phi-3.5-mini") -> ReportDraft: # The agent Framework variant of the weekly report pipeline
    """
    
    It generates a weekly report with Agent Framework and a deterministic fallback

    """

    knowledge = retrieve_guidance(events, language)

    try:
        assessment = asyncio.run(assess_with_agent_framework(events, alias, knowledge))
        generator = f"agent-framework:foundry-local:{alias}"
    except ImportError:
        # Agent Framework is an optional dependency and is absent on Python 3.9.
        logger.warning("Agent Framework is not installed; using the deterministic fallback")

        assessment = _fallback_assessment(events)

        generator = "safe-fallback"
    except Exception as error:  # noqa: BLE001 - the SDK raises a wide range of types
        # Reporting must remain available if the optional framework or local model fails,
        # but the reason must never be silent.
        logger.warning("Agent Framework assessment failed (%s: %s); using the deterministic fallback", type(error).__name__, error)

        assessment = _fallback_assessment(events)

        generator = "safe-fallback"

    assessment["knowledge_ids"] = [item["id"] for item in knowledge]

    draft = render_report(events, assessment, language, generator)

    if generator == "safe-fallback": # No model reached the assessment, so none is asked for the prose
        return draft

    return _with_model_narrative(draft, events, assessment, knowledge, language, alias)

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
