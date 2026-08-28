import unittest

from pathlib import Path

import joblib
import numpy as np
import onnx

from ear.model_runtime import anomaly_flags, load_monitor

ROOT = Path(__file__).resolve().parents[2]
JOBLIB_MODEL = ROOT / "results" / "mendeley_isolation_monitor.joblib"
ONNX_MODEL = ROOT / "results" / "mendeley_isolation_monitor.onnx"

class OnnxRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.joblib_artifact = joblib.load(JOBLIB_MODEL)
        cls.onnx_artifact = load_monitor(ONNX_MODEL)

    def test_onnx_graph_and_metadata_are_valid(self):
        onnx.checker.check_model(onnx.load(ONNX_MODEL))

        self.assertEqual(
            self.onnx_artifact["feature_columns"],
            self.joblib_artifact["feature_columns"],
        )

        self.assertEqual(self.onnx_artifact["watch_windows"], 5)

        self.assertEqual(self.onnx_artifact["alarm_windows"], 30)

    def test_onnx_matches_joblib_decisions(self):
        rng = np.random.default_rng(42)

        scaler = self.joblib_artifact["scaler"]

        values = scaler.center_ + rng.normal(size = (256, 21)) * scaler.scale_

        expected = anomaly_flags(self.joblib_artifact, values)

        actual = anomaly_flags(self.onnx_artifact, values)

        np.testing.assert_array_equal(actual, expected)

if __name__ == "__main__":
    unittest.main()