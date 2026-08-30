"""

It trains and verifies a hive specific Isolation Forest and ONNX monitor

"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np

from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

from .export_onnx_model import export_model
from .model_runtime import anomaly_flags, load_monitor

def train_verified_profile( # After checking the data and ensuring there are at least 42 windows it trains RobustScaler and IsolationForest, saving Joblib, converting it to ONNX and verifying if the two models make the same decisions, it passes them to the actual files if they are the same and rejects them if not
    values: np.ndarray,
    feature_names: list[str],
    hive_id: str,
    joblib_path: Path,
    onnx_path: Path,
    *,
    n_estimators: int = 500,
) -> dict[str, object]:
    values = np.asarray(values, dtype = np.float64)
    
    if values.ndim != 2 or values.shape[1] != len(feature_names) or not np.isfinite(values).all():
        raise ValueError("Öğrenme matrisi geçerli değil")
    
    if len(values) < 42:
        raise ValueError("Model eğitimi için yeterli ses penceresi yok")

    scaler = RobustScaler().fit(values)

    model = IsolationForest(
        n_estimators = n_estimators, contamination = 0.05, random_state = 42, n_jobs = -1
    ).fit(scaler.transform(values))

    artifact = {
        "scaler": scaler,
        "model": model,
        "feature_columns": list(feature_names),
        "hive_id": hive_id,
        "watch_windows": 5,
        "alarm_windows": 30,
        "feature_protocol": "pyAudioAnalysis 1s/1s, 50ms/25ms, first 21 means",
    }

    joblib_path.parent.mkdir(parents = True, exist_ok = True)

    onnx_path.parent.mkdir(parents = True, exist_ok = True)

    temporary_joblib = joblib_path.with_suffix(joblib_path.suffix + ".tmp")
    temporary_onnx = onnx_path.with_name(onnx_path.stem + ".tmp.onnx")

    try:
        joblib.dump(artifact, temporary_joblib)

        export_model(artifact, temporary_onnx)

        expected = model.predict(scaler.transform(values)) == -1

        actual = anomaly_flags(load_monitor(temporary_onnx), values)

        differences = int(np.count_nonzero(expected != actual))

        if differences:
            raise ValueError(f"ONNX karar eşleşmesi başarısız: {differences} farklı karar")
        
        temporary_joblib.replace(joblib_path)

        temporary_onnx.replace(onnx_path)

    finally:
        temporary_joblib.unlink(missing_ok = True)
        temporary_onnx.unlink(missing_ok = True)

    return {
        "hive_id": hive_id,
        "windows": int(len(values)),
        "features": int(values.shape[1]),
        "different_decisions": 0,
        "joblib_model": str(joblib_path),
        "onnx_model": str(onnx_path),
    }