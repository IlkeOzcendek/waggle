from pathlib import Path

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
)


PROCESSED_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
)

HEALTHY_ID = 0
QUEENLESS_ID = 1

EXPERIMENTS = [
    (
        "All hives CNN",
        PROCESSED_DIR
        / "waggle_oof_predictions.npz",
    ),
    (
        "All hives standardized CNN",
        PROCESSED_DIR
        / "waggle_oof_predictions_standardized.npz",
    ),
    (
        "NU-Hive CNN",
        PROCESSED_DIR
        / "waggle_oof_predictions_nuhive_baseline.npz",
    ),
    (
        "NU-Hive Logistic Regression",
        PROCESSED_DIR
        / "waggle_oof_predictions_nuhive_logistic.npz",
    ),
    (
        "NU-Hive hive CV CMVN",
        PROCESSED_DIR
        / "waggle_oof_predictions_nuhive_hive_cmvn.npz",
    ),
    (
        "NU-Hive session CV fixed",
        PROCESSED_DIR
        / "waggle_oof_predictions_nuhive_session_fixed.npz",
    ),
    (
        "NU-Hive session CV CMVN",
        PROCESSED_DIR
        / "waggle_oof_predictions_nuhive_session_cmvn.npz",
    ),
    (
        "All hives hive CV CMVN",
        PROCESSED_DIR
        / "waggle_oof_predictions_all_hive_cmvn.npz",
    ),
    (
        "All hives session CV fixed",
        PROCESSED_DIR
        / "waggle_oof_predictions_all_session_fixed.npz",
    ),
    (
        "All hives session CV CMVN",
        PROCESSED_DIR
        / "waggle_oof_predictions_all_session_cmvn.npz",
    ),
    (
        "AST probe session CV",
        PROCESSED_DIR
        / "waggle_oof_predictions_all_session_ast.npz",
    ),
    (
        "AST probe hive CV",
        PROCESSED_DIR
        / "waggle_oof_predictions_all_hive_ast.npz",
    ),
    (
        "AST probe dataset CV",
        PROCESSED_DIR
        / "waggle_oof_predictions_all_dataset_ast.npz",
    ),
]

# diagnose_confound.py writes these. They hold the number of correctly
# decided recordings for every possible relabelling of the recordings,
# which is the noise band that every result above has to beat
NULL_DISTRIBUTIONS = [
    (
        "NU-Hive",
        PROCESSED_DIR
        / "waggle_permutation_null_nuhive.npz",
    ),
    (
        "All hives",
        PROCESSED_DIR
        / "waggle_permutation_null_all.npz",
    ),
    (
        "All hives AST",
        PROCESSED_DIR
        / "waggle_permutation_null_all_embedding.npz",
    ),
]


def load_experiment(
    name,
    path,
):
    """

    It loads and validates one saved experiment

    """

    if not path.exists():
        raise FileNotFoundError(
            f"Prediction file for {name} "
            f"does not exist -- {path}"
        )

    with np.load(
        path,
        allow_pickle = False,
    ) as dataset:
        required_arrays = {
            "y_true",
            "y_pred",
            "queenless_probability",
            "hive_ids",
            "session_ids",
            "fold_ids",
        }

        available_arrays = set(
            dataset.files
        )

        missing_arrays = (
            required_arrays
            - available_arrays
        )

        if missing_arrays:
            raise ValueError(
                f"{name} is missing arrays: "
                f"{sorted(missing_arrays)}"
            )

        y_true = dataset[
            "y_true"
        ].astype(
            np.int64,
            copy = False,
        )

        y_pred = dataset[
            "y_pred"
        ].astype(
            np.int64,
            copy = False,
        )

        probabilities = dataset[
            "queenless_probability"
        ].astype(
            np.float32,
            copy = False,
        )

        hive_ids = dataset["hive_ids"]
        session_ids = dataset["session_ids"]

        fold_ids = dataset[
            "fold_ids"
        ].astype(
            np.int64,
            copy = False,
        )

    expected_count = len(y_true)

    arrays = {
        "y_pred": y_pred,
        "probabilities": probabilities,
        "hive_ids": hive_ids,
        "session_ids": session_ids,
        "fold_ids": fold_ids,
    }

    for array_name, values in arrays.items():
        if len(values) != expected_count:
            raise ValueError(
                f"{name}: {array_name} has "
                f"{len(values)} values, expected "
                f"{expected_count}"
            )

    valid_labels = {
        HEALTHY_ID,
        QUEENLESS_ID,
    }

    true_labels = set(
        np.unique(y_true).tolist()
    )

    predicted_labels = set(
        np.unique(y_pred).tolist()
    )

    if not true_labels.issubset(
        valid_labels
    ):
        raise ValueError(
            f"{name} has unexpected true labels: "
            f"{true_labels}"
        )

    if not predicted_labels.issubset(
        valid_labels
    ):
        raise ValueError(
            f"{name} has unexpected predictions: "
            f"{predicted_labels}"
        )

    if np.any(
        (probabilities < 0.0)
        | (probabilities > 1.0)
    ):
        raise ValueError(
            f"{name} contains invalid probabilities"
        )

    return {
        "name": name,
        "path": path,
        "y_true": y_true,
        "y_pred": y_pred,
        "probabilities": probabilities,
        "hive_ids": hive_ids,
        "session_ids": session_ids,
        "fold_ids": fold_ids,
    }


def safe_balanced_accuracy(
    y_true,
    y_pred,
):
    """

    It returns balanced accuracy only when the test data has both classes

    """

    unique_labels = np.unique(
        y_true
    )

    if len(unique_labels) < 2:
        return None

    return balanced_accuracy_score(
        y_true,
        y_pred,
    )


def format_metric(value):
    """

    It formats a metric or returns N/A when the metric is not valid

    """

    if value is None:
        return "N/A"

    return f"{value:.4f}"


def calculate_fold_results(
    experiment,
):
    """

    It calculates one result for every unseen physical hive

    """

    y_true = experiment["y_true"]
    y_pred = experiment["y_pred"]
    hive_ids = experiment["hive_ids"]
    fold_ids = experiment["fold_ids"]

    fold_results = []

    for fold_id in np.unique(
        fold_ids
    ):
        mask = fold_ids == fold_id

        test_hives = np.unique(
            hive_ids[mask]
        )

        # A leave one dataset out fold holds several hives at once, so
        # the fold is named after the group rather than a single hive
        test_hive = (
            str(test_hives[0])
            if len(test_hives) == 1
            else f"{len(test_hives)} hives"
        )

        fold_accuracy = accuracy_score(
            y_true[mask],
            y_pred[mask],
        )

        fold_balanced_accuracy = (
            safe_balanced_accuracy(
                y_true[mask],
                y_pred[mask],
            )
        )

        test_labels = np.unique(
            y_true[mask]
        )

        fold_results.append(
            {
                "fold_id": int(fold_id),
                "test_hive": test_hive,
                "clip_count": int(
                    np.sum(mask)
                ),
                "class_count": len(
                    test_labels
                ),
                "accuracy": fold_accuracy,
                "balanced_accuracy":
                    fold_balanced_accuracy,
            }
        )

    return fold_results


def calculate_session_results(
    experiment,
):
    """

    It gives every recording session one prediction
    by averaging the clip probabilities

    """

    y_true = experiment["y_true"]
    probabilities = experiment[
        "probabilities"
    ]
    session_ids = experiment[
        "session_ids"
    ]

    session_true_labels = []
    session_predictions = []

    for session_id in np.unique(
        session_ids
    ):
        mask = (
            session_ids == session_id
        )

        unique_labels = np.unique(
            y_true[mask]
        )

        if len(unique_labels) != 1:
            raise ValueError(
                f"{experiment['name']}: session "
                f"{session_id} contains conflicting "
                f"labels"
            )

        true_label = int(
            unique_labels[0]
        )

        mean_probability = float(
            np.mean(
                probabilities[mask]
            )
        )

        if mean_probability >= 0.5:
            session_prediction = (
                QUEENLESS_ID
            )
        else:
            session_prediction = (
                HEALTHY_ID
            )

        session_true_labels.append(
            true_label
        )

        session_predictions.append(
            session_prediction
        )

    session_true_labels = np.asarray(
        session_true_labels,
        dtype = np.int64,
    )

    session_predictions = np.asarray(
        session_predictions,
        dtype = np.int64,
    )

    session_accuracy = accuracy_score(
        session_true_labels,
        session_predictions,
    )

    session_balanced_accuracy = (
        safe_balanced_accuracy(
            session_true_labels,
            session_predictions,
        )
    )

    return {
        "session_count": len(
            session_true_labels
        ),
        "accuracy": session_accuracy,
        "balanced_accuracy":
            session_balanced_accuracy,
    }


def calculate_summary(
    experiment,
    fold_results,
):
    """

    It calculates pooled and equal-fold summary metrics

    """

    y_true = experiment["y_true"]
    y_pred = experiment["y_pred"]

    pooled_accuracy = accuracy_score(
        y_true,
        y_pred,
    )

    pooled_balanced_accuracy = (
        safe_balanced_accuracy(
            y_true,
            y_pred,
        )
    )

    queenless_f1 = f1_score(
        y_true,
        y_pred,
        pos_label = QUEENLESS_ID,
        zero_division = 0,
    )

    fold_accuracies = [
        result["accuracy"]
        for result in fold_results
    ]

    valid_fold_balanced_accuracies = [
        result["balanced_accuracy"]
        for result in fold_results
        if result["balanced_accuracy"]
        is not None
    ]

    macro_fold_accuracy = float(
        np.mean(
            fold_accuracies
        )
    )

    if valid_fold_balanced_accuracies:
        macro_fold_balanced_accuracy = float(
            np.mean(
                valid_fold_balanced_accuracies
            )
        )
    else:
        macro_fold_balanced_accuracy = None

    return {
        "clip_count": len(y_true),
        "fold_count": len(
            fold_results
        ),
        "valid_balanced_fold_count": len(
            valid_fold_balanced_accuracies
        ),
        "pooled_accuracy":
            pooled_accuracy,
        "pooled_balanced_accuracy":
            pooled_balanced_accuracy,
        "queenless_f1":
            queenless_f1,
        "macro_fold_accuracy":
            macro_fold_accuracy,
        "macro_fold_balanced_accuracy":
            macro_fold_balanced_accuracy,
    }


def print_fold_results(
    experiment,
    fold_results,
):
    """

    It prints the result of every unseen hive separately

    """

    print()
    print(experiment["name"])
    print("-" * len(experiment["name"]))

    print(
        f"{'fold':>4} "
        f"{'test hive':<12} "
        f"{'clips':>8} "
        f"{'classes':>8} "
        f"{'accuracy':>10} "
        f"{'balanced':>10}"
    )

    print("-" * 60)

    for result in fold_results:
        balanced_text = format_metric(
            result[
                "balanced_accuracy"
            ]
        )

        print(
            f"{result['fold_id']:>4} "
            f"{result['test_hive']:<12} "
            f"{result['clip_count']:>8} "
            f"{result['class_count']:>8} "
            f"{result['accuracy']:>10.4f} "
            f"{balanced_text:>10}"
        )

    print()
    print(
        "N/A means that the unseen test hive "
        "contains only one true class."
    )


def print_null_band():
    """

    It prints the permutation noise band next to the results

    A result that lands inside this band is indistinguishable from
    relabelling the recordings at random, no matter how good the number
    looks on its own

    """

    available = [
        (name, path)
        for name, path in NULL_DISTRIBUTIONS
        if path.exists()
    ]

    if not available:
        return

    print()
    print("Permutation noise band")
    print("======================")

    print(
        f"{'hive set':<12} "
        f"{'recordings':>11} "
        f"{'real':>6} "
        f"{'fake best':>10} "
        f"{'fake median':>12} "
        f"{'p value':>9} "
        f"{'p floor':>9}"
    )

    print("-" * 76)

    for name, path in available:
        with np.load(
            path,
            allow_pickle = False,
        ) as saved:
            correct_counts = saved[
                "correct_counts"
            ]

            fold_count = int(
                saved["fold_count"]
            )

            real_correct = int(
                saved["real_correct"]
            )

            p_value = float(
                saved["p_value"]
            )

        print(
            f"{name:<12} "
            f"{fold_count:>11} "
            f"{real_correct:>6} "
            f"{int(correct_counts.max()):>10} "
            f"{float(np.median(correct_counts)):>12.1f} "
            f"{p_value:>9.3f} "
            f"{1 / len(correct_counts):>9.3f}"
        )

    print()

    print(
        "real = recordings decided correctly with the true labels."
    )

    print(
        "fake best = the same number for the best random relabelling."
    )

    print(
        "p floor = the smallest p value this many recordings can ever "
        "produce. A p floor above 0.05 means no result on that hive "
        "set can be significant."
    )


def print_summary_table(
    summaries,
):
    """

    It prints the main experiment comparison

    """

    print()
    print("Main experiment comparison")
    print("==========================")

    print(
        f"{'experiment':<32} "
        f"{'clips':>7} "
        f"{'folds':>6} "
        f"{'pool acc':>9} "
        f"{'pool bal':>9} "
        f"{'fold bal':>9} "
        f"{'Q F1':>8} "
        f"{'sess bal':>9}"
    )

    print("-" * 101)

    for item in summaries:
        summary = item["summary"]
        session = item["session"]

        pooled_balanced_text = (
            format_metric(
                summary[
                    "pooled_balanced_accuracy"
                ]
            )
        )

        macro_balanced_text = (
            format_metric(
                summary[
                    "macro_fold_balanced_accuracy"
                ]
            )
        )

        session_balanced_text = (
            format_metric(
                session[
                    "balanced_accuracy"
                ]
            )
        )

        print(
            f"{item['name']:<32} "
            f"{summary['clip_count']:>7} "
            f"{summary['fold_count']:>6} "
            f"{summary['pooled_accuracy']:>9.4f} "
            f"{pooled_balanced_text:>9} "
            f"{macro_balanced_text:>9} "
            f"{summary['queenless_f1']:>8.4f} "
            f"{session_balanced_text:>9}"
        )

    print()
    print(
        "Primary metric: fold bal"
    )

    print(
        "fold bal is the mean balanced accuracy "
        "across valid two-class unseen-hive folds."
    )

    print(
        "Single-class test hives are excluded "
        "from fold balanced accuracy."
    )


def main():
    summaries = []

    print(
        "Loading saved experiment predictions..."
    )

    for name, path in EXPERIMENTS:
        # A variant that has not been run yet is simply left out so that
        # the comparison still works while experiments are added
        if not path.exists():
            print(
                f"Skipping {name} -- "
                f"no saved predictions at {path}"
            )

            continue

        experiment = load_experiment(
            name,
            path,
        )

        fold_results = (
            calculate_fold_results(
                experiment
            )
        )

        session_results = (
            calculate_session_results(
                experiment
            )
        )

        summary = calculate_summary(
            experiment,
            fold_results,
        )

        print_fold_results(
            experiment,
            fold_results,
        )

        summaries.append(
            {
                "name": name,
                "summary": summary,
                "session":
                    session_results,
            }
        )

    print_summary_table(
        summaries
    )

    print_null_band()


if __name__ == "__main__":
    main()