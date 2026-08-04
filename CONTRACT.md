# Event Contract — v1 · FROZEN

The two halves of Waggle communicate **only** through this format. İlke's side (ear/brain)
**produces** events; İrem's side (panel) **consumes** them. Changing this format requires
agreement from both of us; any change bumps the version (v2) and updates this file.

## Format

```json
{
  "hive_id": "H3",
  "timestamp": "2026-08-12T14:30:00",
  "event": "queenless_suspected",
  "confidence": 0.87
}
```

## Fields

| Field | Type | Rules |
|---|---|---|
| `hive_id` | string | `"H1"`, `"H2"`, `"H3"` — simulated hives |
| `timestamp` | string | ISO 8601, local time (`YYYY-MM-DDTHH:MM:SS`) |
| `event` | string | `"queenless_suspected"` \| `"healthy"` \| `"uncertain"` |
| `confidence` | float | model confidence score, 0.0–1.0 |

## Flow rules

- Events are written to the SQLite store on the panel side (table schema is İrem's responsibility).
- Weeks 1–2: the event source is the fake event generator in `tools/`.
- Week 3: the source is swapped for the real model stream (`ear/`) — zero changes on the panel side.
