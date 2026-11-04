"""Dataset API tests. ``synthetic_root`` is synthetic; ``real_root`` tests skip without the data."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from conftest import CHANNELS, MARKER_CHANNEL, MARKER_UV
from tmseeg_access.dataset import (
    DataNotLocalError,
    Dataset,
    DuplicatePulseError,
    flag_duplicates,
)


@pytest.fixture()
def ds(synthetic_root) -> Dataset:
    return Dataset(synthetic_root)


def test_rejects_a_folder_that_is_not_bids(tmp_path):
    with pytest.raises(FileNotFoundError, match="Not a BIDS"):
        Dataset(tmp_path)


def test_path_can_come_from_the_environment(synthetic_root, monkeypatch):
    monkeypatch.setenv("TMSEEG_DATA_ROOT", str(synthetic_root))
    assert Dataset().subjects() == ["sub-901", "sub-902"]


def test_subjects_and_sessions(ds):
    assert ds.subjects() == ["sub-901", "sub-902"]
    assert ds.sessions("sub-901") == []
    assert ds.sessions("901") == []
    with pytest.raises(KeyError):
        ds.sessions("sub-999")


def test_recordings_show_what_is_local(ds):
    table = ds.recordings(task="tmseeg")
    assert len(table) == 3
    local = table.set_index(["subject", "acquisition"])["has_signal"]
    assert bool(local["sub-901", "parietal"]) is True
    assert bool(local["sub-902", "parietal"]) is False


def test_metadata_joins_participants_and_behaviour(ds):
    meta = ds.metadata()
    assert len(meta) == 3
    row = meta[(meta.subject == "sub-901") & (meta.acquisition == "parietal")].iloc[0]
    assert row["age"] == 30
    assert row["pulse_count"] == 8
    assert row["nback_accuracy"] == pytest.approx(0.75)
    other = meta[meta.subject == "sub-902"].iloc[0]
    assert pd.isna(other["smoker"])
    assert pd.isna(other["nback_accuracy"])


def test_behavior_is_trial_level_with_subject(ds):
    table = ds.behavior("nback")
    assert len(table) == 4
    assert set(table["subject"]) == {"sub-901"}
    with pytest.raises(KeyError):
        ds.behavior("missing")


def test_pulses_flag_duplicates_without_removing_them(ds):
    pulses = ds.pulses("sub-901", "control")
    assert len(pulses) == 10
    assert int(pulses["is_duplicate"].sum()) == 2


def test_flag_duplicates_uses_a_window_not_equality():
    table = pd.DataFrame({"onset": [1.0, 1.0001, 4.0]})
    flagged = flag_duplicates(table, 1000, 0.002)
    assert flagged["is_duplicate"].tolist() == [False, True, False]
    assert flagged["onset_sample"].tolist() == [1000, 1000, 4000]


def test_onset_sample_comes_from_onset_not_the_one_based_column(ds):
    pulses = ds.pulses("sub-901", "parietal")
    assert pulses["onset_sample"].iloc[0] == 2000
    assert pulses["sample"].iloc[0] == 2001


def test_load_raw_is_lazy_and_returns_independent_copies(ds):
    raw = ds.load_raw("sub-901", acquisition="parietal")
    assert raw.preload is False
    assert raw.info["sfreq"] == 1000
    first = ds.load_raw("sub-901", acquisition="parietal", preload=True)
    first._data[:] = 0
    second = ds.load_raw("sub-901", acquisition="parietal", preload=True)
    assert not np.allclose(second.get_data(), 0)


def test_repeat_load_uses_the_cache(ds):
    ds.load_raw("sub-901", acquisition="parietal")
    before = ds._open_raw.cache_info().hits
    ds.load_raw("sub-901", acquisition="parietal")
    assert ds._open_raw.cache_info().hits == before + 1


def test_missing_signal_says_how_to_get_it(ds):
    with pytest.raises(DataNotLocalError, match="tmseeg-access download"):
        ds.load_raw("sub-902", acquisition="parietal")


def test_session_argument_is_rejected_clearly(ds):
    with pytest.raises(ValueError, match="no sessions"):
        ds.load_raw("sub-901", session="01", acquisition="parietal")


def test_unknown_recording_raises(ds):
    with pytest.raises(KeyError):
        ds.load_raw("sub-901", acquisition="occipital")


def test_epochs_land_on_the_right_samples(ds):
    epochs = ds.epochs_around_pulses("sub-901", "parietal", tmin=-0.1, tmax=0.2)
    assert len(epochs) == 8
    assert epochs.events[0, 0] == 2000
    assert epochs.get_data().shape == (8, 6, 301)
    assert epochs.metadata["event_id"].iloc[0] == "event-000001"


def test_time_zero_is_the_pulse_sample_on_the_right_channel(ds):
    epochs = ds.epochs_around_pulses("sub-901", "parietal", tmin=-0.1, tmax=0.2)
    mean_uv = epochs.get_data().mean(axis=0) * 1e6
    channel, sample = np.unravel_index(np.argmax(mean_uv), mean_uv.shape)
    assert epochs.ch_names[channel] == CHANNELS[MARKER_CHANNEL]
    assert epochs.times[sample] == pytest.approx(0)
    assert mean_uv.max() == pytest.approx(MARKER_UV)


def test_duplicates_stop_epoching_by_default(ds):
    with pytest.raises(DuplicatePulseError, match="pulse.duplicate"):
        ds.epochs_around_pulses("sub-901", "control")


def test_keep_first_is_explicit_and_recorded(ds):
    epochs = ds.epochs_around_pulses("sub-901", "control", on_duplicate="keep_first")
    assert len(epochs) == 8
    record = json.loads(epochs.info["description"])
    assert record["on_duplicate"] == "keep_first"
    assert record["markers_in_events_tsv"] == 10
    assert record["duplicates_removed"] == 2


def test_channels_are_kept_unless_excluded_and_exclusions_are_recorded(ds):
    assert "Oz" in ds.epochs_around_pulses("sub-901", "parietal").ch_names
    epochs = ds.epochs_around_pulses("sub-901", "parietal", exclude_channels=("Oz", "NOT_THERE"))
    assert "Oz" not in epochs.ch_names
    assert json.loads(epochs.info["description"])["channels_excluded"] == ["Oz"]


def test_bad_duplicate_policy_is_rejected(ds):
    with pytest.raises(ValueError, match="on_duplicate"):
        ds.epochs_around_pulses("sub-901", "control", on_duplicate="ignore")


@pytest.mark.realdata
def test_real_sample_column_is_one_based_latency(real_root):
    ds = Dataset(real_root)
    events = ds.events("sub-001", acquisition="parietal")
    assert np.abs((events["sample"] - 1) / 1000 - events["onset"]).max() <= 0.00051


@pytest.mark.realdata
def test_real_epochs_for_one_subject(real_root):
    ds = Dataset(real_root)
    epochs = ds.epochs_around_pulses("sub-001", "parietal", tmin=-0.1, tmax=0.5)
    assert len(epochs) == 120
    assert epochs.info["sfreq"] == 1000
    assert len(epochs.ch_names) == 62


@pytest.mark.realdata
def test_real_doubled_markers_stop_epoching_before_any_signal_is_read(real_root):
    ds = Dataset(real_root)
    with pytest.raises(DuplicatePulseError):
        ds.epochs_around_pulses("sub-136", "parietal")
