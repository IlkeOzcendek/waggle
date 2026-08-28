# Event Contract — v2 · FROZEN

The acoustic monitor produces this event and the panel consumes it. Any field
or semantic change requires a new contract version and coordinated tests.

## Payload

```json
{
  "hive_id": "H3",
  "timestamp": "2026-08-29T12:30:00Z",
  "status": "ALARM",
  "anomaly_fraction": 1.0,
  "consecutive_anomalies": 30,
  "source_file": "queen_loss_sample.wav"
}
```

## Fields

| Field | Type | Rules |
| --- | --- | --- |
| `hive_id` | string | Active panel hive identifier such as `H1` or `H4` |
| `timestamp` | string | ISO 8601 timestamp; UTC with `Z` is preferred |
| `status` | string | `NORMAL`, `WATCH`, or `ALARM` |
| `anomaly_fraction` | float | Fraction of one-second windows classified as anomalous, from 0 to 1 |
| `consecutive_anomalies` | integer | Current consecutive anomalous-window count, zero or greater |
| `source_file` | string or null | Source WAV filename for auditability |

## Status semantics

- `NORMAL`: the current acoustic sequence remains below the watch rule.
- `WATCH`: at least five consecutive anomalous seconds were observed.
- `ALARM`: at least 30 consecutive anomalous seconds were observed.

`anomaly_fraction` is not a calibrated probability and must never be displayed
as model confidence. The panel reports it as the proportion of anomalous audio
windows. `ALARM` means that persistent acoustic change compatible with queen
loss was detected; it requests physical inspection and does not prove queen
death.

## Transport

Events are posted to `POST /api/events` with `Content-Type: application/json`
and the shared `X-Device-Key` header. The device client retries temporary
failures and stores unsent payloads in a local JSONL queue.
