from itertools import combinations
from pathlib import Path
import argparse
import time

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


PROCESSED_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
)

DATASET_PATH = (
    PROCESSED_DIR
    / "waggle_mels_cleaned.npz"
)

EMBEDDING_PATH = (
    PROCESSED_DIR
    / "waggle_embeddings_ast.npz"
)

FEATURE_SOURCES = (
    "mel",
    "embedding",
)

NUHIVE_HIVES = (
    "Hive1",
    "Hive3",
)

HIVE_SETS = (
    "all",
    "nuhive",
)

MINIMUM_SESSION_CLIPS = 10

HEALTHY_ID = 0
QUEENLESS_ID = 1

CLASS_NAMES = {
    HEALTHY_ID: "healthy",
    QUEENLESS_ID: "queenless",
}

RANDOM_SEED = 42

NORMALIZATION_MODES = (
    "fixed",
    "cmvn",
)

IDENTITY_PROBE_FOLDS = 5
WITHIN_SESSION_FOLDS = 5


def parse_arguments():
    """

    It reads the diagnostic settings from the command line

    """

    parser = argparse.ArgumentParser(
        description = (
            "It measures how much of the queenless decision is really "
            "a recording fingerprint"
        )
    )

    parser.add_argument(
        "--hives",
        choices = HIVE_SETS,
        default = "all",
        help = (
            "'all' uses every hive, 'nuhive' keeps only Hive1 and Hive3"
        ),
    )

    parser.add_argument(
        "--min-clips",
        type = int,
        default = MINIMUM_SESSION_CLIPS,
        help = (
            "Recordings with fewer clips than this are dropped"
        ),
    )

    parser.add_argument(
        "--features",
        choices = FEATURE_SOURCES,
        default = "mel",
        help = (
            "'mel' uses the log mel band summaries, 'embedding' uses "
            "the pretrained audio encoder output written by "
            "extract_embeddings.py"
        ),
    )

    return parser.parse_args()


def build_null_path(hive_set, feature_source):
    """

    It gives the saved permutation distribution its own file so that
    compare_experiments.py can print the noise band next to the results

    """

    return (
        PROCESSED_DIR
        / (
            f"waggle_permutation_null_{hive_set}"
            f"{'' if feature_source == 'mel' else '_' + feature_source}"
            ".npz"
        )
    )


def load_dataset(
    hive_set,
    minimum_session_clips,
):
    """

    It loads the spectrograms and drops the recordings that are too
    short to carry a decision

    """

    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Prepared dataset does not exist -- "
            f"{DATASET_PATH}"
        )

    with np.load(
        DATASET_PATH,
        allow_pickle = False,
    ) as dataset:
        X = dataset["X"].astype(
            np.float32,
            copy = False,
        )

        y = dataset["y"].astype(
            np.int64,
            copy = False,
        )

        hive_ids = dataset["hive_ids"]
        session_ids = dataset["session_ids"]

    if hive_set == "nuhive":
        keep = np.isin(
            hive_ids,
            np.asarray(NUHIVE_HIVES),
        )

        X = X[keep]
        y = y[keep]
        hive_ids = hive_ids[keep]
        session_ids = session_ids[keep]

    dropped_sessions = []

    for session_id in np.unique(
        session_ids
    ):
        clip_count = int(
            np.sum(
                session_ids == session_id
            )
        )

        if (
            clip_count
            < minimum_session_clips
        ):
            dropped_sessions.append(
                (
                    str(session_id),
                    clip_count,
                )
            )

    if dropped_sessions:
        keep = ~np.isin(
            session_ids,
            np.asarray(
                [
                    name
                    for name, _ in dropped_sessions
                ]
            ),
        )

        X = X[keep]
        y = y[keep]
        hive_ids = hive_ids[keep]
        session_ids = session_ids[keep]

    return (
        X,
        y,
        hive_ids,
        session_ids,
        dropped_sessions,
    )


def load_embeddings(
    hive_set,
    minimum_session_clips,
):
    """

    It loads the pretrained encoder output written by
    extract_embeddings.py and applies the same hive and recording
    filtering as the log mel path

    """

    if not EMBEDDING_PATH.exists():
        raise FileNotFoundError(
            f"Embeddings do not exist -- "
            f"{EMBEDDING_PATH}. Run "
            f"ear/extract_embeddings.py first"
        )

    with np.load(
        EMBEDDING_PATH,
        allow_pickle = False,
    ) as dataset:
        X = dataset["X"].astype(
            np.float32,
            copy = False,
        )

        y = dataset["y"].astype(
            np.int64,
            copy = False,
        )

        hive_ids = dataset["hive_ids"]
        session_ids = dataset["session_ids"]

    if hive_set == "nuhive":
        keep = np.isin(
            hive_ids,
            np.asarray(NUHIVE_HIVES),
        )

        X = X[keep]
        y = y[keep]
        hive_ids = hive_ids[keep]
        session_ids = session_ids[keep]

    dropped_sessions = []

    for session_id in np.unique(
        session_ids
    ):
        clip_count = int(
            np.sum(
                session_ids == session_id
            )
        )

        if (
            clip_count
            < minimum_session_clips
        ):
            dropped_sessions.append(
                (
                    str(session_id),
                    clip_count,
                )
            )

    if dropped_sessions:
        keep = ~np.isin(
            session_ids,
            np.asarray(
                [
                    name
                    for name, _ in dropped_sessions
                ]
            ),
        )

        X = X[keep]
        y = y[keep]
        hive_ids = hive_ids[keep]
        session_ids = session_ids[keep]

    return (
        X,
        y,
        hive_ids,
        session_ids,
        dropped_sessions,
    )


def build_feature_sets(
    X,
    session_ids,
    feature_source,
):
    """

    It returns the named feature sets that every test is run on

    The log mel path is tried with two normalizations, the pretrained
    encoder output is used as it is because the scaler in the pipeline
    already handles its scale

    """

    if feature_source == "embedding":
        return [
            (
                "ast",
                X,
            )
        ]

    return [
        (
            normalization,
            extract_summary_features(
                normalize_spectrograms(
                    X,
                    session_ids,
                    normalization,
                )
            ),
        )
        for normalization in (
            NORMALIZATION_MODES
        )
    ]


def normalize_spectrograms(
    X,
    session_ids,
    normalization,
):
    """

    It applies the same normalization that train_sessions.py uses

    """

    X = X.astype(
        np.float32,
        copy = True,
    )

    if normalization == "fixed":
        np.clip(
            X,
            -80.0,
            0.0,
            out = X,
        )

        X += 80.0
        X /= 80.0

        return X

    if normalization == "cmvn":
        for session_id in np.unique(
            session_ids
        ):
            mask = session_ids == session_id

            band_means = X[mask].mean(
                axis = (0, 2),
                keepdims = True,
            )

            band_deviations = X[mask].std(
                axis = (0, 2),
                keepdims = True,
            )

            X[mask] = (
                X[mask] - band_means
            ) / (band_deviations + 1e-6)

        return X

    raise ValueError(
        f"Unknown normalization mode -- "
        f"{normalization}"
    )


def extract_summary_features(X):
    """

    It converts every spectrogram into the mean and the standard
    deviation of each of the 128 mel bands, which gives 256 numbers

    """

    features = np.concatenate(
        [
            np.mean(X, axis = 2),
            np.std(X, axis = 2),
        ],
        axis = 1,
    )

    return features.astype(
        np.float32,
        copy = False,
    )


def create_model():
    """

    It creates the same scaler and logistic regression pipeline that
    train_baseline.py uses

    """

    return Pipeline(
        steps = [
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "classifier",
                LogisticRegression(
                    class_weight = "balanced",
                    max_iter = 2000,
                    random_state = RANDOM_SEED,
                    solver = "liblinear",
                ),
            ),
        ]
    )


def majority_accuracy(labels):
    """

    It returns the accuracy of always answering the most frequent label

    """

    _, counts = np.unique(
        labels,
        return_counts = True,
    )

    return float(
        counts.max()
        / counts.sum()
    )


def run_identity_probe(
    features,
    targets,
    probe_name,
):
    """

    It tries to recognize which recording or which hive a clip comes
    from, using the very same features that the queenless detector uses

    A high score means that the features carry a strong recording
    fingerprint, which is what the detector latches onto instead of the
    queen state

    """

    unique_targets, encoded = np.unique(
        targets,
        return_inverse = True,
    )

    if len(unique_targets) < 2:
        print(
            f"{probe_name:<28} "
            f"{'n/a':>10} "
            f"{'n/a':>10}"
        )

        return None

    smallest_group = int(
        np.bincount(encoded).min()
    )

    fold_count = min(
        IDENTITY_PROBE_FOLDS,
        smallest_group,
    )

    splitter = StratifiedKFold(
        n_splits = fold_count,
        shuffle = True,
        random_state = RANDOM_SEED,
    )

    predictions = np.empty_like(encoded)

    for (
        train_indices,
        test_indices,
    ) in splitter.split(
        features,
        encoded,
    ):
        model = create_model()

        model.fit(
            features[train_indices],
            encoded[train_indices],
        )

        predictions[test_indices] = (
            model.predict(
                features[test_indices]
            )
        )

    accuracy = accuracy_score(
        encoded,
        predictions,
    )

    baseline = majority_accuracy(
        encoded
    )

    print(
        f"{probe_name:<28} "
        f"{accuracy:>10.4f} "
        f"{baseline:>10.4f}"
    )

    return accuracy


def run_within_session_test(
    features,
    y,
):
    """

    It splits the clips randomly, so clips of the same recording land in
    both the training and the testing part

    A near perfect score here together with a poor cross session score
    proves that the model memorizes recordings instead of learning the
    queen state

    """

    splitter = StratifiedKFold(
        n_splits = WITHIN_SESSION_FOLDS,
        shuffle = True,
        random_state = RANDOM_SEED,
    )

    predictions = np.empty_like(y)

    for (
        train_indices,
        test_indices,
    ) in splitter.split(
        features,
        y,
    ):
        model = create_model()

        model.fit(
            features[train_indices],
            y[train_indices],
        )

        predictions[test_indices] = (
            model.predict(
                features[test_indices]
            )
        )

    return (
        accuracy_score(y, predictions),
        balanced_accuracy_score(
            y,
            predictions,
        ),
    )


def run_leave_one_session_out(
    features,
    clip_labels,
    session_ids,
):
    """

    It trains on every recording except one and decides the held out
    recording by the median of its clip probabilities

    It returns the clip level balanced accuracy, the number of correctly
    decided recordings and the number of usable folds

    """

    clip_predictions = np.full(
        len(clip_labels),
        fill_value = -1,
        dtype = np.int64,
    )

    correct_sessions = 0
    usable_folds = 0

    session_details = []

    for session_id in np.unique(
        session_ids
    ):
        test_mask = (
            session_ids == session_id
        )

        train_mask = ~test_mask

        train_labels = clip_labels[
            train_mask
        ]

        if len(
            np.unique(train_labels)
        ) < 2:
            continue

        usable_folds += 1

        model = create_model()

        model.fit(
            features[train_mask],
            train_labels,
        )

        probabilities = (
            model.predict_proba(
                features[test_mask]
            )[
                :,
                list(
                    model.classes_
                ).index(QUEENLESS_ID),
            ]
        )

        clip_predictions[test_mask] = (
            np.where(
                probabilities > 0.5,
                QUEENLESS_ID,
                HEALTHY_ID,
            )
        )

        median_probability = float(
            np.median(probabilities)
        )

        decision = (
            QUEENLESS_ID
            if median_probability > 0.5
            else HEALTHY_ID
        )

        true_label = int(
            np.unique(
                clip_labels[test_mask]
            )[0]
        )

        if decision == true_label:
            correct_sessions += 1

        session_details.append(
            {
                "session_id": str(
                    session_id
                ),
                "true_label": true_label,
                "decision": decision,
                "median_probability": (
                    median_probability
                ),
            }
        )

    covered = clip_predictions != -1

    if not np.any(covered):
        return (
            float("nan"),
            0,
            0,
            session_details,
        )

    clip_balanced = (
        balanced_accuracy_score(
            clip_labels[covered],
            clip_predictions[covered],
        )
        if len(
            np.unique(
                clip_labels[covered]
            )
        ) > 1
        else float("nan")
    )

    return (
        clip_balanced,
        correct_sessions,
        usable_folds,
        session_details,
    )


def build_session_table(
    y,
    hive_ids,
    session_ids,
):
    """

    It collects the label and the hive of every recording session

    """

    sessions = []

    for session_id in np.unique(
        session_ids
    ):
        mask = session_ids == session_id

        sessions.append(
            {
                "session_id": str(
                    session_id
                ),
                "hive_id": str(
                    np.unique(
                        hive_ids[mask]
                    )[0]
                ),
                "label": int(
                    np.unique(y[mask])[0]
                ),
                "clip_count": int(
                    np.sum(mask)
                ),
            }
        )

    return sessions


def run_permutation_test(
    features,
    session_ids,
    sessions,
    true_correct_sessions,
):
    """

    It relabels the recordings in every possible way that keeps the same
    number of healthy and queenless recordings, and reruns the leave one
    session out experiment for each of them

    If the real labelling is not clearly better than the fake ones, the
    pipeline has not shown any queen related signal

    """

    session_names = [
        session["session_id"]
        for session in sessions
    ]

    healthy_count = sum(
        1
        for session in sessions
        if session["label"] == HEALTHY_ID
    )

    all_labelings = list(
        combinations(
            range(len(session_names)),
            healthy_count,
        )
    )

    print()

    print(
        f"Possible labellings with "
        f"{healthy_count} healthy and "
        f"{len(session_names) - healthy_count} "
        f"queenless recordings: "
        f"{len(all_labelings)}"
    )

    print(
        f"Smallest p value this dataset can "
        f"ever produce: "
        f"{1 / len(all_labelings):.3f}"
    )

    print()

    scores = []

    for healthy_positions in all_labelings:
        fake_labels = np.full(
            len(session_names),
            QUEENLESS_ID,
            dtype = np.int64,
        )

        for position in healthy_positions:
            fake_labels[
                position
            ] = HEALTHY_ID

        label_by_session = {
            name: int(label)
            for name, label in zip(
                session_names,
                fake_labels,
            )
        }

        clip_labels = np.array(
            [
                label_by_session[
                    str(session_id)
                ]
                for session_id in session_ids
            ],
            dtype = np.int64,
        )

        (
            _,
            correct_sessions,
            usable_folds,
            _,
        ) = run_leave_one_session_out(
            features,
            clip_labels,
            session_ids,
        )

        is_true_labeling = set(
            healthy_positions
        ) == {
            index
            for index, session in enumerate(
                sessions
            )
            if session["label"]
            == HEALTHY_ID
        }

        scores.append(
            (
                correct_sessions,
                usable_folds,
                is_true_labeling,
            )
        )

    correct_counts = np.array(
        [
            correct
            for correct, _, _ in scores
        ]
    )

    fold_count = max(
        usable
        for _, usable, _ in scores
    )

    print(
        f"{'recordings correct':<20} "
        f"{'labellings':>11} "
        f"{'share':>8}"
    )

    print("-" * 42)

    for value in range(
        fold_count + 1
    ):
        occurrences = int(
            np.sum(
                correct_counts == value
            )
        )

        if occurrences == 0:
            continue

        marker = (
            "   <- real labels"
            if value == true_correct_sessions
            else ""
        )

        print(
            f"{value:<20} "
            f"{occurrences:>11} "
            f"{occurrences / len(scores):>8.3f}"
            f"{marker}"
        )

    at_least_as_good = sum(
        1
        for correct, _, _ in scores
        if correct >= true_correct_sessions
    )

    p_value = (
        at_least_as_good
        / len(scores)
    )

    print()

    print(
        f"Real labelling: "
        f"{true_correct_sessions}/{fold_count} "
        f"recordings correct"
    )

    print(
        f"Best fake labelling: "
        f"{int(correct_counts.max())}/{fold_count}"
    )

    print(
        f"Fake labellings that do at least as "
        f"well as the real one: "
        f"{at_least_as_good}/{len(scores)}"
    )

    print(
        f"Permutation p value: "
        f"{p_value:.3f}"
    )

    return (
        p_value,
        correct_counts,
        fold_count,
    )


def main():
    program_start_time = (
        time.perf_counter()
    )

    arguments = parse_arguments()

    loader = (
        load_embeddings
        if arguments.features == "embedding"
        else load_dataset
    )

    (
        X,
        y,
        hive_ids,
        session_ids,
        dropped_sessions,
    ) = loader(
        arguments.hives,
        arguments.min_clips,
    )

    sessions = build_session_table(
        y,
        hive_ids,
        session_ids,
    )

    print(
        f"Dataset: "
        f"{EMBEDDING_PATH if arguments.features == 'embedding' else DATASET_PATH}"
    )

    print(
        f"Features: {arguments.features} "
        f"({X.shape[1] if X.ndim == 2 else X.shape[1:]} per clip)"
    )

    print(
        f"Hive set: {arguments.hives} "
        f"({len(np.unique(hive_ids))} hives)"
    )

    print(f"Clips: {len(y)}")

    print(
        f"Recording sessions: "
        f"{len(sessions)}"
    )

    for name, clip_count in (
        dropped_sessions
    ):
        print(
            f"Dropped recording {name} -- "
            f"only {clip_count} clips "
            f"(minimum {arguments.min_clips})"
        )

    print()

    print(
        f"{'session_id':<34} "
        f"{'hive':<8} "
        f"{'label':<11} "
        f"{'clips':>7}"
    )

    print("-" * 62)

    for session in sessions:
        print(
            f"{session['session_id']:<34} "
            f"{session['hive_id']:<8} "
            f"{CLASS_NAMES[session['label']]:<11} "
            f"{session['clip_count']:>7}"
        )

    feature_sets = build_feature_sets(
        X,
        session_ids,
        arguments.features,
    )

    results_by_mode = {}

    for normalization, features in (
        feature_sets
    ):
        print()
        print("=" * 70)

        print(
            f"Feature set: {normalization}"
        )

        print("=" * 70)

        print()

        print(
            "Test 1 -- can the features "
            "recognize the recording itself?"
        )

        print()

        print(
            f"{'probe':<28} "
            f"{'accuracy':>10} "
            f"{'majority':>10}"
        )

        print("-" * 52)

        session_probe = run_identity_probe(
            features,
            session_ids,
            "recording session identity",
        )

        hive_probe = run_identity_probe(
            features,
            hive_ids,
            "physical hive identity",
        )

        print()

        print(
            "A high score means the features "
            "describe the microphone and the "
            "room, not the colony."
        )

        if normalization == "cmvn":
            print(
                "Note: cmvn sets the mean of "
                "every band to zero by "
                "construction, so half of the "
                "feature vector is empty here. "
                "The remaining score comes from "
                "the band standard deviations."
            )

        print()

        print(
            "Test 2 -- queen state with a "
            "random clip split (recordings "
            "appear on both sides)"
        )

        (
            within_accuracy,
            within_balanced,
        ) = run_within_session_test(
            features,
            y,
        )

        print()

        print(
            f"Accuracy: "
            f"{within_accuracy:.4f}"
        )

        print(
            f"Balanced accuracy: "
            f"{within_balanced:.4f}"
        )

        print()

        print(
            "Test 3 -- queen state with leave "
            "one recording out (the honest "
            "split)"
        )

        (
            cross_balanced,
            correct_sessions,
            usable_folds,
            session_details,
        ) = run_leave_one_session_out(
            features,
            y,
            session_ids,
        )

        print()

        print(
            f"{'session_id':<34} "
            f"{'true':<11} "
            f"{'decision':<11} "
            f"{'median Q':>9}"
        )

        print("-" * 68)

        for detail in session_details:
            print(
                f"{detail['session_id']:<34} "
                f"{CLASS_NAMES[detail['true_label']]:<11} "
                f"{CLASS_NAMES[detail['decision']]:<11} "
                f"{detail['median_probability']:>9.4f}"
            )

        print()

        print(
            f"Clip level balanced accuracy: "
            f"{cross_balanced:.4f}"
        )

        print(
            f"Recordings decided correctly: "
            f"{correct_sessions}/{usable_folds}"
        )

        print()

        print(
            f"Memorization gap "
            f"(random split minus honest split): "
            f"{within_balanced - cross_balanced:.4f}"
        )

        results_by_mode[
            normalization
        ] = {
            "session_probe": session_probe,
            "hive_probe": hive_probe,
            "within_balanced": within_balanced,
            "cross_balanced": cross_balanced,
            "correct_sessions": correct_sessions,
            "usable_folds": usable_folds,
        }

    print()
    print("=" * 70)

    # The last feature set is the one the permutation test runs on:
    # for the log mel path that is cmvn, for the encoder path it is the
    # only feature set there is
    permutation_name, permutation_features = (
        feature_sets[-1]
    )

    print(
        f"Test 4 -- permutation test on the "
        f"{permutation_name} features"
    )

    print("=" * 70)

    (
        p_value,
        null_correct_counts,
        permutation_fold_count,
    ) = run_permutation_test(
        permutation_features,
        session_ids,
        sessions,
        results_by_mode[permutation_name][
            "correct_sessions"
        ],
    )

    null_path = build_null_path(
        arguments.hives,
        arguments.features,
    )

    np.savez_compressed(
        null_path,
        correct_counts = null_correct_counts,
        fold_count = np.int32(
            permutation_fold_count
        ),
        real_correct = np.int32(
            results_by_mode[permutation_name][
                "correct_sessions"
            ]
        ),
        p_value = np.float32(p_value),
    )

    print()

    print(
        f"Permutation distribution saved to: "
        f"{null_path}"
    )

    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)

    print()

    print(
        f"{'feature set':<16} "
        f"{'session probe':>14} "
        f"{'hive probe':>12} "
        f"{'random split':>13} "
        f"{'honest split':>13} "
        f"{'sessions ok':>12}"
    )

    print("-" * 86)

    for normalization, _ in feature_sets:
        result = results_by_mode[
            normalization
        ]

        print(
            f"{normalization:<16} "
            f"{result['session_probe']:>14.4f} "
            f"{result['hive_probe']:>12.4f} "
            f"{result['within_balanced']:>13.4f} "
            f"{result['cross_balanced']:>13.4f} "
            f"{str(result['correct_sessions']) + '/' + str(result['usable_folds']):>12}"
        )

    print()

    print(
        "How to read this table:"
    )

    print(
        "- session probe near 1.0 means the "
        "features are a recording fingerprint."
    )

    print(
        "- a large gap between the random "
        "split and the honest split means "
        "memorization, not learning."
    )

    smallest_possible_p = 1 / len(
        list(
            combinations(
                range(len(sessions)),
                sum(
                    1
                    for session in sessions
                    if session["label"]
                    == HEALTHY_ID
                ),
            )
        )
    )

    print(
        f"- the permutation p value is "
        f"{p_value:.3f}, and with "
        f"{len(sessions)} recordings it can "
        f"never go below "
        f"{smallest_possible_p:.3f}."
    )

    if smallest_possible_p > 0.05:
        print(
            "  That floor is above 0.05, so no "
            "result on this hive set can reach "
            "significance. Add recordings."
        )

    else:
        print(
            "  That floor is below 0.05, so a "
            "real signal could be shown on this "
            "hive set."
        )

    print()

    print(
        f"Total program time: "
        f"{time.perf_counter() - program_start_time:.2f} seconds"
    )


if __name__ == "__main__":
    main()
