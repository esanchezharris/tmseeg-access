"""Shared fixtures. Everything built here is SYNTHETIC test data, not real recordings."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.io import savemat

RATE = 1000
CHANNELS = ["Fz", "Cz", "Pz", "Oz", "C3", "C4"]
MARKER_CHANNEL = 1
MARKER_UV = 500.0
PULSE_ONSETS = [round(2.0 + 3.0 * i, 4) for i in range(8)]


def write_eeglab_pair(directory: Path, stem: str, data_uv: np.ndarray) -> None:
    """Write signal the way ds008037 stores it: a header ``.set`` plus a float32 ``.fdt``."""
    fdt_name = f"{stem}_eeg.fdt"
    # EEGLAB multiplexes: every channel at time 0, then every channel at time 1, and so on.
    data_uv.T.astype("float32").tofile(directory / fdt_name)
    n_channels, n_samples = data_uv.shape
    locations = np.zeros(n_channels, dtype=[("labels", object), ("type", object)])
    locations["labels"] = CHANNELS
    locations["type"] = "EEG"
    savemat(
        directory / f"{stem}_eeg.set",
        {
            "setname": stem,
            "filename": f"{stem}_eeg.set",
            "filepath": "",
            "comments": "SYNTHETIC",
            "nbchan": float(n_channels),
            "trials": 1.0,
            "pnts": float(n_samples),
            "srate": float(RATE),
            "xmin": 0.0,
            "xmax": (n_samples - 1) / RATE,
            "data": fdt_name,
            "datfile": fdt_name,
            "times": np.array([]),
            "ref": "common",
            "event": np.array([]),
            "epoch": np.array([]),
            "chanlocs": locations,
            "icawinv": np.array([]),
            "icasphere": np.array([]),
            "icaweights": np.array([]),
            "icaact": np.array([]),
            "icachansind": np.array([]),
        },
        appendmat=False,
    )


def write_recording(
    directory: Path,
    stem: str,
    onsets: list[float],
    label: str,
    *,
    seconds: float = 30.0,
    with_signal: bool = True,
) -> None:
    """Write one synthetic EEGLAB recording with BIDS sidecars."""
    rng = np.random.default_rng(len(stem) + len(onsets))
    data_uv = rng.normal(0, 5, (len(CHANNELS), int(seconds * RATE))).astype("float32")
    for onset in onsets:  # a marker spike, so tests can prove epochs land on the right sample
        data_uv[MARKER_CHANNEL, round(onset * RATE)] = MARKER_UV
    write_eeglab_pair(directory, stem, data_uv)
    sidecar = {
        "TaskName": "SYNTHETIC",
        "SamplingFrequency": RATE,
        "EEGChannelCount": len(CHANNELS),
        "RecordingDuration": seconds,
        "EEGReference": "FCz",
        "PowerLineFrequency": 50,
        "SoftwareFilters": "n/a",
    }
    (directory / f"{stem}_eeg.json").write_text(json.dumps(sidecar), encoding="utf-8")
    channels = pd.DataFrame({"name": CHANNELS, "type": "EEG", "units": "uV"})
    channels.to_csv(directory / f"{stem}_channels.tsv", sep="\t", index=False)
    events = pd.DataFrame(
        {
            "onset": onsets,
            "duration": 0,
            "sample": [round(x * RATE) + 1 for x in onsets],
            "trial_type": label,
            "value": label.title(),
            "is_tms_pulse": 1,
            "event_id": [f"event-{i + 1:06d}" for i in range(len(onsets))],
        }
    )
    events.to_csv(directory / f"{stem}_events.tsv", sep="\t", index=False)
    if not with_signal:
        (directory / f"{stem}_eeg.fdt").unlink()


@pytest.fixture(scope="session")
def synthetic_root(tmp_path_factory) -> Path:
    """A tiny BIDS dataset: clean, doubled-marker, metadata-only and task recordings."""
    root = tmp_path_factory.mktemp("synthetic_bids")
    (root / "dataset_description.json").write_text(
        json.dumps({"Name": "SYNTHETIC test fixture, not real data", "BIDSVersion": "1.9.0"}),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "participant_id": ["sub-901", "sub-902"],
            "age": [30, 40],
            "sex": ["female", "male"],
            "smoker": ["No", "n/a"],
        }
    ).to_csv(root / "participants.tsv", sep="\t", index=False)

    for subject in ["sub-901", "sub-902"]:
        (root / subject / "eeg").mkdir(parents=True)
        (root / subject / "beh").mkdir()

    eeg = root / "sub-901" / "eeg"
    write_recording(eeg, "sub-901_task-tmseeg_acq-parietal", PULSE_ONSETS, "parietal")
    doubled = sorted([*PULSE_ONSETS, *(x + 0.0005 for x in PULSE_ONSETS[:2])])
    write_recording(eeg, "sub-901_task-tmseeg_acq-control", doubled, "control")

    eeg = root / "sub-902" / "eeg"
    write_recording(
        eeg, "sub-902_task-tmseeg_acq-parietal", PULSE_ONSETS, "parietal", with_signal=False
    )

    pd.DataFrame({"trial": [1, 2, 3, 4], "correctness": [1, 1, 0, 1]}).to_csv(
        root / "sub-901" / "beh" / "sub-901_task-nback_beh.tsv", sep="\t", index=False
    )
    return root


def real_data_root() -> Path | None:
    value = os.environ.get("TMSEEG_DATA_ROOT")
    if value is None or not (Path(value) / "dataset_description.json").exists():
        return None
    return Path(value)


@pytest.fixture(scope="session")
def real_root() -> Path:
    root = real_data_root()
    if root is None:
        pytest.skip("Real dataset not available: TMSEEG_DATA_ROOT is unset")
    return root
