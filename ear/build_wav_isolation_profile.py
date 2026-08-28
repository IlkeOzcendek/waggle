"""

It builds a hive specific Isolation Forest from healthy enrollment WAV files

"""

from pathlib import Path

import argparse # taking value using the terminal
import csv

from datetime import datetime

import joblib # getting the ML model that has been trained before
import numpy as np

from sklearn.ensemble import IsolationForest # A tree algo for detecting the anormalies
from sklearn.preprocessing import RobustScaler # outliers are gotten less effected

from wav_isolation_monitor import wav_features

def arguments(): # It defines the information will be given to the program from the terminal
    parser = argparse.ArgumentParser(description = __doc__)

    parser.add_argument("manifest", type = Path)
    parser.add_argument("--hive", required = True)
    parser.add_argument("--output", type = Path, required = True)
    parser.add_argument("--development-override", action = "store_true")

    return parser.parse_args()

def main():
    args = arguments()

    with args.manifest.open(newline = "", encoding = "utf-8") as stream: # Opens the CSV and converts in a usabe way
        rows = list(csv.DictReader(stream))

    selected = [
        row for row in rows if row["hive_id"] == args.hive

        and row["collection_phase"] == "enrollment"
        and row["queen_state"] == "queenright"
        and row["queen_confirmation"].strip()
    ]

    days = {datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00")).date() # In which days are the selected recordings

            for row in selected}
    hardware = {(row["device_id"], row["microphone_model"], row["microphone_position"])

                for row in selected}

    problems = []

    # -- ************* Is it usable enough to train the model ************* --

    if len(selected) < 42: problems.append(f"sessions={len(selected)}/42")

    if len(days) < 14: problems.append(f"days={len(days)}/14")

    if len(hardware) != 1: problems.append(f"hardware_configurations={len(hardware)}/1")

    if any(not row.get("temperature_c", "").strip() or
           not row.get("humidity_pct", "").strip() for row in selected):
        problems.append("missing temperature/humidity")

    if problems and not args.development_override:
        raise SystemExit("Profile is not production ready: " + "; ".join(problems))

    if problems:
        print(" ** WARNING development override: " + "; ** ".join(problems))

    if not selected:
        raise SystemExit(f" ** No confirmed queenright enrollment WAVs for hive {args.hive} **")

    matrices = []

    feature_names = None

    #  -- ********** Get the voice property of each rec ********** --

    for index, row in enumerate(selected, start = 1):
        values, names = wav_features(args.manifest.parent / row["file"])

        if feature_names is not None and names != feature_names:
            raise SystemExit("! * Feature schema changed between recordings * !")

        feature_names = names

        matrices.append(values)

        print(f"processed = {index}/{len(selected)} {row['file']}", flush = True)

        # ! Combine the proterties and train the Isolation Forest model !

    X = np.concatenate(matrices)

    scaler = RobustScaler().fit(X)
    model = IsolationForest(
        n_estimators = 500, contamination = 0.05, random_state = 42, n_jobs = -1
    ).fit(scaler.transform(X))

    artifact = {
        "scaler": scaler, "model": model, "feature_columns": feature_names,
        "hive_id": args.hive, "hardware": list(hardware),
        "training_days": sorted(map(str, days)),
        "enrollment_sessions": [row["session_id"] for row in selected],
        "watch_windows": 5, "alarm_windows": 30,
        "feature_protocol": "pyAudioAnalysis 1s/1s, 50ms/25ms, first 21 means",
    }

    args.output.parent.mkdir(parents = True, exist_ok = True)

    joblib.dump(artifact, args.output)

    print(f"profile={args.output}")

    print(f"hive = {args.hive} sessions = {len(selected)} days = {len(days)} windows = {len(X)}")

if __name__ == "__main__": # It says in case this Python file is executed directly run the main() function
    main()
