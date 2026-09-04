"""

It exports a Waggle joblib monitor to ONNX and verify decision parity

"""

from __future__ import annotations

from pathlib import Path

import argparse
import json
import joblib
import numpy as np
import onnx
import onnxruntime as ort
import pandas as pd

from sklearn.pipeline import Pipeline
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType

def arguments(): # The system checks which Joblib model is coming from the terminal, where the output should be generated, verifies if there is a validation CSV and retrieves information on where the report should be written
    parser = argparse.ArgumentParser(description = __doc__)

    parser.add_argument("joblib_model", type = Path)
    parser.add_argument("output", type = Path)
    parser.add_argument("--verification-csv", type = Path)
    parser.add_argument("--report", type = Path)

    return parser.parse_args()

def export_model(artifact, output: Path): # After creating a single pipeline with RobustScaler and IsolationForest and converting it to ONNX it places the feature, WATCH, ALARM, hive information as metadata into ONNX and saves the .onnx file
    feature_count = len(artifact["feature_columns"])

    pipeline = Pipeline([
        ("scaler", artifact["scaler"]),
        ("model", artifact["model"]),
    ])

    model = convert_sklearn(
        pipeline,
        initial_types = [("features", FloatTensorType([None, feature_count]))],
        target_opset = {"": 17, "ai.onnx.ml": 3},
    )

    metadata = {
        "feature_columns": artifact["feature_columns"],
        "watch_windows": artifact["watch_windows"],
        "alarm_windows": artifact["alarm_windows"],
        "hive_id": artifact.get("hive_id") or "",
        "source_doi": artifact.get("source_doi") or "",
        # The decision score's deepest possible value is -1 - offset_, because the raw
        # isolation score never falls below -1. Carrying the offset is therefore what lets
        # inference turn a score into "how far past the boundary this window sits" once the
        # estimator itself is gone and only the graph remains.
        "score_offset": float(artifact["model"].offset_),
    }

    for key, value in metadata.items():
        entry = model.metadata_props.add()

        entry.key = f"waggle.{key}"

        entry.value = json.dumps(value) if isinstance(value, list) else str(value)

    output.parent.mkdir(parents = True, exist_ok = True)

    onnx.save_model(model, output)

# The graph runs in float32 where the estimator runs in float64, so the two scores agree
# to about a ten-thousandth rather than exactly. Anything looser than this is a conversion
# fault, not a rounding difference.
SCORE_TOLERANCE = 1e-2

def verify(artifact, onnx_path: Path, csv_path: Path): # It feeds the same CSV data to the Joblib model and then to the ONNX model, compares both the decisions and the scores behind them and accepts the conversion as verified=True only when neither has drifted
    data = pd.read_csv(csv_path)

    values = data[artifact["feature_columns"]].to_numpy(dtype = np.float64)

    scaled = artifact["scaler"].transform(values)

    expected = artifact["model"].predict(scaled)

    # The severity the panel reports is read off this score, so parity of the labels alone
    # no longer covers what the exported graph is used for.
    expected_scores = artifact["model"].decision_function(scaled)

    session = ort.InferenceSession(str(onnx_path), providers = ["CPUExecutionProvider"])

    actual, actual_scores = session.run(
        ["label", "scores"],
        {session.get_inputs()[0].name: values.astype(np.float32)},
    )

    actual = np.asarray(actual).reshape(-1)

    actual_scores = np.asarray(actual_scores).reshape(-1)

    differences = int(np.count_nonzero(expected != actual))

    score_drift = float(np.abs(expected_scores - actual_scores).max())

    return {
        "verification_rows": int(len(values)),
        "different_decisions": differences,
        "decision_agreement": float(np.mean(expected == actual)),
        "maximum_score_difference": score_drift,
        "verified": differences == 0 and score_drift <= SCORE_TOLERANCE,
    }

def main():
    args = arguments()

    artifact = joblib.load(args.joblib_model)

    export_model(artifact, args.output)

    # ** ONNX generates a conversion report, compares the Joblib and ONNX results if a validation CSV is available, stops the program if there is a discrepancy and saves the report to a JSON file if requested

    report = {
        "source_model": str(args.joblib_model),
        "onnx_model": str(args.output),
        "feature_count": len(artifact["feature_columns"]),
        "onnx_bytes": args.output.stat().st_size,
    }

    if args.verification_csv:
        report.update(verify(artifact, args.output, args.verification_csv))

        if not report["verified"]:
            raise SystemExit(" - ! ONNX decision parity verification failed - ! ")
        
    if args.report:
        args.report.parent.mkdir(parents = True, exist_ok = True)

        args.report.write_text(json.dumps(report, indent = 2) + "\n", encoding = "utf-8")

    print(json.dumps(report, indent = 2))

if __name__ == "__main__":
    main()
