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

## Run the panel locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn panel.app.main:app --reload
```

Open <http://127.0.0.1:8000> and sign in with the local demo account:

- Username: `admin`
- Password: `waggle-demo`

Set `WAGGLE_ADMIN_USERNAME`, `WAGGLE_ADMIN_PASSWORD`, and `WAGGLE_SESSION_SECRET`
before a real deployment. Sessions expire after eight hours by default.

The demo interface presents the technical hive identifiers with friendly names:
`H1` is Bahçe Kovanı, `H2` is Orman Kovanı, and `H3` is Deneme Kovanı. The
identifiers remain unchanged in the API contract used by edge devices.

Python 3.10+ is recommended. Python 3.9 is supported through the conditional `eval_type_backport` dependency in `requirements.txt`.

Open <http://127.0.0.1:8000>. In a second terminal, activate the same environment and start the simulated event stream:

```bash
python tools/fake_events.py
```

To add a demo weekly report, run:

```bash
python tools/fake_report.py
```

Weather defaults to the demo hive location. Override it with `WAGGLE_LAT`, `WAGGLE_LON`, and `WAGGLE_LOCATION` before starting the server.

The dashboard also includes a one-click demo scenario, client-side hive/event filters, and a dependency-free SVG confidence chart. The demo endpoint is intended for local presentation use only.

Critical events can be acknowledged from the event table, and recent weekly reports remain selectable in the report history control.

The API documentation is available at <http://127.0.0.1:8000/docs>. Run the panel tests with:

```bash
python -m unittest discover -s panel/tests -v
```
