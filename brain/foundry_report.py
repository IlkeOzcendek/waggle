"""Generate a safe bilingual hive report with Microsoft Foundry Local."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import argparse
import json
import os
import re
import subprocess

import requests


Language = Literal["tr", "en"]
ALLOWED_PRIORITIES = {"routine", "watch", "immediate"}
ALLOWED_ACTIONS = {"continue_monitoring", "record_again", "inspect_hive", "check_queen"}


@dataclass(frozen=True)
class ReportDraft:
    summary: str
    recommendations: list[str]
    hive_ids: list[str]
    language: Language
    generator: str
    assessment: dict


def _run_foundry(*arguments: str) -> str:
    result = subprocess.run(
        ["foundry", *arguments],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def _foundry_connection(alias: str) -> tuple[str, str]:
    subprocess.run(
        ["foundry", "model", "load", alias],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )
    status = json.loads(_run_foundry("server", "status", "--output", "json"))
    model = json.loads(_run_foundry("model", "info", alias, "--output", "json"))["model"]
    return status["webUrls"][0].rstrip("/") + "/v1", model["id"]


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("Foundry response did not contain a JSON object")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Foundry assessment must be a JSON object")
    return value


def _fallback_assessment(events: list[dict]) -> dict:
    statuses = {event["status"] for event in events}
    if "ALARM" in statuses:
        return {
            "priority": "immediate",
            "pattern": "persistent_acoustic_change",
            "queen_loss_compatible": True,
            "inspection_required": True,
            "action_codes": ["inspect_hive", "check_queen"],
        }
    if "WATCH" in statuses:
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


def _validate_assessment(value: dict, events: list[dict]) -> dict:
    priority = value.get("priority")
    actions = value.get("action_codes")
    if priority not in ALLOWED_PRIORITIES:
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
    if any(event["status"] == "ALARM" for event in events):
        result.update(
            priority="immediate",
            queen_loss_compatible=True,
            inspection_required=True,
        )
        for action in ("inspect_hive", "check_queen"):
            if action not in result["action_codes"]:
                result["action_codes"].append(action)
    return result


def assess_with_foundry(events: list[dict], alias: str = "phi-3.5-mini") -> dict:
    base_url, model_id = _foundry_connection(alias)
    prompt = {
        "task": "Classify the operational response to acoustic hive events.",
        "events": events,
        "allowed_priority": sorted(ALLOWED_PRIORITIES),
        "allowed_action_codes": sorted(ALLOWED_ACTIONS),
        "rules": [
            "ALARM is persistent acoustic change, not proof of queen death.",
            "ALARM requires inspect_hive and check_queen.",
            "WATCH requires continued monitoring or another recording.",
        ],
        "output_schema": {
            "priority": "one allowed priority",
            "pattern": "short snake_case identifier",
            "queen_loss_compatible": "boolean",
            "inspection_required": "boolean",
            "action_codes": "list of allowed action codes",
        },
    }
    response = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only one valid JSON object. Do not write prose or markdown.",
                },
                {"role": "user", "content": json.dumps(prompt)},
            ],
            "temperature": 0,
            "max_tokens": 160,
        },
        timeout=180,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _validate_assessment(_extract_json(content), events)


def render_report(events: list[dict], assessment: dict, language: Language, generator: str) -> ReportDraft:
    hive_ids = list(dict.fromkeys(event["hive_id"] for event in events))
    alarm_hives = [event["hive_id"] for event in events if event["status"] == "ALARM"]
    watch_hives = [event["hive_id"] for event in events if event["status"] == "WATCH"]
    normal_hives = [event["hive_id"] for event in events if event["status"] == "NORMAL"]

    if language == "tr":
        parts = []
        if normal_hives:
            parts.append(f"{', '.join(normal_hives)} normal akustik profili içinde kaldı.")
        if watch_hives:
            parts.append(f"{', '.join(watch_hives)} için gelişen akustik değişim izleniyor.")
        if alarm_hives:
            parts.append(
                f"{', '.join(alarm_hives)} için kraliçe kaybıyla uyumlu olabilecek kalıcı akustik değişim algılandı; bu kesin tanı değildir."
            )
        actions = {
            "continue_monitoring": "Rutin akustik izlemeye devam edin.",
            "record_again": "Yeni bir ses kaydı alın ve değişimin sürüp sürmediğini kontrol edin.",
            "inspect_hive": "Alarm veren kovanı fiziksel olarak kontrol edin.",
            "check_queen": "Kraliçenin varlığını ve koloni durumunu doğrulayın.",
        }
    else:
        parts = []
        if normal_hives:
            parts.append(f"{', '.join(normal_hives)} remained within the learned acoustic baseline.")
        if watch_hives:
            parts.append(f"A developing acoustic change is being monitored for {', '.join(watch_hives)}.")
        if alarm_hives:
            parts.append(
                f"Persistent acoustic change compatible with possible queen loss was detected for {', '.join(alarm_hives)}; this is not a definitive diagnosis."
            )
        actions = {
            "continue_monitoring": "Continue routine acoustic monitoring.",
            "record_again": "Capture another recording and confirm whether the change persists.",
            "inspect_hive": "Perform a physical inspection of the hive that raised the alarm.",
            "check_queen": "Verify queen presence and overall colony condition.",
        }
    return ReportDraft(
        summary=" ".join(parts),
        recommendations=[actions[code] for code in assessment["action_codes"]],
        hive_ids=hive_ids,
        language=language,
        generator=generator,
        assessment=assessment,
    )


def generate_report(events: list[dict], language: Language, alias: str = "phi-3.5-mini") -> ReportDraft:
    try:
        assessment = assess_with_foundry(events, alias)
        generator = f"foundry-local:{alias}"
    except (OSError, subprocess.SubprocessError, requests.RequestException, KeyError, ValueError, json.JSONDecodeError):
        assessment = _fallback_assessment(events)
        generator = "safe-fallback"
    return render_report(events, assessment, language, generator)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("tr", "en"), default="tr")
    parser.add_argument("--model", default="phi-3.5-mini")
    parser.add_argument("--panel-url", default="http://127.0.0.1:8000/api/reports")
    parser.add_argument("--device-key", default=os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo"))
    parser.add_argument("--no-post", action="store_true")
    args = parser.parse_args()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    events = [
        {"hive_id": "H1", "status": "NORMAL", "anomaly_fraction": .08, "consecutive_anomalies": 0},
        {"hive_id": "H2", "status": "WATCH", "anomaly_fraction": .66, "consecutive_anomalies": 5},
        {"hive_id": "H3", "status": "ALARM", "anomaly_fraction": 1.0, "consecutive_anomalies": 30},
    ]
    report = generate_report(events, args.language, args.model)
    payload = {
        "period_start": (now - timedelta(days=7)).isoformat(),
        "period_end": now.isoformat(),
        "summary": report.summary,
        "recommendations": report.recommendations,
        "hive_ids": report.hive_ids,
        "language": report.language,
        "generator": report.generator,
    }
    print(json.dumps({**payload, "assessment": report.assessment}, ensure_ascii=False, indent=2))
    if not args.no_post:
        response = requests.post(
            args.panel_url,
            json=payload,
            headers={"X-Device-Key": args.device_key},
            timeout=10,
        )
        response.raise_for_status()
        print(f"report_id={response.json()['id']}")


if __name__ == "__main__":
    main()
