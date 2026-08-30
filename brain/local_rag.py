"""

It is a small deterministic retriever for Waggle's offline guidance notes

"""

from __future__ import annotations # It makes type definitions more flexible by allowing type hints to be processed later instead of evaluated immediately

from functools import lru_cache # This allows a function to cache a previously calculated result and avoid recalculating it
from pathlib import Path

import json
import re # regex

KNOWLEDGE_PATH = Path(__file__).with_name("knowledge") / "hive_guidance.json"

def _tokens(value: str) -> set[str]: # It defines a helper function that takes a text file and returns a set of unique words or parts of it
    return set(re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9_]+", value.casefold()))

@lru_cache(maxsize = 1)
def load_knowledge() -> tuple[dict, ...]: # It loads the local knowledge base in JSON once and then checks that its structure is correct and stores it in memory; it doesn't read the file again in subsequent calls
    entries = json.loads(KNOWLEDGE_PATH.read_text(encoding = "utf-8"))

    if not isinstance(entries, list) or not entries:
        raise ValueError("Local knowledge base must contain at least one entry")
    
    required = {"id", "tags", "tr", "en"}

    if any(not required.issubset(entry) for entry in entries):
        raise ValueError("Local knowledge entry is incomplete")
    
    return tuple(entries)

def retrieve_guidance(events: list[dict], language: str, limit: int = 3) -> list[dict]: # It gets the event from ALARM, WATCH or normal then generates suitable keywords after that it calculates the number of common words with the text in the local JSON and retrieve the top 3 most matching guide texts
    """
    
    It returns relevant passages without network access or model generated retrieval
    
    """

    statuses = {str(event.get("status", "")).upper() for event in events}

    query = " ".join(statuses)

    if "ALARM" in statuses:
        query += " persistent acoustic change queen loss inspect hive check queen diagnosis"

    elif "WATCH" in statuses:
        query += " developing acoustic change record again continue monitoring"

    else:
        query += " normal baseline continue monitoring"

    query_tokens = _tokens(query)

    scored = []

    for index, entry in enumerate(load_knowledge()):
        searchable = " ".join([entry["id"], *entry["tags"], entry["en"], entry["tr"]])

        score = len(query_tokens & _tokens(searchable))

        scored.append((score, -index, entry))

    selected = [item[2] for item in sorted(scored, reverse = True) if item[0] > 0][:limit]

    return [{"id": entry["id"], "text": entry[language]} for entry in selected]