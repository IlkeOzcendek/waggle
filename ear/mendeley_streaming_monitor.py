"""

It trains and replays a persistent watch / alarm monitor on the sudden loss data

"""

from pathlib import Path

import json
import joblib

import numpy as np
import pandas as pd

from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler # for scaling features to be robust to outliers

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data" / "queen_loss_africanized_honeybee_dataset.csv"
MODEL = ROOT / "results" / "mendeley_isolation_monitor.joblib"
RESULT = ROOT / "results" / "mendeley_streaming_replay.json"

WATCH_WINDOWS = 5
ALARM_WINDOWS = 30

def first_completion(flags, required):
    run = 0

    for index, value in enumerate(flags, start = 1):
        run = run + 1 if value else 0

        if run >= required:
            return index

    return None

def longest_run(flags):
    run = maximum = 0

    for value in flags:
        run = run + 1 if value else 0

        maximum = max(maximum, run)

    return maximum


def main():
    data = pd.read_csv(DATA)

    days = sorted(data["date"].unique())

    columns = [column for column in data.columns if column not in ("date", "label")]

    X = data[columns].to_numpy(dtype = np.float64)

    train = data["date"].isin(days[:4]).to_numpy()

    scaler = RobustScaler().fit(X[train]) # (value - median) / IQR that it calculates the spread of the data getting less affected by outliers compared to StandardScaler; fit trains and transform scales the data to have median 0 and IQR 1

    model = IsolationForest( # to find outliers, tree structure
        n_estimators = 500, # number of trees in the forest
        contamination = 0.05, # estimates that 5% of the data are outliers, anormalies
        random_state = 42, # random seed for reproducibility
        n_jobs = -1 # uses all available CPU cores to speed up training
    ).fit(scaler.transform(X[train]))

    artifact = {
        "scaler": scaler, "model": model, "feature_columns": columns,
        "training_days": days[:4], "watch_windows": WATCH_WINDOWS,
        "alarm_windows": ALARM_WINDOWS,
        "source_doi": "10.17632/j97khfj656.1",
    }

    MODEL.parent.mkdir(parents = True, exist_ok = True)
    joblib.dump(artifact, MODEL) # saves the trained model and scaler to a file for later use

    replay = []

    for day in days[4:]:
        mask = data["date"].to_numpy() == day

        flags = model.predict(scaler.transform(X[mask])) == -1

        row = {
            "date": day, "label": str(data.loc[mask, "label"].iloc[0]),
            "windows": int(flags.size), "anomaly_fraction": float(flags.mean()),
            "longest_anomaly_run": int(longest_run(flags)),
            "watch_completion_window": first_completion(flags, WATCH_WINDOWS),
            "alarm_completion_window": first_completion(flags, ALARM_WINDOWS),
        }

        replay.append(row); print(row)

    output = { # creates a dictionary to store the replay results and metadata about the model and data
        "window_seconds": 1, "watch_rule": f"{WATCH_WINDOWS} consecutive anomalous windows",
        "alarm_rule": f"{ALARM_WINDOWS} consecutive anomalous windows",
        "replay": replay,
        "interpretation": "latency is measured from recording start, not queen-removal time",
    }

    RESULT.write_text(json.dumps(output, indent = 2) + "\n", encoding = "utf-8") # writes the replay results to a JSON file with pretty formatting that uses 2 spaces for indentation and a newline at the end
    print(f"model={MODEL}")
    print(f"result={RESULT}")

if __name__ == "__main__":
    main()