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
