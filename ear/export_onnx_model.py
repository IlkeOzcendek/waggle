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

def arguments():
    parser = argparse.ArgumentParser(description = __doc__)

    parser.add_argument("joblib_model", type = Path)
    parser.add_argument("output", type = Path)
    parser.add_argument("--verification-csv", type = Path)
    parser.add_argument("--report", type = Path)

    return parser.parse_args()

def export_model(artifact, output: Path):
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
    }

    for key, value in metadata.items():
        entry = model.metadata_props.add()

        entry.key = f"waggle.{key}"

        entry.value = json.dumps(value) if isinstance(value, list) else str(value)

    output.parent.mkdir(parents = True, exist_ok = True)

    onnx.save_model(model, output)

def verify(artifact, onnx_path: Path, csv_path: Path):
    data = pd.read_csv(csv_path)

    values = data[artifact["feature_columns"]].to_numpy(dtype = np.float64)

    expected = artifact["model"].predict(artifact["scaler"].transform(values))

    session = ort.InferenceSession(str(onnx_path), providers = ["CPUExecutionProvider"])

    actual = session.run(
        [session.get_outputs()[0].name],
        {session.get_inputs()[0].name: values.astype(np.float32)},
    )[0].reshape(-1)

    differences = int(np.count_nonzero(expected != actual))

    return {
        "verification_rows": int(len(values)),
        "different_decisions": differences,
        "decision_agreement": float(np.mean(expected == actual)),
        "verified": differences == 0,
    }

def main():
    args = arguments()

    artifact = joblib.load(args.joblib_model)

    export_model(artifact, args.output)

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