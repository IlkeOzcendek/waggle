<div align="center">
  <img src="./assets/waggle-banner-v9.gif" width="100%" alt="Waggle acoustic hive monitoring banner with fast independently moving original golden audio levels" />
</div>

<h1 align="center">One hive. Its own baseline. An early warning when the sound changes.</h1>

<p align="center">
  Waggle is a colony-specific acoustic monitor designed to detect persistent
  changes compatible with queen loss.
</p>

<p align="center">
  <a href="#current-evidence">Evidence</a> ·
  <a href="#processing-flow">How it works</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#reproduce-the-mendeley-replay">Reproduce</a>
</p>

<table>
  <tr>
    <th width="33%">LEARN</th>
    <th width="33%">LISTEN</th>
    <th width="33%">WARN</th>
  </tr>
  <tr>
    <td align="center">Builds a normal profile from confirmed healthy recordings</td>
    <td align="center">Compares each new second with that hive's own acoustic baseline</td>
    <td align="center">Escalates only when the acoustic change persists</td>
  </tr>
</table>

## Current evidence

<table>
  <tr>
    <th width="25%">Held-out accuracy</th>
    <th width="25%">Queen-loss sensitivity</th>
    <th width="25%">Healthy specificity</th>
    <th width="25%">Persistent alarm</th>
  </tr>
  <tr>
    <td align="center"><strong>94.17%</strong></td>
    <td align="center"><strong>100%</strong></td>
    <td align="center"><strong>88.33%</strong></td>
    <td align="center"><strong>30 seconds</strong></td>
  </tr>
</table>

The strongest result uses the public [Mendeley sudden queen-loss
dataset](https://data.mendeley.com/datasets/j97khfj656/1) (DOI
`10.17632/j97khfj656.1`): six complete days from one colony, with queen removal
on the morning of the final day.

| Evaluation stage | Data used | Outcome |
| --- | --- | --- |
| Healthy-profile training | Queenright days 1–4 | Baseline learned |
| Untouched validation | Queenright day 5 | No persistent alarm |
| Untouched test | Queenless day 6 | `WATCH` at 5 s, `ALARM` at 30 s |

> **What the alarm means**<br/>
> Persistent acoustic change compatible with queen loss was detected. Check
> the hive and queen.

An alarm is not proof that the queen has died. Disease, swarming, environmental
noise, microphone movement, and other colony stresses can also alter hive
acoustics. The 94.17% result demonstrates a colony-specific change detector on
one published feature dataset—not universal performance on arbitrary raw WAV
recordings or unseen hives. In a separate grouped AI-BELHA raw-WAV experiment,
generic queen-state classification reached 53.33% balanced accuracy.

## Processing flow

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontFamily": "Arial", "lineColor": "#d79a43"}}}%%
flowchart LR
    A["Confirmed healthy<br/>WAV recordings"] --> B["Hive-specific<br/>normal profile"]
    C["New hive audio"] --> D["One-second<br/>acoustic features"]
    B --> E{"Isolation Forest<br/>anomaly decision"}
    D --> E

    E -->|within profile| N["NORMAL"]
    E -->|anomalous| W["WATCH<br/>after 5 seconds"]
    W -->|sound recovers| N
    W -->|change persists| L["ALARM<br/>after 30 seconds"]

    N --> G["Timestamped<br/>CSV event log"]
    W --> G
    L --> G

    classDef source fill:#07182b,stroke:#d79a43,color:#f6c36f,stroke-width:2px;
    classDef process fill:#0b2239,stroke:#c58a38,color:#f4f0e8,stroke-width:2px;
    classDef decision fill:#132d46,stroke:#f0ad4e,color:#ffffff,stroke-width:2px;
    classDef normal fill:#12372a,stroke:#54b883,color:#ffffff,stroke-width:2px;
    classDef watch fill:#493817,stroke:#e4ad45,color:#ffffff,stroke-width:2px;
    classDef alarm fill:#4b2025,stroke:#e06b75,color:#ffffff,stroke-width:2px;
    classDef log fill:#171f2d,stroke:#8495a8,color:#ffffff,stroke-width:2px;

    class A,C source;
    class B,D process;
    class E decision;
    class N normal;
    class W watch;
    class L alarm;
    class G log;
```

Raw WAV processing uses mono 16-bit PCM audio, resamples to 16 kHz when
necessary, and extracts 21 pyAudioAnalysis features with 50 ms windows, 25 ms
steps, and one-second aggregation.

## Quick start

Python 3.9 or newer is recommended.

### 1. Create the environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2. Reproduce the Mendeley replay

Download the Mendeley CSV and place it at:

```text
data/queen_loss_africanized_honeybee_dataset.csv
```

Run:

```bash
python ear/mendeley_streaming_monitor.py
```

Expected replay:

```text
queenright validation day: no alarm
queenless test day: WATCH at window 5, ALARM at window 30
```

The command writes:

```text
results/mendeley_isolation_monitor.joblib
results/mendeley_streaming_replay.json
```

### 3. Build a development WAV profile

First ingest a confirmed healthy WAV:

```bash
python ear/add_field_recording.py healthy.wav \
  --field-dir data/field \
  --timestamp 2026-09-14T12:00:00+03:00 \
  --site SITE01 --hive HIVE03 --device DEV01 \
  --microphone "microphone-model" --position "fixed-position" \
  --temperature 25 --humidity 60 --inspection queen_present
```

For a software demonstration with insufficient enrollment data:

```bash
python ear/build_wav_isolation_profile.py data/field/manifest.csv \
  --hive HIVE03 --output results/HIVE03_isolation.joblib \
  --development-override
```

`--development-override` profiles are for software testing only. Production
profile creation requires at least 42 confirmed healthy sessions across 14
days, one fixed hardware configuration, and complete temperature/humidity
metadata.

### 4. Monitor a WAV folder

```bash
mkdir -p inbox events
python ear/monitor_wav_folder.py \
  results/HIVE03_isolation.joblib inbox \
  --state events/HIVE03_state.json \
  --log events/HIVE03_events.csv \
  --watch --poll-seconds 5
```

Stop continuous monitoring with `Control-C`. Processed filenames and SHA-256
hashes are retained so unchanged files are not analyzed twice.

## Repository map

| Path | Purpose |
| --- | --- |
| `ear/mendeley_streaming_monitor.py` | Reproduce the sudden queen-loss replay |
| `ear/wav_isolation_monitor.py` | Score a single WAV recording |
| `ear/build_wav_isolation_profile.py` | Build a hive-specific healthy profile |
| `ear/monitor_wav_folder.py` | Continuously process incoming WAV files |
| `ear/add_field_recording.py` | Ingest a recording with field metadata |
| `ear/validate_field_manifest.py` | Check metadata and profile readiness |
| `data/` | Local datasets; excluded from Git |
| `results/` | Selected model artifact and evaluation metrics |
| [`docs/FIELD_PROTOCOL.md`](docs/FIELD_PROTOCOL.md) | Field recording and enrollment protocol |

## Research pipeline ready

The acoustic monitoring pipeline is complete and reproducible from profile
creation to persistent alarm generation.

| Capability | Result |
| --- | --- |
| Sudden queen-loss replay | Reproduces the held-out validation and test results |
| Raw-WAV processing | Resampling and one-second acoustic feature extraction operational |
| Hive enrollment | Builds a personal healthy baseline from labeled recordings |
| Persistent monitoring | Produces `NORMAL`, `WATCH`, and `ALARM` states |
| Continuous operation | Monitors incoming WAV files without duplicate processing |
| Event output | Writes timestamped, integration-ready CSV records |

This repository provides the tested acoustic detection layer that can feed an
application interface, local report generator, or notification service. Its
validated claim remains precise: Waggle detects persistent change relative to
a hive's learned healthy acoustic profile; an alarm requests inspection rather
than declaring queen death as a certainty.

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

Python 3.10+ is recommended. Python 3.9 is supported through the conditional
`eval_type_backport` dependency in `requirements.txt`.

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

The panel supports dynamic hive management, alarm acknowledgement, CSV/JSON
exports, SQLite backup and restore, system-health monitoring, and authenticated
local access. Development credentials are for local demonstration only.

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

Open <http://127.0.0.1:8000>. In a second terminal, activate the same
environment and start the simulated event stream:

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

The dashboard includes a one-click demo scenario, client-side hive/event
filters, and a dependency-free SVG confidence chart. The demo endpoint and
fake-event tools are intended for local presentation use only.

Critical events can be acknowledged from the event table, and recent weekly
reports remain selectable in the report history control.

The API documentation is available at <http://127.0.0.1:8000/docs>. Run the
panel tests with:

```bash
python -m unittest discover -s panel/tests -v
```

Pull requests automatically run the panel suite on Python 3.9 and 3.11, compile
all Python modules, and validate both JavaScript entry points. The PR template
also checks the frozen event contract, secret handling, UI verification, and
recovery notes before review.

The panel supports keyboard navigation with a skip link, visible focus states,
focus transfer between views, current-page navigation announcements, labeled
tables and restore controls, live system status announcements, and reduced-motion
preferences.

Session tokens are also required to use their canonical URL-safe encoding, so
alternate textual encodings of the same signed bytes are rejected.

---

<p align="center">
  <strong>Waggle</strong><br/>
  Listen for what the hive cannot say.<br/><br/>
  Built for the Microsoft AI Innovators Summer Program 2026.
</p>
