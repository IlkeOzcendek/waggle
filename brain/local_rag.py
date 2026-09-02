"""Offline retrieval over Waggle's reviewed hive guidance.

The retriever is deterministic and needs no network and no embedding model: the panel is
meant to work in a field shed with the Wi-Fi off. What it does have is the facts of the
period, so it selects on those rather than on the status label alone — an alarm at 40%
anomaly in December is a different situation from one at 95% in May, and the older
version returned the same three passages for both.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_PATH = Path(__file__).with_name("knowledge") / "hive_guidance.json"

# A matched condition is worth more than a matched word: conditions encode "this passage
# is about a situation like yours", while a shared word may be incidental.
CONDITION_WEIGHT = 6.0
TAG_WEIGHT = 2.0


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9_]+", value.casefold()))


def _lexical_score(query: set[str], entry: dict, idf: dict[str, float]) -> float:
    """Word overlap, divided by passage length.

    Without the division the score is a plain sum, so a long bilingual passage collects
    more matches than a short one purely by being long — and the seasonal notes, which
    are short and specific, lost to general prose every time.
    """
    tags = _tokens(" ".join(entry["tags"]))
    body = _tokens(" ".join([entry["en"], entry["tr"]]))
    raw = sum(idf.get(token, 1.0) * TAG_WEIGHT for token in query & tags)
    raw += sum(idf.get(token, 1.0) for token in query & (body - tags))
    return raw / math.sqrt(len(tags | body) or 1)


@lru_cache(maxsize=1)
def load_knowledge() -> tuple[dict, ...]:
    entries = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("Local knowledge base must contain at least one entry")
    required = {"id", "tags", "tr", "en"}
    if any(not required.issubset(entry) for entry in entries):
        raise ValueError("Local knowledge entry is incomplete")
    return tuple(entries)


@lru_cache(maxsize=1)
def _inverse_document_frequency() -> dict[str, float]:
    """Words that appear in most passages carry almost no signal; weight them down."""
    entries = load_knowledge()
    counts: dict[str, int] = {}
    for entry in entries:
        for token in _tokens(" ".join([entry["id"], *entry["tags"], entry["en"], entry["tr"]])):
            counts[token] = counts.get(token, 0) + 1
    return {token: math.log(len(entries) / count) + 1 for token, count in counts.items()}


def _parsed_month(event: dict) -> int | None:
    stamp = event.get("timestamp")
    if isinstance(stamp, datetime):
        return stamp.month
    if isinstance(stamp, str):
        try:
            return datetime.fromisoformat(stamp.replace("Z", "+00:00")).month
        except ValueError:
            return None
    return None


def event_profile(events: list[dict]) -> dict:
    """The facts a passage can be selected against."""
    fractions = [float(event["anomaly_fraction"]) for event in events if event.get("anomaly_fraction") is not None]
    runs = [int(event["consecutive_anomalies"]) for event in events if event.get("consecutive_anomalies") is not None]
    months = {month for month in (_parsed_month(event) for event in events) if month}
    return {
        "statuses": {str(event.get("status", "")).upper() for event in events if event.get("status")},
        "max_anomaly": max(fractions, default=0.0),
        "max_consecutive": max(runs, default=0),
        # Absent measurements must not be read as zero: a passage about short anomalous
        # runs should not be chosen because no run length was recorded at all.
        "has_anomaly": bool(fractions),
        "has_runs": bool(runs),
        "hive_count": len({event.get("hive_id") for event in events if event.get("hive_id")}),
        "months": months,
        "event_count": len(events),
    }


def _condition_score(entry: dict, profile: dict) -> float | None:
    """Score an entry against the period, or None when it does not apply to it."""
    conditions = entry.get("conditions")
    if not conditions:
        return 0.0
    matched = 0
    for name, expected in conditions.items():
        if name == "status":
            if not profile["statuses"] & set(expected):
                return None
        elif name == "min_anomaly":
            if not profile["has_anomaly"] or profile["max_anomaly"] < expected:
                return None
        elif name == "max_anomaly":
            if not profile["has_anomaly"] or profile["max_anomaly"] > expected:
                return None
        elif name == "min_consecutive":
            if not profile["has_runs"] or profile["max_consecutive"] < expected:
                return None
        elif name == "max_consecutive":
            if not profile["has_runs"] or profile["max_consecutive"] > expected:
                return None
        elif name == "months":
            if not profile["months"] & set(expected):
                return None
        elif name == "min_hives":
            if profile["hive_count"] < expected:
                return None
        else:  # An unknown condition must never silently widen a match.
            return None
        matched += 1
    return matched * CONDITION_WEIGHT


def _query_tokens(profile: dict) -> set[str]:
    parts = list(profile["statuses"])
    if "ALARM" in profile["statuses"]:
        parts.append("persistent acoustic change queen loss inspect hive check queen diagnosis")
    if "WATCH" in profile["statuses"]:
        parts.append("developing acoustic change record again continue monitoring")
    if profile["statuses"] <= {"NORMAL"}:
        parts.append("normal baseline continue monitoring")
    if profile["max_anomaly"] >= 0.85:
        parts.append("anomaly_fraction dominant microphone placement")
    if profile["max_consecutive"] >= 20:
        parts.append("consecutive_anomalies sustained priority")
    if profile["hive_count"] > 1:
        parts.append("multiple_hives comparison environmental")
    return _tokens(" ".join(parts))


def retrieve_guidance(events: list[dict], language: str, limit: int = 3) -> list[dict]:
    """Return the passages that fit this period, most specific first."""
    profile = event_profile(events)
    query = _query_tokens(profile)
    idf = _inverse_document_frequency()
    scored = []
    for index, entry in enumerate(load_knowledge()):
        condition_score = _condition_score(entry, profile)
        if condition_score is None:
            continue
        total = condition_score + _lexical_score(query, entry, idf)
        if total > 0:
            scored.append((total, -index, entry))
    scored.sort(reverse=True)
    selected = [entry for _, _, entry in scored[:limit]]

    # Reserve a slot for the season. Alarm guidance always outscores it — an alarm is the
    # more urgent thing to say — but "it is May, look for queen cells" is exactly the
    # context that turns a generic warning into advice about this hive, this month. So it
    # is guaranteed a place rather than left to win on points.
    if limit > 1 and not any("months" in entry.get("conditions", {}) for entry in selected):
        seasonal = next(
            (entry for _, _, entry in scored if "months" in entry.get("conditions", {})),
            None,
        )
        if seasonal is not None:
            selected = selected[: limit - 1] + [seasonal]

    return [{"id": entry["id"], "text": entry[language]} for entry in selected]


def search_guidance(query: str, language: str, limit: int = 3) -> list[dict]:
    """Free-text lookup, for the agent to call when it wants something specific."""
    query_tokens = _tokens(query)
    idf = _inverse_document_frequency()
    scored = []
    for index, entry in enumerate(load_knowledge()):
        score = _lexical_score(query_tokens, entry, idf)
        if score > 0:
            scored.append((score, -index, entry))
    scored.sort(reverse=True)
    return [{"id": entry["id"], "text": entry[language]} for _, _, entry in scored[:limit]]
