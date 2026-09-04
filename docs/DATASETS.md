# Datasets and evaluation

This document records which external data supports Waggle's published result,
how it is split, what the reported metrics mean and which artefacts reproduce
the result. It is deliberately narrower than a general claim of queen-state
classification.

## Mendeley sudden queen-loss dataset

- Source: [A dataset of the sounds produced by a colony of Africanized honeybees
  during a sudden queen loss event](https://data.mendeley.com/datasets/j97khfj656/1)
- DOI: `10.17632/j97khfj656.1`
- Dataset license recorded by the project: CC BY 4.0
- Local input: `data/queen_loss_africanized_honeybee_dataset.csv`
- Scope used by Waggle: six complete days from one colony, 900 one-second rows
  per day and 21 acoustic features per row

The source CSV is not committed. The repository's `data/` directory is ignored;
users must obtain the dataset under its original terms.

## Fixed chronological split

| Role | Dates | Colony state | Rows |
| --- | --- | --- | ---: |
| Healthy-profile training | 2019-08-26 to 2019-08-29 | Queenright | 3,600 |
| Held-out validation | 2019-08-30 | Queenright | 900 |
| Held-out test | 2019-09-02 | Queenless | 900 |

The split is chronological. The held-out days are not used to fit the
`RobustScaler` or `IsolationForest`.

## Model and persistence rules

- Preprocessing: `RobustScaler`
- Detector: `IsolationForest`
- Trees: 500
- Contamination: 0.05
- Random seed: 42
- `WATCH`: 5 consecutive anomalous one-second windows
- `ALARM`: 30 consecutive anomalous one-second windows

## Reported outcome

| Measure | Value | Definition |
| --- | ---: | --- |
| Healthy specificity | 88.33% | Fraction of held-out healthy-day windows classified as normal |
| Queen-loss sensitivity | 100% | Fraction of held-out queenless-day windows classified as anomalous |
| Balanced accuracy proxy | 94.17% | `(specificity + sensitivity) / 2` across the two held-out days |
| Queenless persistent alert | 30 s | First completion of 30 consecutive anomalous windows from recording start |

The healthy validation recording contains a seven-window anomaly run and can
therefore enter `WATCH`; it never reaches `ALARM`. The queenless recording is
anomalous for all 900 windows. Alert latency is measured from the beginning of
the recording, not from the time the queen was removed.

This result demonstrates a colony-specific change detector on one published
feature dataset. It does not establish universal accuracy on unseen colonies,
microphones, environments, raw WAV files or causes of acoustic change.

## Reproduction and auditable artefacts

After downloading the source CSV to the local input path, run:

```bash
python ear/mendeley_streaming_monitor.py
```

The checked-in evidence is:

| Artefact | Purpose |
| --- | --- |
| `results/mendeley_sudden_loss_holdout.json` | Split, candidates and held-out window metrics |
| `results/mendeley_streaming_replay.json` | Persistent `WATCH` / `ALARM` replay |
| `results/mendeley_isolation_monitor.joblib` | Fitted Python pipeline |
| `results/mendeley_isolation_monitor.onnx` | Portable inference graph |
| `results/mendeley_onnx_parity.json` | Python-versus-ONNX comparison on all 5,400 rows |

The parity report records zero decision differences. Its maximum score
difference is `0.00030409904524109077`, below the exporter's `0.01` tolerance.
Parity therefore means exact agreement of decisions plus bounded score drift,
not bit-identical floating-point scores.

## Field enrollment data

Prospective hive data is local and hive-specific; it is not included in the
repository. Production enrollment requires at least 42 confirmed healthy
sessions across 14 distinct days and four accepted field-health confirmations,
using one fixed recording configuration. See
[`FIELD_PROTOCOL.md`](FIELD_PROTOCOL.md) for capture, metadata and inspection
requirements.

Uploaded raw WAV audio is converted to feature windows and then deleted by the
panel. Operators remain responsible for consent, retention, backups and any
separately retained source recordings.
