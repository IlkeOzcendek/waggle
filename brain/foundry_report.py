"""

It generates a safe bilingual hive report with Microsoft Foundry Local

"""

from __future__ import annotations # Postpones evaluation of type annotations which makes forward references and modern type hints easier to use
from dataclasses import dataclass # Provides @dataclass for defining lightweight classes that mainly store structured data
from datetime import datetime, timedelta, timezone
from typing import Literal # Literal restricts a type hint to a fixed set of allowed string values

import argparse
import asyncio # It runs the asynchronous Agent Framework assessment from synchronous code
import json
import os
import re

import subprocess # It executes Foundry CLI commands such as model load and server restart

import requests

from brain.local_rag import retrieve_guidance

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

def _foundry_connection(alias: str) -> tuple[str, str]: # It ensures the requested local model is loaded and returns
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

    match = re.search(r"\{.*\}", text, flags = re.DOTALL)

    if not match:
        raise ValueError("Foundry response did not contain a JSON object")

    value = json.loads(match.group(0))

    if not isinstance(value, dict):
        raise ValueError("Foundry assessment must be a JSON object")
    
    return value

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
            "max_tokens": 160,
        },
        timeout = 180,
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

    from agent_framework.openai import OpenAIChatClient

    base_url, model_id = _foundry_connection(alias)

    agent = Agent( # It creates a constrained offline reporting agent backed by the local Foundry model
        client = OpenAIChatClient(
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

    alarm_hives = [event["hive_id"] for event in events if event["status"] == "ALARM"] # Identify hives requiring immediate inspection language

    watch_hives = [event["hive_id"] for event in events if event["status"] == "WATCH"] # Identify hives with developing acoustic change

    normal_hives = [event["hive_id"] for event in events if event["status"] == "NORMAL"] # It identifies hives remaining within their learned baseline

    if language == "tr": # Render Turkish summary sentences and Turkish recommendation texts here
        parts = []
        if normal_hives:
            parts.append(f"{', '.join(normal_hives)} normal akustik profili içinde kaldı")
        if watch_hives:
            parts.append(f"{', '.join(watch_hives)} için gelişen akustik değişim izleniyor")
        if alarm_hives:
            parts.append(
                f"{', '.join(alarm_hives)} için kraliçe kaybıyla uyumlu olabilecek kalıcı akustik değişim algılandı, bu kesin tanı değildir"
            )
        actions = {
            "continue_monitoring": "Rutin akustik izlemeye devam edin",
            "record_again": "Yeni bir ses kaydı alın ve değişimin sürüp sürmediğini kontrol edin",
            "inspect_hive": "Alarm veren kovanı fiziksel olarak kontrol edin",
            "check_queen": "Kraliçenin varlığını ve koloni durumunu doğrulayın",
        }

    else: # English versions are here
        parts = []
        if normal_hives:
            parts.append(f"{', '.join(normal_hives)} remained within the learned acoustic baseline")

        if watch_hives:
            parts.append(f"A developing acoustic change is being monitored for {', '.join(watch_hives)}")

        if alarm_hives:
            parts.append(
                f"Persistent acoustic change compatible with possible queen loss was detected for {', '.join(alarm_hives)}; this is not a definitive diagnosis"
            )

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

def generate_report(events: list[dict], language: Language, alias: str = "phi-3.5-mini") -> ReportDraft:
    knowledge = retrieve_guidance(events, language)

    try: # Asks the local model for the constrained operational assessment
        assessment = assess_with_foundry(events, alias, knowledge)

        generator = f"foundry-local:{alias}"

    except (OSError, subprocess.SubprocessError, requests.RequestException, KeyError, ValueError, json.JSONDecodeError):
        assessment = _fallback_assessment(events)

        generator = "safe-fallback"

    assessment["knowledge_ids"] = [item["id"] for item in knowledge] # Preserves the IDs of grounding passages for traceability or auditing

    return render_report(events, assessment, language, generator)

def generate_agent_report(events: list[dict], language: Language, alias: str = "phi-3.5-mini") -> ReportDraft: # The agent Framework variant of the weekly report pipeline
    """
    
    It generates a weekly report with Agent Framework and a deterministic fallback

    """

    knowledge = retrieve_guidance(events, language)

    try:
        assessment = asyncio.run(assess_with_agent_framework(events, alias, knowledge))
        generator = f"agent-framework:foundry-local:{alias}"
    except Exception:
        # Reporting must remain available if the optional framework or local
        assessment = _fallback_assessment(events)

        generator = "safe-fallback"

    assessment["knowledge_ids"] = [item["id"] for item in knowledge]

    return render_report(events, assessment, language, generator)

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