"""

It asks a different question than the other training scripts

Instead of "is this recording queenless", it asks "did the queen state
change between these two recordings of the same hive". Both members of
a pair come from the same colony and the same microphone, so whatever
makes that hive sound like itself cancels out inside the pair. That is
the confound every earlier experiment kept measuring

The hard part is time. A pair whose state changed is also a pair of two
different days, so a model can score well by noticing "these are
different days" without knowing anything about the queen. Two things
guard against it:

- hard negative pairs: two recordings of the same hive, both with a
  queen, but weeks apart. A model that only sees time calls these
  changed as well
- results are reported per day gap bin, so a score that only comes from
  far apart pairs is visible

"""

from pathlib import Path
import argparse
import collections
import time
from datetime import date

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


PROCESSED_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
)

DATASET_PATH = (
    PROCESSED_DIR
    / "waggle_mels_sbcm.npz"
)

QUEENLESS_STATUS = "1"

RANDOM_SEED = 42

PAIRS_PER_HIVE = 3000

# Day gaps are reported in these bins so that a score coming only from
# far apart recordings cannot hide inside an overall number
GAP_BINS = (
    (0, 1),
    (2, 5),
    (6, 12),
    (13, 40),
)


def parse_arguments():
    """

    It reads the experiment settings from the command line

    """

    parser = argparse.ArgumentParser(
        description = (
            "Pairwise change detection for the queen state"
        )
    )

    parser.add_argument(
        "--pairs-per-hive",
        type = int,
        default = PAIRS_PER_HIVE,
        help = (
            "How many pairs of each kind to sample per hive"
        ),
    )

    parser.add_argument(
        "--include-easy-negatives",
        action = "store_true",
        help = (
            "It adds same day unchanged pairs, which are easy and "
            "inflate the score"
        ),
    )

    return parser.parse_args()


def load_units():
    """

    It averages the clips of every audio segment into one feature vector

    A segment is one minute of audio, which is the smallest unit that
    still describes a stable stretch of the recording

    """

    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Prepared dataset does not exist -- "
            f"{DATASET_PATH}. Run "
            f"ear/prepare_sbcm.py first"
        )

    with np.load(
        DATASET_PATH,
        allow_pickle = False,
    ) as dataset:
        X = dataset["X"]
        session_ids = dataset["session_ids"]
        source_files = dataset["source_files"]

    # Mean and standard deviation of every mel band over time
    features = np.concatenate(
        [
            X.mean(axis = 2),
            X.std(axis = 2),
        ],
        axis = 1,
    ).astype(np.float32)

    units = []

    for source_file in np.unique(
        source_files
    ):
        mask = source_files == source_file

        session_id = str(
            session_ids[mask][0]
        )

        parts = session_id.split("_")

        hive = "_".join(parts[:-2])
        day = parts[-2]
        status = parts[-1].lstrip("s")

        units.append(
            {
                "hive": hive,
                "day": date.fromisoformat(day),
                "status": status,
                "session_id": session_id,
                "feature": features[mask].mean(
                    axis = 0
                ),
            }
        )

    return units


def day_gap(first, second):
    """

    It returns how many days apart two units were recorded

    """

    return abs(
        (first["day"] - second["day"]).days
    )


def has_queen(unit):
    """

    It says whether the colony had a queen during this unit

    """

    return unit["status"] != QUEENLESS_STATUS


def sample_pairs(
    units,
    generator,
    wanted,
    include_easy_negatives,
):
    """

    It builds the three kinds of pairs for one hive

    changed        one member queenless, the other with a queen
    hard unchanged both with a queen but on different days
    easy unchanged the same day, only added when asked for

    """

    with_queen = [
        unit
        for unit in units
        if has_queen(unit)
    ]

    queenless = [
        unit
        for unit in units
        if not has_queen(unit)
    ]

    if not with_queen or not queenless:
        return []

    pairs = []

    def draw(pool_a, pool_b, label, kind, condition):
        added = 0
        attempts = 0

        while (
            added < wanted
            and attempts < wanted * 50
        ):
            attempts += 1

            first = pool_a[
                generator.integers(len(pool_a))
            ]

            second = pool_b[
                generator.integers(len(pool_b))
            ]

            if not condition(first, second):
                continue

            pairs.append(
                {
                    "feature": np.abs(
                        first["feature"]
                        - second["feature"]
                    ),
                    "label": label,
                    "kind": kind,
                    "gap": day_gap(first, second),
                }
            )

            added += 1

    draw(
        with_queen,
        queenless,
        1,
        "changed",
        lambda a, b: True,
    )

    draw(
        with_queen,
        with_queen,
        0,
        "hard unchanged",
        lambda a, b: a["day"] != b["day"],
    )

    if include_easy_negatives:
        draw(
            with_queen,
            with_queen,
            0,
            "easy unchanged",
            lambda a, b: (
                a["day"] == b["day"]
                and a is not b
            ),
        )

    return pairs


def create_model():
    """

    It creates the classifier that reads the difference between the two
    members of a pair

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
                    max_iter = 5000,
                    random_state = RANDOM_SEED,
                ),
            ),
        ]
    )


def report_gap_bins(
    labels,
    scores,
    gaps,
):
    """

    It reports the score separately for pairs that are close together
    and pairs that are far apart in time

    """

    print(
        f"      {'day gap':<12}"
        f"{'changed':>9}"
        f"{'unchanged':>11}"
        f"{'AUC':>8}"
    )

    for low, high in GAP_BINS:
        mask = (
            (gaps >= low)
            & (gaps <= high)
        )

        if not np.any(mask):
            continue

        positives = int(
            np.sum(labels[mask] == 1)
        )

        negatives = int(
            np.sum(labels[mask] == 0)
        )

        if positives == 0 or negatives == 0:
            text = "n/a"

        else:
            text = (
                f"{roc_auc_score(labels[mask], scores[mask]):.3f}"
            )

        print(
            f"      {f'{low}-{high}':<12}"
            f"{positives:>9}"
            f"{negatives:>11}"
            f"{text:>8}"
        )


def main():
    program_start_time = time.perf_counter()

    arguments = parse_arguments()

    generator = np.random.default_rng(
        RANDOM_SEED
    )

    units = load_units()

    hives = sorted(
        {unit["hive"] for unit in units}
    )

    print(f"Dataset: {DATASET_PATH}")
    print(f"Audio segments: {len(units)}")
    print(f"Hives: {len(hives)}")

    print(
        f"Pairs of each kind per hive: "
        f"{arguments.pairs_per_hive}"
    )

    print(
        f"Easy same day negatives: "
        f"{'included' if arguments.include_easy_negatives else 'excluded'}"
    )

    pairs_by_hive = {}

    for hive in hives:
        pairs_by_hive[hive] = sample_pairs(
            [
                unit
                for unit in units
                if unit["hive"] == hive
            ],
            generator,
            arguments.pairs_per_hive,
            arguments.include_easy_negatives,
        )

    print()

    print(
        f"{'hive':<12}"
        + "".join(
            f"{kind:>17}"
            for kind in (
                "changed",
                "hard unchanged",
            )
        )
    )

    print("-" * 48)

    for hive in hives:
        counts = collections.Counter(
            pair["kind"]
            for pair in pairs_by_hive[hive]
        )

        print(
            f"{hive:<12}"
            f"{counts['changed']:>17}"
            f"{counts['hard unchanged']:>17}"
        )

    print()

    print(
        "Leave one hive out, pairwise change detection:"
    )

    hive_scores = []

    for test_hive in hives:
        train_pairs = [
            pair
            for hive in hives
            if hive != test_hive
            for pair in pairs_by_hive[hive]
        ]

        test_pairs = pairs_by_hive[test_hive]

        if not test_pairs or not train_pairs:
            continue

        train_features = np.stack(
            [
                pair["feature"]
                for pair in train_pairs
            ]
        )

        train_labels = np.array(
            [
                pair["label"]
                for pair in train_pairs
            ]
        )

        test_features = np.stack(
            [
                pair["feature"]
                for pair in test_pairs
            ]
        )

        test_labels = np.array(
            [
                pair["label"]
                for pair in test_pairs
            ]
        )

        test_gaps = np.array(
            [
                pair["gap"]
                for pair in test_pairs
            ]
        )

        if len(set(train_labels)) < 2:
            continue

        model = create_model()

        model.fit(
            train_features,
            train_labels,
        )

        scores = model.predict_proba(
            test_features
        )[:, 1]

        overall = roc_auc_score(
            test_labels,
            scores,
        )

        hive_scores.append(overall)

        print()

        print(
            f"  test hive {test_hive}  "
            f"AUC {overall:.3f}"
        )

        report_gap_bins(
            test_labels,
            scores,
            test_gaps,
        )

    print()

    print(
        f"Mean AUC over unseen hives: "
        f"{np.mean(hive_scores):.3f}"
        f"   (0.5 = chance)"
    )

    print()

    print(
        "A score above chance inside every day gap bin means the model "
        "is not just noticing that two recordings are far apart in "
        "time."
    )

    print()

    print(
        f"Total program time: "
        f"{time.perf_counter() - program_start_time:.1f} seconds"
    )


if __name__ == "__main__":
    main()
