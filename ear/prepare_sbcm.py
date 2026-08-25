"""

It turns the Smart Bee Colony Monitor recordings into the same log mel
dataset format that prepare_data.py produces

Unlike the "To bee or not to bee" recordings, every hive here went
through a controlled experiment: the original queen was removed, the
hive stayed queenless for a few days, a new queen was introduced and
then accepted. The hive, the microphone and the location stay the same
while only the queen state changes, which is what makes this data able
to separate the queen from the recording

"""

from pathlib import Path
import argparse
import csv
import time

import librosa
import numpy as np


DATA_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "sbcm"
)

LABEL_CSV = (
    DATA_DIR
    / "all_data_updated.csv"
)

SOUND_DIR = (
    DATA_DIR
    / "sound_files"
    / "sound_files"
)

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
    / "waggle_mels_sbcm.npz"
)

# Identical to prepare_data.py so that the two datasets can be merged
SAMPLE_RATE = 22050
CLIP_SECONDS = 5
CLIP_SAMPLES = SAMPLE_RATE * CLIP_SECONDS
NUM_OF_FFT = 2048
HOP_LENGTH = 512
NUM_OF_MELS = 128
FMAX = 2000
EXPECTED_MEL_SHAPE = (128, 216)

HEALTHY_ID = 0
QUEENLESS_ID = 1

# The queen status column encodes the phase of the experiment
QUEEN_STATUS_ORIGINAL = "0"
QUEEN_STATUS_QUEENLESS = "1"
QUEEN_STATUS_NOT_ACCEPTED = "2"
QUEEN_STATUS_ACCEPTED = "3"

STATUS_NAMES = {
    QUEEN_STATUS_ORIGINAL: "original queen",
    QUEEN_STATUS_QUEENLESS: "queenless",
    QUEEN_STATUS_NOT_ACCEPTED: "new queen not accepted",
    QUEEN_STATUS_ACCEPTED: "new queen accepted",
}

# A caged new queen that the colony has not accepted yet is neither
# clearly queenright nor clearly queenless, so it is left out by default
AMBIGUOUS_STATUSES = {
    QUEEN_STATUS_NOT_ACCEPTED,
}

SEGMENTS_PER_RECORDING = 2
CLIPS_PER_SEGMENT = 6
MAXIMUM_SEGMENT_INDEX = 12


def parse_arguments():
    """

    It reads the preparation settings from the command line

    """

    parser = argparse.ArgumentParser(
        description = (
            "It builds the log mel dataset for the Smart Bee Colony "
            "Monitor recordings"
        )
    )

    parser.add_argument(
        "--segments-per-recording",
        type = int,
        default = SEGMENTS_PER_RECORDING,
        help = (
            "How many 60 second segments to sample from every recording"
        ),
    )

    parser.add_argument(
        "--clips-per-segment",
        type = int,
        default = CLIPS_PER_SEGMENT,
        help = (
            "How many 5 second clips to take from every segment"
        ),
    )

    parser.add_argument(
        "--include-not-accepted",
        action = "store_true",
        help = (
            "It keeps the phase where a new queen was introduced but "
            "not yet accepted, counting it as queen present"
        ),
    )

    return parser.parse_args()


def format_duration(seconds):
    """

    It converts seconds into an easier to read duration

    """

    seconds = max(0, int(round(seconds)))

    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"

    if minutes > 0:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def read_label_rows():
    """

    It reads the recording table and checks the columns it needs

    """

    if not LABEL_CSV.exists():
        raise FileNotFoundError(
            f"Label table does not exist -- "
            f"{LABEL_CSV}"
        )

    with open(
        LABEL_CSV,
        newline = "",
    ) as handle:
        rows = list(
            csv.DictReader(handle)
        )

    required_columns = {
        "device",
        "hive number",
        "date",
        "file name",
        "queen presence",
        "queen status",
    }

    missing_columns = (
        required_columns
        - set(rows[0].keys())
    )

    if missing_columns:
        raise ValueError(
            f"Label table is missing columns: "
            f"{sorted(missing_columns)}"
        )

    return rows


def describe_row(row):
    """

    It builds the hive, recording block and label of one row

    The block is one hive on one day in one phase of the experiment.
    Clips inside a block share the colony, the microphone, the weather
    and the queen state, so a block is the smallest unit that can be
    treated as one sample

    """

    hive_id = (
        f"SBCM_d{row['device']}"
        f"h{row['hive number']}"
    )

    day = row["date"][:10]
    status = row["queen status"]

    session_id = (
        f"{hive_id}_{day}_s{status}"
    )

    label = (
        QUEENLESS_ID
        if status == QUEEN_STATUS_QUEENLESS
        else HEALTHY_ID
    )

    return (
        hive_id,
        session_id,
        status,
        label,
    )


def find_segment_paths(
    row,
    wanted_segments,
):
    """

    It returns the segment files of one recording, spread evenly so that
    the sampled minutes are not all next to each other

    """

    stem = row["file name"].replace(
        ".raw",
        "",
    )

    available = [
        SOUND_DIR
        / f"{stem}__segment{index}.wav"
        for index in range(
            MAXIMUM_SEGMENT_INDEX
        )
    ]

    available = [
        path
        for path in available
        if path.exists()
    ]

    if not available:
        return []

    if len(available) <= wanted_segments:
        return available

    positions = np.linspace(
        0,
        len(available) - 1,
        wanted_segments,
    )

    return [
        available[int(round(position))]
        for position in positions
    ]


def clip_to_log_mel(clip):
    """

    It converts one clip into a log mel spectrogram

    """

    mel = librosa.feature.melspectrogram(
        y = clip,
        sr = SAMPLE_RATE,
        n_fft = NUM_OF_FFT,
        hop_length = HOP_LENGTH,
        n_mels = NUM_OF_MELS,
        fmax = FMAX,
    )

    mel_db = librosa.power_to_db(
        mel,
        ref = np.max,
    )

    if mel_db.shape != EXPECTED_MEL_SHAPE:
        raise ValueError(
            f"Unexpected spectrogram shape "
            f"{mel_db.shape}, expected "
            f"{EXPECTED_MEL_SHAPE}"
        )

    return mel_db.astype(
        np.float32,
        copy = False,
    )


def take_clips(
    audio,
    wanted_clips,
):
    """

    It takes evenly spaced full length clips from one segment

    """

    total_clips = len(audio) // CLIP_SAMPLES

    if total_clips == 0:
        return []

    wanted_clips = min(
        wanted_clips,
        total_clips,
    )

    positions = np.linspace(
        0,
        total_clips - 1,
        wanted_clips,
    )

    clips = []

    for position in positions:
        start = (
            int(round(position))
            * CLIP_SAMPLES
        )

        clips.append(
            audio[
                start : start + CLIP_SAMPLES
            ]
        )

    return clips


def build_dataset(arguments):
    """

    It walks the recording table and turns the sampled audio into
    spectrograms

    """

    rows = read_label_rows()

    features = []
    labels = []
    hive_ids = []
    session_ids = []
    statuses = []
    source_files = []

    skipped_ambiguous = 0
    skipped_without_audio = 0

    start_time = time.perf_counter()

    print(
        f"Recordings in the label table: "
        f"{len(rows)}"
    )

    print()

    for row_number, row in enumerate(
        rows,
        start = 1,
    ):
        (
            hive_id,
            session_id,
            status,
            label,
        ) = describe_row(row)

        if (
            status in AMBIGUOUS_STATUSES
            and not arguments.include_not_accepted
        ):
            skipped_ambiguous += 1

            continue

        segment_paths = find_segment_paths(
            row,
            arguments.segments_per_recording,
        )

        if not segment_paths:
            skipped_without_audio += 1

            continue

        for path in segment_paths:
            audio, _ = librosa.load(
                path,
                sr = SAMPLE_RATE,
                mono = True,
            )

            for clip in take_clips(
                audio,
                arguments.clips_per_segment,
            ):
                features.append(
                    clip_to_log_mel(clip)
                )

                labels.append(label)
                hive_ids.append(hive_id)
                session_ids.append(session_id)
                statuses.append(status)
                source_files.append(path.name)

        if row_number % 100 == 0:
            elapsed = (
                time.perf_counter()
                - start_time
            )

            print(
                f"[{row_number:>4}/{len(rows)}] "
                f"{len(features)} clips "
                f"| elapsed "
                f"{format_duration(elapsed)}"
            )

    print()

    print(
        f"Skipped as ambiguous "
        f"(new queen not accepted): "
        f"{skipped_ambiguous}"
    )

    print(
        f"Skipped without audio on disk: "
        f"{skipped_without_audio}"
    )

    return (
        np.asarray(
            features,
            dtype = np.float32,
        ),
        np.asarray(labels, dtype = np.int64),
        np.asarray(hive_ids, dtype = np.str_),
        np.asarray(session_ids, dtype = np.str_),
        np.asarray(statuses, dtype = np.str_),
        np.asarray(
            source_files,
            dtype = np.str_,
        ),
    )


def report_dataset(
    y,
    hive_ids,
    session_ids,
    statuses,
):
    """

    It prints what the prepared dataset contains

    """

    print()

    print(
        f"{'hive':<14} "
        f"{'phase':<24} "
        f"{'days':>6} "
        f"{'clips':>8}"
    )

    print("-" * 56)

    for hive_id in np.unique(hive_ids):
        for status in sorted(
            np.unique(
                statuses[
                    hive_ids == hive_id
                ]
            )
        ):
            mask = (
                (hive_ids == hive_id)
                & (statuses == status)
            )

            day_count = len(
                np.unique(
                    session_ids[mask]
                )
            )

            print(
                f"{hive_id:<14} "
                f"{STATUS_NAMES[status]:<24} "
                f"{day_count:>6} "
                f"{int(np.sum(mask)):>8}"
            )

    healthy = int(
        np.sum(y == HEALTHY_ID)
    )

    queenless = int(
        np.sum(y == QUEENLESS_ID)
    )

    print()
    print(f"Clips: {len(y)}")
    print(f"Healthy clips: {healthy}")
    print(f"Queenless clips: {queenless}")
    print(f"Hives: {len(np.unique(hive_ids))}")

    print(
        f"Recording blocks "
        f"(hive x day x phase): "
        f"{len(np.unique(session_ids))}"
    )

    queenless_blocks = len(
        np.unique(
            session_ids[
                y == QUEENLESS_ID
            ]
        )
    )

    print(
        f"Queenless blocks: "
        f"{queenless_blocks}"
    )

    print(
        f"Queen present blocks: "
        f"{len(np.unique(session_ids)) - queenless_blocks}"
    )


def main():
    program_start_time = time.perf_counter()

    arguments = parse_arguments()

    print(f"Label table: {LABEL_CSV}")
    print(f"Audio: {SOUND_DIR}")

    print(
        f"Segments per recording: "
        f"{arguments.segments_per_recording}"
    )

    print(
        f"Clips per segment: "
        f"{arguments.clips_per_segment}"
    )

    print(
        f"New queen not accepted phase: "
        f"{'kept' if arguments.include_not_accepted else 'excluded'}"
    )

    print()

    (
        X,
        y,
        hive_ids,
        session_ids,
        statuses,
        source_files,
    ) = build_dataset(arguments)

    report_dataset(
        y,
        hive_ids,
        session_ids,
        statuses,
    )

    OUTPUT_PATH.parent.mkdir(
        parents = True,
        exist_ok = True,
    )

    np.savez_compressed(
        OUTPUT_PATH,
        X = X,
        y = y,
        hive_ids = hive_ids,
        session_ids = session_ids,
        statuses = statuses,
        source_files = source_files,
        sample_rate = np.int32(SAMPLE_RATE),
        clip_seconds = np.int32(CLIP_SECONDS),
        n_mels = np.int32(NUM_OF_MELS),
        hop_length = np.int32(HOP_LENGTH),
        fmax = np.int32(FMAX),
    )

    print()
    print(f"Saved to: {OUTPUT_PATH}")

    print(
        f"Total program time: "
        f"{format_duration(time.perf_counter() - program_start_time)}"
    )


if __name__ == "__main__":
    main()
