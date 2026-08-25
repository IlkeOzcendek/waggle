"""

It turns every clean clip into an embedding from a pretrained audio
model instead of a hand made log mel summary

The log mel summary features describe the average loudness of each
frequency band, which turned out to be mostly a recording fingerprint.
A model that was pretrained on millions of general sounds describes what
the sound is like instead, which is the best chance of finding a queen
related signal in a small dataset

"""

from pathlib import Path
import argparse
import sys
import time

import numpy as np
import torch

# The data pipeline lives next to this file and is reused as is so that
# the clips stay identical to the log mel dataset
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent),
)

from prepare_data import (
    CLIP_SECONDS,
    LABEL_TO_ID,
    clip_overlaps_nobee,
    find_audio_files,
    load_audio,
    parse_filename,
    read_lab_intervals,
    split_into_clips,
)


PROCESSED_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
)

# The AST checkpoint was trained on AudioSet, which contains a wide
# range of everyday sounds including insects
AST_MODEL_NAME = (
    "MIT/ast-finetuned-audioset-10-10-0.4593"
)

AST_SAMPLE_RATE = 16000

BATCH_SIZE = 8


def build_output_path(model_tag):
    """

    It gives every encoder its own embedding file

    """

    return (
        PROCESSED_DIR
        / f"waggle_embeddings_{model_tag}.npz"
    )


def parse_arguments():
    """

    It reads the extraction settings from the command line

    """

    parser = argparse.ArgumentParser(
        description = (
            "It extracts pretrained audio embeddings for every clean clip"
        )
    )

    parser.add_argument(
        "--batch-size",
        type = int,
        default = BATCH_SIZE,
        help = "Clips encoded at the same time",
    )

    return parser.parse_args()


def choose_device():
    """

    It chooses the fastest available device

    """

    if torch.backends.mps.is_available():
        return torch.device("mps")

    if torch.cuda.is_available():
        return torch.device("cuda")

    return torch.device("cpu")


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


def load_encoder(device):
    """

    It loads the frozen pretrained encoder and its input preparation

    The encoder is never trained here. Only a small classifier is fitted
    on top of its output later, which is what keeps a model this large
    usable with a handful of recordings

    """

    from transformers import (
        ASTFeatureExtractor,
        ASTModel,
    )

    print(
        f"Loading encoder {AST_MODEL_NAME} ..."
    )

    feature_extractor = (
        ASTFeatureExtractor.from_pretrained(
            AST_MODEL_NAME
        )
    )

    model = ASTModel.from_pretrained(
        AST_MODEL_NAME
    )

    model.eval()
    model.to(device)

    for parameter in model.parameters():
        parameter.requires_grad = False

    return feature_extractor, model


def encode_batch(
    clips,
    feature_extractor,
    model,
    device,
):
    """

    It turns a list of raw audio clips into one embedding each

    """

    inputs = feature_extractor(
        clips,
        sampling_rate = AST_SAMPLE_RATE,
        return_tensors = "pt",
    )

    input_values = inputs[
        "input_values"
    ].to(device)

    with torch.no_grad():
        outputs = model(
            input_values = input_values
        )

    # The pooled output summarizes the whole clip in one vector
    embeddings = outputs.pooler_output

    return (
        embeddings
        .cpu()
        .numpy()
        .astype(np.float32)
    )


def resample_to_encoder_rate(
    clip,
    source_rate,
):
    """

    It converts one clip to the sample rate the encoder expects

    """

    import librosa

    if source_rate == AST_SAMPLE_RATE:
        return clip

    return librosa.resample(
        clip,
        orig_sr = source_rate,
        target_sr = AST_SAMPLE_RATE,
    )


def extract_all(
    feature_extractor,
    model,
    device,
    batch_size,
):
    """

    It walks the same clean clips that prepare_data.py keeps, so the
    labels and the grouping stay identical

    """

    audio_files = find_audio_files()

    embeddings = []
    labels = []
    hive_ids = []
    session_ids = []
    source_files = []

    pending_clips = []
    pending_count = 0

    start_time = time.perf_counter()

    print()
    print("Encoding clean clips ...")

    for file_number, path in enumerate(
        audio_files,
        start = 1,
    ):
        label, hive_id, session_id = (
            parse_filename(path)
        )

        audio, sample_rate = load_audio(
            path
        )

        intervals = read_lab_intervals(
            path
        )

        file_clean_count = 0

        for clip_index, clip in enumerate(
            split_into_clips(audio)
        ):
            clip_start = (
                clip_index * CLIP_SECONDS
            )

            clip_end = (
                clip_start + CLIP_SECONDS
            )

            # The same noBee filtering as the log mel pipeline
            if clip_overlaps_nobee(
                clip_start,
                clip_end,
                intervals,
            ):
                continue

            pending_clips.append(
                resample_to_encoder_rate(
                    clip,
                    sample_rate,
                )
            )

            labels.append(
                LABEL_TO_ID[label]
            )

            hive_ids.append(hive_id)
            session_ids.append(session_id)
            source_files.append(path.name)

            file_clean_count += 1
            pending_count += 1

            if (
                len(pending_clips)
                >= batch_size
            ):
                embeddings.append(
                    encode_batch(
                        pending_clips,
                        feature_extractor,
                        model,
                        device,
                    )
                )

                pending_clips = []

        elapsed = (
            time.perf_counter()
            - start_time
        )

        print(
            f"[{file_number:>2}/{len(audio_files)}] "
            f"{path.name}: "
            f"{file_clean_count} clean clips "
            f"| total {pending_count} "
            f"| elapsed {format_duration(elapsed)}"
        )

    if pending_clips:
        embeddings.append(
            encode_batch(
                pending_clips,
                feature_extractor,
                model,
                device,
            )
        )

    return (
        np.concatenate(embeddings, axis = 0),
        np.asarray(labels, dtype = np.int64),
        np.asarray(hive_ids, dtype = np.str_),
        np.asarray(session_ids, dtype = np.str_),
        np.asarray(source_files, dtype = np.str_),
    )


def main():
    program_start_time = time.perf_counter()

    arguments = parse_arguments()

    device = choose_device()

    print(f"Device: {device}")

    feature_extractor, model = load_encoder(
        device
    )

    (
        X,
        y,
        hive_ids,
        session_ids,
        source_files,
    ) = extract_all(
        feature_extractor,
        model,
        device,
        arguments.batch_size,
    )

    if len(X) != len(y):
        raise RuntimeError(
            f"Embedding and label counts do not "
            f"match -- {len(X)} and {len(y)}"
        )

    if not np.all(np.isfinite(X)):
        raise RuntimeError(
            "Embeddings contain NaN or infinite values"
        )

    output_path = build_output_path("ast")

    output_path.parent.mkdir(
        parents = True,
        exist_ok = True,
    )

    np.savez_compressed(
        output_path,
        X = X,
        y = y,
        hive_ids = hive_ids,
        session_ids = session_ids,
        source_files = source_files,
    )

    print()
    print(f"Clips encoded: {len(y)}")
    print(f"Embedding size: {X.shape[1]}")
    print(f"Hives: {len(np.unique(hive_ids))}")

    print(
        f"Recordings: "
        f"{len(np.unique(session_ids))}"
    )

    print(f"Saved to: {output_path}")

    print(
        f"Total program time: "
        f"{format_duration(time.perf_counter() - program_start_time)}"
    )


if __name__ == "__main__":
    main()
