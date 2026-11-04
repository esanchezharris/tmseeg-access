"""MATLAB export round trips. Files are read back in Python: MATLAB itself is not used here."""

from __future__ import annotations

import json

import mne
import numpy as np
import pandas as pd
import pytest
from scipy.io import loadmat

from tmseeg_access.dataset import Dataset
from tmseeg_access.matlab import (
    export_epochs_mat,
    export_epochs_set,
    export_metadata,
    read_epochs_mat,
    read_metadata_mat,
)

# float32 storage in .set rounds values, so allow a tiny difference there. Values are in volts.
SET_TOLERANCE_V = 1e-11


@pytest.fixture()
def epochs(synthetic_root):
    return Dataset(synthetic_root).epochs_around_pulses(
        "sub-901", "control", tmin=-0.1, tmax=0.2, on_duplicate="keep_first", baseline=(-0.1, 0)
    )


def test_mat_round_trip_keeps_signal_times_and_channels(epochs, tmp_path):
    back = read_epochs_mat(export_epochs_mat(epochs, tmp_path / "e.mat"))
    assert back["data_uv"].shape == (8, 6, 301)
    assert np.allclose(back["data_uv"], epochs.get_data() * 1e6, rtol=1e-12, atol=1e-9)
    assert np.allclose(back["times_s"], epochs.times)
    assert back["channels"] == epochs.ch_names
    assert back["sampling_rate_hz"] == 1000


def test_mat_round_trip_keeps_the_epoch_table_and_provenance(epochs, tmp_path):
    back = read_epochs_mat(export_epochs_mat(epochs, tmp_path / "e.mat"))
    assert list(back["epochs_table"]["event_id"]) == epochs.metadata["event_id"].tolist()
    assert back["provenance"]["on_duplicate"] == "keep_first"
    assert back["provenance"]["duplicates_removed"] == 2


def test_set_round_trip_keeps_signal_and_channels(epochs, tmp_path):
    path = export_epochs_set(epochs, tmp_path / "e.set")
    back = mne.read_epochs_eeglab(path, verbose="ERROR")
    assert back.ch_names == epochs.ch_names
    assert back.info["sfreq"] == epochs.info["sfreq"]
    assert np.allclose(back.get_data(), epochs.get_data(), atol=SET_TOLERANCE_V)
    assert np.allclose(back.times, epochs.times)


def test_set_has_one_event_per_epoch_at_time_zero(epochs, tmp_path):
    """MNE passes raw-time annotations along, and they must not become events in the epochs."""
    assert len(epochs.annotations) > 0
    path = export_epochs_set(epochs, tmp_path / "e.set")
    content = loadmat(path, squeeze_me=True, struct_as_record=False)
    events = np.atleast_1d(content["event"])
    assert len(events) == len(epochs)
    pulse_sample = int(np.argmin(np.abs(epochs.times)))
    positions = [(float(e.latency) - 1) % int(content["pnts"]) for e in events]
    assert np.allclose(positions, pulse_sample)
    assert [int(e.epoch) for e in events] == list(range(1, len(epochs) + 1))


def test_set_keeps_its_table_and_provenance_beside_it(epochs, tmp_path):
    export_epochs_set(epochs, tmp_path / "e.set")
    table = pd.read_csv(tmp_path / "e_epochs.csv")
    assert table["event_id"].tolist() == epochs.metadata["event_id"].tolist()
    record = json.loads((tmp_path / "e_provenance.json").read_text(encoding="utf-8"))
    assert record["duplicates_removed"] == 2


def test_mat_round_trip_keeps_shape_for_one_epoch_and_one_channel(epochs, tmp_path):
    small = epochs[0].copy().pick([epochs.ch_names[0]])
    back = read_epochs_mat(export_epochs_mat(small, tmp_path / "s.mat"))
    assert back["data_uv"].shape == (1, 1, len(small.times))
    assert back["channels"] == small.ch_names
    assert len(back["epochs_table"]["event_id"]) == 1


def test_metadata_round_trip_keeps_values_and_gaps(synthetic_root, tmp_path):
    table = Dataset(synthetic_root).metadata()
    back = read_metadata_mat(export_metadata(table, tmp_path / "m.mat"))
    assert back["subject"].tolist() == table["subject"].tolist()
    assert list(back.columns) == list(table.columns)
    assert back["pulse_count"].tolist() == table["pulse_count"].astype(int).tolist()
    assert np.isnan(back.loc[table["subject"] == "sub-902", "nback_accuracy"]).all()


def test_true_and_false_become_one_and_zero(tmp_path):
    table = pd.DataFrame({"has_signal": [True, False], "subject": ["a", "b"]})
    back = read_metadata_mat(export_metadata(table, tmp_path / "m.mat"))
    assert back["has_signal"].tolist() == [1.0, 0.0]


@pytest.mark.realdata
def test_real_epochs_round_trip_through_both_formats(real_root, tmp_path):
    epochs = Dataset(real_root).epochs_around_pulses("sub-001", "parietal", baseline=(-0.1, -0.01))
    back = read_epochs_mat(export_epochs_mat(epochs, tmp_path / "e.mat"))
    assert np.allclose(back["data_uv"], epochs.get_data() * 1e6, atol=1e-6)
    loaded = mne.read_epochs_eeglab(export_epochs_set(epochs, tmp_path / "e.set"), verbose="ERROR")
    assert loaded.get_data().shape == epochs.get_data().shape
    assert np.abs(loaded.get_data() - epochs.get_data()).max() < 1e-9
