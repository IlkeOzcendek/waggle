import unittest

from pathlib import Path

import joblib
import numpy as np
import onnx

from ear.model_runtime import _validated_metadata, anomaly_flags, load_monitor, severity_profile, window_decisions

ROOT = Path(__file__).resolve().parents[2]
JOBLIB_MODEL = ROOT / "results" / "mendeley_isolation_monitor.joblib"
ONNX_MODEL = ROOT / "results" / "mendeley_isolation_monitor.onnx"

class OnnxRuntimeTest(unittest.TestCase): # The system tests that the model converted from Joblib to ONNX remains intact that uses the same features and retains the WATCH =5 / ALARM =30 settings
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

    def test_onnx_matches_joblib_decisions(self): # It feeds the same 256 samples into both the original Joblib model and the model converted to ONNX and checks if the results are exactly the same
        rng = np.random.default_rng(42)

        scaler = self.joblib_artifact["scaler"]

        values = scaler.center_ + rng.normal(size = (256, 21)) * scaler.scale_

        expected = anomaly_flags(self.joblib_artifact, values)

        actual = anomaly_flags(self.onnx_artifact, values)

        np.testing.assert_array_equal(actual, expected)

    def test_onnx_scores_match_the_joblib_decision_function(self): # The graph has always returned a score beside the label, and it is only trustworthy if it is the same number the estimator computes
        rng = np.random.default_rng(7)

        scaler = self.joblib_artifact["scaler"]

        values = scaler.center_ + rng.normal(size = (256, 21)) * scaler.scale_

        expected = self.joblib_artifact["model"].decision_function(scaler.transform(values))

        _, actual = window_decisions(self.onnx_artifact, values)

        # The graph runs in float32 where the estimator runs in float64, so they agree to
        # a rounding difference rather than exactly.
        np.testing.assert_allclose(actual, expected, atol = 1e-3)

    def test_runtime_requests_outputs_by_name(self):
        class Session:
            def get_inputs(self):
                return [type("Node", (), {"name": "features"})()]

            def run(self, names, _feeds):
                self.names = names
                return np.array([[-1], [1]]), np.array([[-0.2], [0.1]])

        session = Session()
        artifact = {"feature_columns": ["a"], "_onnx_session": session}
        flags, scores = window_decisions(artifact, np.array([[1.0], [2.0]]))

        self.assertEqual(session.names, ["label", "scores"])
        np.testing.assert_array_equal(flags, [True, False])
        np.testing.assert_allclose(scores, [-0.2, 0.1])

    def test_feature_matrix_shape_and_values_are_checked_before_inference(self):
        for values in (np.zeros((2, 20)), np.full((2, 21), np.nan)):
            with self.subTest(shape=values.shape):
                with self.assertRaises(ValueError):
                    window_decisions(self.onnx_artifact, values)


class OnnxContractTest(unittest.TestCase):
    class Node:
        def __init__(self, name, shape, type_):
            self.name = name
            self.shape = shape
            self.type = type_

    class Meta:
        def __init__(self, values):
            self.custom_metadata_map = values

    class Session:
        def __init__(self, metadata, width=2, outputs=None):
            self.metadata = metadata
            self.width = width
            self.outputs = outputs

        def get_modelmeta(self):
            return OnnxContractTest.Meta(self.metadata)

        def get_inputs(self):
            return [OnnxContractTest.Node("features", [None, self.width], "tensor(float)")]

        def get_outputs(self):
            return self.outputs or [
                OnnxContractTest.Node("label", [None, 1], "tensor(int64)"),
                OnnxContractTest.Node("scores", [None, 1], "tensor(float)"),
            ]

    @staticmethod
    def metadata(**overrides):
        values = {
            "waggle.feature_columns": '["a", "b"]',
            "waggle.watch_windows": "5",
            "waggle.alarm_windows": "30",
            "waggle.score_offset": "-0.5",
        }
        values.update(overrides)
        return values

    def test_valid_contract_is_parsed(self):
        contract = _validated_metadata(self.Session(self.metadata()))
        self.assertEqual(contract["feature_columns"], ["a", "b"])

    def test_bad_metadata_and_thresholds_are_rejected(self):
        cases = (
            {"waggle.feature_columns": "not-json"},
            {"waggle.feature_columns": '["a", "a"]'},
            {"waggle.watch_windows": "0"},
            {"waggle.watch_windows": "31", "waggle.alarm_windows": "30"},
            {"waggle.score_offset": "nan"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    _validated_metadata(self.Session(self.metadata(**overrides)))

    def test_input_width_and_named_outputs_are_required(self):
        with self.assertRaisesRegex(ValueError, "input width"):
            _validated_metadata(self.Session(self.metadata(), width=3))

        outputs = [self.Node("output0", [None, 1], "tensor(int64)")]
        with self.assertRaisesRegex(ValueError, "label and scores"):
            _validated_metadata(self.Session(self.metadata(), outputs=outputs))

class SeverityTest(unittest.TestCase): # Severity says how far a window fell outside the profile, where the anomaly fraction says only how many did
    @classmethod
    def setUpClass(cls):
        cls.artifact = load_monitor(ONNX_MODEL)

    def test_the_exported_profile_carries_the_offset_severity_needs(self):
        self.assertIsNotNone(self.artifact["score_offset"])

    def test_a_deeper_deviation_scores_higher_than_a_shallow_one(self):
        shallow = severity_profile(self.artifact, np.array([-0.01, -0.02]))
        deep = severity_profile(self.artifact, np.array([-0.30, -0.40]))

        self.assertLess(shallow["anomaly_severity"], deep["anomaly_severity"])
        self.assertLess(deep["peak_severity"], 1.0)

    def test_normal_windows_carry_no_severity(self):
        calm = severity_profile(self.artifact, np.array([0.05, 0.12]))

        self.assertEqual(calm["anomaly_severity"], 0.0)
        self.assertEqual(calm["peak_severity"], 0.0)

    def test_the_mean_covers_the_anomalous_windows_only(self): # Averaging in the normal windows would report a milder period simply because it was mostly quiet, which the anomaly fraction already says
        mostly_calm = severity_profile(self.artifact, np.array([0.1, 0.1, 0.1, -0.30]))
        only_deep = severity_profile(self.artifact, np.array([-0.30]))

        self.assertAlmostEqual(mostly_calm["anomaly_severity"], only_deep["anomaly_severity"])

    def test_a_profile_without_the_offset_reports_no_severity(self): # A hive profile exported before the offset was recorded still classifies its windows; it simply cannot say how deep they were
        older = dict(self.artifact, score_offset = None)

        self.assertEqual(
            severity_profile(older, np.array([-0.30])),
            {"anomaly_severity": None, "peak_severity": None},
        )

if __name__ == "__main__":
    unittest.main()
