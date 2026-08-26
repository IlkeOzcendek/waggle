# 🐝 Waggle - AI that listens to beehives

> Bees explain directions to each other with the *waggle dance* — their own language.

> **Waggle** listens to that language and translates it for humans.


Waggle is an edge AI system that detects **queenless colonies from hive audio, fully on device**,

and generates natural language reports and alerts for beekeepers using a **local LLM

(Microsoft Foundry Local + Phi)**. Hives live in remote areas with no internet so running AI

at the edge is not a preference here but a requirement.


## Architecture

```

audio -> spectrogram -> fine tuned AST model (ONNX Runtime)

-> event JSON -> SQLite

-> Foundry Local (Phi) + RAG (beekeeping knowledge base) + Agent Framework

-> English + Turkish reports & alerts -> web panel (FastAPI + HTML/JS)

```

## Repository layout

| Folder | Owner | Contents |

|---|---|---|

| `ear/` | İlke | data scripts, spectrogram pipeline, model training, ONNX export, live stream detection |

| `brain/` | İlke | Foundry Local integration, RAG knowledge base, report agent |

| `panel/` | İrem | FastAPI backend + single-page web panel, SQLite layer, alerts |

| `tools/` | shared | fake event generator, demo scripts |

| `data/` | (git-ignored) | datasets - never pushed |


The two sides are going to communicate only through using the event contract in [`CONTRACT.md`](CONTRACT.md).


## Data

Public datasets that are no sensors required:

[To bee or not to bee](https://zenodo.org/records/1321278) and NU-Hive for training,

[UrBAN](https://www.nature.com/articles/s41597-025-04869-1) for cross dataset validation only.



## Team

- **İlke Özçendek** - Ear + Brain (audio ML, local LLM, agents)

- **İrem Erkmen** - Face (panel, storage, alerts)



Built for the Microsoft AI Innovators Summer Program 2026 · Aug 3–31, 2026

The authenticated **Sistem Durumu** page shows database integrity, stored record counts,
and the latest device/model and report integration activity in user-friendly language.

Panel name, location, critical alarm threshold, alert sound, and refresh interval can be
changed from the authenticated **Ayarlar** page and are stored persistently in SQLite.

The system status screen marks device/model activity as delayed when no new event
arrives for 15 minutes, and weekly reports as stale after eight days. These
thresholds can be changed with `WAGGLE_DEVICE_STALE_SECONDS` and
`WAGGLE_REPORT_STALE_SECONDS`.

First-time users receive a four-step quick-start guide. Completion is stored in SQLite,
and the guide can be reopened later from the settings page.

## Run the panel locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and replace the example secrets.
uvicorn panel.app.main:app --reload
```

For a presentation-ready server with deterministic H1/H2/H3 events and a
weekly report, use the one-command demo:

```bash
python tools/run_demo.py
```

See [`DEMO_CHECKLIST.md`](DEMO_CHECKLIST.md) for the presentation flow and
recovery steps. [`PRESENTATION_GUIDE.md`](PRESENTATION_GUIDE.md) contains a
four-minute Turkish narration, closing message, and answers to likely questions.

Open <http://127.0.0.1:8000> and sign in with the local demo account:

- Username: `admin`
- Password: `waggle-demo`

To open the panel from an unused Android phone on the same trusted local network,
run `python tools/run_demo.py --lan` and use the phone address printed in the
terminal. This does not require internet access. See
[`FIELD_PHONE.md`](FIELD_PHONE.md) for setup, troubleshooting, and security notes.

Configuration is loaded automatically from `.env`, which is ignored by Git.
Set `WAGGLE_ENV=production` for a real deployment; startup then fails if the
default password, device key, session secret, or secure cookie setting is unsafe.
Sessions expire after eight hours by default.

Browser-changing requests are restricted to the panel's own origin, while edge
devices without browser headers continue to authenticate with `X-Device-Key`.
The server also sends anti-framing, no-sniff, referrer, permissions, cache, and
content security headers for the local panel.

Repeated failed logins from the same client are limited to five attempts within
five minutes by default. `WAGGLE_LOGIN_MAX_ATTEMPTS` and
`WAGGLE_LOGIN_WINDOW_SECONDS` can adjust this local, in-memory protection.

The demo interface presents the technical hive identifiers with friendly names:
`H1` is Bahçe Kovanı, `H2` is Orman Kovanı, and `H3` is Deneme Kovanı. The
identifiers remain unchanged in the API contract used by edge devices.

Authenticated users can add hives from **Kovanlarım**. The server assigns the
next technical identifier automatically (`H4`, `H5`, and so on), while the user
only enters a friendly name and an optional location.

Hive names and locations can be edited later. Archiving removes a hive from the
live dashboard and blocks new events without deleting its historical data; an
archived hive can be restored from **Kovanlarım** at any time.

The **Alarmlar** view collects critical queenless-suspected events across all
hives. Open alarms can be acknowledged after a physical inspection and remain
available in the resolved history for traceability.

Authenticated panel users can download hives, all events, critical alarms, and
weekly reports from **Dışa Aktar**. CSV exports include a UTF-8 marker for Excel;
JSON exports preserve structured recommendation and hive identifier lists.

The same screen provides a live SQLite backup. It uses SQLite's online backup
API, so events may continue arriving while a consistent `.db` file is created.
The temporary server-side copy is removed after the download completes.

## Send an event from an edge device

Panel users authenticate with a browser session. Edge services use a separate
`X-Device-Key` that can only submit events and generated reports. Set a strong key on both the server
and device before deployment:

```bash
export WAGGLE_DEVICE_KEY="replace-with-a-long-random-key"
uvicorn panel.app.main:app --reload
```

Send a model result from another terminal:

```bash
export WAGGLE_DEVICE_KEY="replace-with-a-long-random-key"
python tools/send_event.py --hive H4 --event queenless_suspected --confidence 0.91
```

The client retries temporary failures and stores unsent events in
`.waggle_pending_events.jsonl`. On the next run it sends queued events first.
For local demos, both sides default to `waggle-device-demo`.

Python 3.10+ is recommended. Python 3.9 is supported through the conditional `eval_type_backport` dependency in `requirements.txt`.

Open <http://127.0.0.1:8000>. In a second terminal, activate the same environment and start the simulated event stream:

```bash
python tools/fake_events.py
```

To add a demo weekly report, run:

```bash
python tools/fake_report.py
```

The core product is offline-first. Online weather is disabled by default and no
coordinates are sent to a third party unless a user explicitly enables it in
**Ayarlar**. When enabled, configured `WAGGLE_LAT` and `WAGGLE_LON` coordinates
are sent to Open-Meteo and cached for ten minutes. `WAGGLE_LOCATION` controls
the user-facing label; weather failure never blocks hive monitoring.

The dashboard also includes a one-click demo scenario, client-side hive/event filters, and a dependency-free SVG confidence chart. The demo endpoint is intended for local presentation use only.

Critical events can be acknowledged from the event table, and recent weekly reports remain selectable in the report history control.

The API documentation is available at <http://127.0.0.1:8000/docs>. Run the panel tests with:

```bash
python -m unittest discover -s panel/tests -v
```
