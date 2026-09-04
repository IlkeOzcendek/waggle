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

# Turkish builds words by attaching suffixes to a stem, so the word a beekeeper types and
# the word a passage uses routinely differ only in their ending. Matching whole tokens
# alone therefore failed on the majority of natural queries: measured on this corpus,
# "oğullar", "kraliçesiz", "kovanları" and "nemli" each returned nothing while "oğul",
# "kraliçe", "kovan" and "nem" were all present in the text.
MINIMUM_STEM = 3
# An inflected match is real evidence, but weaker than the word itself: it is a guess about
# morphology, made without a dictionary. Weighting it below an exact match is what keeps
# the guess from outranking a passage that actually uses the searched word.
INFLECTION_WEIGHT = 0.6

# Wind noise starts entering an outdoor microphone well before a beekeeper would call the
# day windy. This is a caution threshold, not a physical constant: above it a recording is
# worth repeating before its anomaly ratio is read as the colony's own sound.
WIND_NOISE_KMH = 20.0
# WMO interpretation codes from 51 upward are drizzle and everything wetter. Fog (45, 48)
# is deliberately below the line: it does not carry the sound of rain onto the microphone.
PRECIPITATION_CODE = 51


def _tokens(value: str) -> set[str]:
    """Words, by Unicode's definition rather than by a hand-written alphabet.

    The alphabet this used to list left out â, î and û, which Turkish still writes in
    words like "rüzgâr" and "hâle". They were not skipped, they were split: "rüzgâr"
    entered the vocabulary as "rüzg" and "r", so the passage about wind could not be found
    by searching for wind, and the fragments distorted every inverse-document-frequency
    weight around them.
    """
    return set(re.findall(r"\w+", value.casefold()))


@lru_cache(maxsize=1)
def _vocabulary() -> tuple[str, ...]:
    """Every word the corpus uses, which is the only dictionary available offline."""
    return tuple(sorted(_inverse_document_frequency()))


# Turkish softens a final k, p, t or ç when a vowel-initial suffix follows, so the stem
# itself changes: hırsızlık becomes hırsızlığı, kitap becomes kitabı. A prefix comparison
# alone breaks on exactly the last letter, which is why searching for "bal hırsızlığı"
# returned the note about a recent honey harvest and not the note about robbing.
SOFTENED_CONSONANTS = {"k": "ğ", "p": "b", "t": "d", "ç": "c"}


def _stem_forms(word: str) -> tuple[str, ...]:
    """The word, plus the shape it takes when a suffix softens its final consonant."""
    softened = SOFTENED_CONSONANTS.get(word[-1:])
    return (word,) if softened is None else (word, word[:-1] + softened)


def _related(token: str) -> dict[str, float]:
    """Corpus words that are the same word as this one, give or take a suffix.

    Either direction counts: the query may be the inflected form ("kovanları" against the
    passage's "kovan") or the stem ("nem" against "nemli"). The weight falls off as the
    two diverge in length, so "kovan" is worth much more against "kovanı" than against
    "kovanlarındakiler", where the shared prefix is more likely to be a coincidence.
    """
    related: dict[str, float] = {}
    for word in _vocabulary():
        if word == token:
            continue
        shorter, longer = sorted((token, word), key=len)
        if len(shorter) < MINIMUM_STEM:
            continue
        if not any(longer.startswith(form) for form in _stem_forms(shorter)):
            continue
        related[word] = INFLECTION_WEIGHT * len(shorter) / len(longer)
    return related


def _weighted_query(query: set[str]) -> dict[str, dict[str, float]]:
    """Each searched word, with the corpus forms it can be matched through.

    Kept grouped by the word the reader typed rather than flattened, because a passage may
    contain several forms of one word — "kraliçesizlik", "kraliçe" and "kraliçesini" — and
    those are one term used three times, not three terms.
    """
    grouped: dict[str, dict[str, float]] = {}
    for token in query:
        forms = dict(_related(token))
        # An exact match always outranks a prefix relationship pointing at the same word.
        forms[token] = 1.0
        grouped[token] = forms
    return grouped


def _lexical_score(query: dict[str, dict[str, float]], entry: dict, idf: dict[str, float]) -> float:
    """Weighted word overlap, divided by passage length.

    Without the division the score is a plain sum, so a long bilingual passage collects
    more matches than a short one purely by being long — and the seasonal notes, which
    are short and specific, lost to general prose every time.

    Each searched word scores at most once, through whichever of its forms fits best.
    Summing the forms instead let one word be counted as many times as the passage happened
    to inflect it: searching "kraliçe" ranked the note that writes it three ways above the
    note about queens, on no more evidence.
    """
    tags = _tokens(" ".join(entry["tags"]))
    body = _tokens(" ".join([entry["en"], entry["tr"]]))
    raw = 0.0
    for forms in query.values():
        best = max(
            (idf.get(word, 1.0) * TAG_WEIGHT * weight for word, weight in forms.items() if word in tags),
            default=0.0,
        )
        best = max(best, max(
            (idf.get(word, 1.0) * weight for word, weight in forms.items() if word in body - tags),
            default=0.0,
        ))
        raw += best
    return raw / math.sqrt(len(tags | body) or 1)


@lru_cache(maxsize=1)
def load_knowledge() -> tuple[dict, ...]:
    entries = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("Local knowledge base must contain at least one entry")
    required = {"id", "title", "tags", "tr", "en"}
    if any(not required.issubset(entry) for entry in entries):
        raise ValueError("Local knowledge entry is incomplete")
    return tuple(entries)


# What a note is about, in the reader's words. The tags are the retriever's vocabulary —
# "consecutive_anomalies", "false_positive", "health_confirmation" — and printing them on
# a page a beekeeper reads showed them the machine's index instead of their own subject.
# The order matters: a seasonal note about an alarm is filed under the season, because that
# is what makes it apply today.
CATEGORY_RULES = (
    ("seasonal", ("Mevsim", "Season")),
    ("limits", ("Sınırlar", "Limits")),
    ("false_positive", ("Yanlış alarm", "False alarm")),
    ("method", ("Yöntem", "Method")),
    ("health_confirmation", ("Saha kontrolü", "Field check")),
    ("ALARM", ("Alarm", "Alarm")),
    ("WATCH", ("İzleme", "Watch")),
    ("NORMAL", ("Normal", "Normal")),
)
DEFAULT_CATEGORY = ("Koloni", "Colony")


def guidance_title(entry: dict, language: str) -> str:
    """The note's own name, falling back to its id for a base written before titles."""
    title = entry.get("title") or {}
    return title.get(language) or title.get("tr") or entry["id"]


def guidance_category(entry: dict, language: str) -> str:
    """The one word that says which part of beekeeping this note belongs to."""
    tags = set(entry.get("tags", ()))
    for tag, names in CATEGORY_RULES:
        if tag in tags:
            return names[0] if language == "tr" else names[1]
    return DEFAULT_CATEGORY[0] if language == "tr" else DEFAULT_CATEGORY[1]


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
    def measurement(event: dict, name: str) -> float:
        try:
            value = float(event[name])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{name} must be a number") from error
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{name} must be finite and between 0 and 1")
        return value

    fractions = [measurement(event, "anomaly_fraction") for event in events if event.get("anomaly_fraction") is not None]
    # How far the sound moved, where anomaly_fraction is how often it moved. Absent on
    # events recorded before the acoustic model reported it.
    severities = [measurement(event, "anomaly_severity") for event in events if event.get("anomaly_severity") is not None]
    runs = []
    for event in events:
        if event.get("consecutive_anomalies") is None:
            continue
        value = event["consecutive_anomalies"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("consecutive_anomalies must be a non-negative integer")
        runs.append(value)
    months = {month for month in (_parsed_month(event) for event in events) if month}
    # Conditions are stamped only while online weather is on, so most periods carry none.
    # An absent reading is never treated as a calm, dry one: it is unknown, and a passage
    # that selects on weather must not match a period whose weather was never observed.
    winds = [float(event["wind_kmh"]) for event in events if event.get("wind_kmh") is not None]
    codes = {int(event["weather_code"]) for event in events if event.get("weather_code") is not None}
    adverse = [
        event for event in events
        if (event.get("wind_kmh") is not None and float(event["wind_kmh"]) >= WIND_NOISE_KMH)
        or (event.get("weather_code") is not None and int(event["weather_code"]) >= PRECIPITATION_CODE)
    ]
    return {
        "statuses": {str(event.get("status", "")).upper() for event in events if event.get("status")},
        "max_anomaly": max(fractions, default=0.0),
        "max_severity": max(severities, default=0.0),
        "has_severity": bool(severities),
        "max_consecutive": max(runs, default=0),
        # Absent measurements must not be read as zero: a passage about short anomalous
        # runs should not be chosen because no run length was recorded at all.
        "has_anomaly": bool(fractions),
        "has_runs": bool(runs),
        "hive_count": len({event.get("hive_id") for event in events if event.get("hive_id")}),
        "months": months,
        "event_count": len(events),
        "has_weather": bool(winds or codes),
        "max_wind_kmh": max(winds, default=0.0),
        "precipitation": any(code >= PRECIPITATION_CODE for code in codes),
        # Whether a decision the beekeeper has to act on was taken in conditions that
        # corrupt a recording. This is what turns the weather note from trivia into a
        # reason to measure again before opening a hive.
        "adverse_recording": bool(adverse),
        "adverse_statuses": {str(event.get("status", "")).upper() for event in adverse if event.get("status")},
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
        elif name == "min_wind_kmh":
            if not profile["has_weather"] or profile["max_wind_kmh"] < expected:
                return None
        elif name == "precipitation":
            if not profile["has_weather"] or profile["precipitation"] is not bool(expected):
                return None
        elif name == "adverse_recording":
            if not profile["has_weather"] or profile["adverse_recording"] is not bool(expected):
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
    if profile["adverse_recording"]:
        parts.append("rüzgâr yağmur kayıt koşulu wind rain recording conditions repeat false_positive")
    return _tokens(" ".join(parts))


def _presented(entry: dict, language: str) -> dict:
    """A note as a reader meets it: named, filed, and quoted — with its id kept for audit."""
    return {
        "id": entry["id"],
        "title": guidance_title(entry, language),
        "category": guidance_category(entry, language),
        "text": entry[language],
    }


def retrieve_guidance(events: list[dict], language: str, limit: int = 3) -> list[dict]:
    """Return the passages that fit this period, most specific first."""
    profile = event_profile(events)
    query = _weighted_query(_query_tokens(profile))
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

    return [_presented(entry, language) for entry in selected]


def search_guidance(query: str, language: str, limit: int = 3) -> list[dict]:
    """Free-text lookup, for the agent to call when it wants something specific."""
    query_tokens = _weighted_query(_tokens(query))
    idf = _inverse_document_frequency()
    scored = []
    for index, entry in enumerate(load_knowledge()):
        score = _lexical_score(query_tokens, entry, idf)
        if score > 0:
            scored.append((score, -index, entry))
    scored.sort(reverse=True)
    return [_presented(entry, language) for _, _, entry in scored[:limit]]
