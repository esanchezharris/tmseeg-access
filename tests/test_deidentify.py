"""De-identification tests. All data here is SYNTHETIC, including the planted identifiers."""

from __future__ import annotations

import json
import shutil
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from scipy.io import loadmat, savemat

from conftest import CHANNELS, write_recording
from tmseeg_access.dataset import Dataset
from tmseeg_access.deidentify import (
    LOG_NAME,
    date_offset,
    deidentify,
    scan_set_header,
    shift_datetime,
)
from tmseeg_access.download import compute_hash

FAKE_PATH = "/Users/synthetic.person/Desktop/study/901_SP_PP.dap"
FAKE_KEY = b"synthetic test key"


def plant_identifiers(root):
    """Add fake identifiers of the kinds found in real headers and sidecars."""
    set_path = root / "sub-901/eeg/sub-901_task-tmseeg_acq-parietal_eeg.set"
    content = {k: v for k, v in loadmat(set_path).items() if not k.startswith("__")}
    content["comments"] = f"Original file: {FAKE_PATH}"
    content["filepath"] = "/fs04/synthetic/bids/sub-901/eeg"
    content["history"] = f"EEG = loadcurry('{FAKE_PATH}');"
    content["chaninfo"] = {"filename": "/Users/synthetic.person/caps/cap.ced", "nosedir": "+X"}
    savemat(set_path, content, appendmat=False)
    sidecar = root / "sub-901/eeg/sub-901_task-tmseeg_acq-parietal_eeg.json"
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    data.update(InstitutionName="Synthetic University", InstitutionAddress="1 Fake Street")
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    (root / "sub-901/sub-901_scans.tsv").write_text(
        "filename\tacq_time\neeg/a.set\t2024-03-05T10:15:00\neeg/b.set\t2024-03-05T11:15:00\n"
        "eeg/c.set\tn/a\n",
        encoding="utf-8",
    )
    (root / "sub-901/eeg/sub-901_electrodes.tsv").write_text("name\tx\nFz\t1\n", encoding="utf-8")


@pytest.fixture()
def source(synthetic_root, tmp_path):
    root = tmp_path / "source"
    shutil.copytree(synthetic_root, root)
    plant_identifiers(root)
    return root


@pytest.fixture()
def output(tmp_path):
    return tmp_path / "output"


def run(source, output, **kwargs) -> dict:
    return deidentify(source, output, key=FAKE_KEY, **kwargs)


def test_source_is_untouched(source, output):
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    run(source, output)
    assert before == {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}


def test_header_text_is_removed_everywhere(source, output):
    run(source, output)
    path = output / "sub-901/eeg/sub-901_task-tmseeg_acq-parietal_eeg.set"
    raw_bytes = path.read_bytes()
    assert b"synthetic.person" not in raw_bytes
    assert b"fs04" not in raw_bytes
    assert scan_set_header(path) == []


def test_scan_finds_identifiers_before_they_are_removed(source):
    path = source / "sub-901/eeg/sub-901_task-tmseeg_acq-parietal_eeg.set"
    assert {"comments", "filepath", "history", "chaninfo"} <= set(scan_set_header(path))


def test_sidecar_fields_are_removed_and_others_kept(source, output):
    run(source, output)
    path = output / "sub-901/eeg/sub-901_task-tmseeg_acq-parietal_eeg.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "InstitutionName" not in data
    assert "InstitutionAddress" not in data
    assert data["SamplingFrequency"] == 1000


def test_signal_is_byte_identical(source, output):
    log = run(source, output)
    a = source / "sub-901/eeg/sub-901_task-tmseeg_acq-parietal_eeg.fdt"
    b = output / "sub-901/eeg/sub-901_task-tmseeg_acq-parietal_eeg.fdt"
    assert compute_hash(a, "sha256") == compute_hash(b, "sha256")
    assert log["signal_files_changed"] == []
    assert log["signal_files_identical_to_source"] == 2


def test_output_still_loads_and_epochs_match(source, output):
    run(source, output)
    before = Dataset(source).epochs_around_pulses("sub-901", "parietal").get_data()
    after = Dataset(output).epochs_around_pulses("sub-901", "parietal").get_data()
    assert np.array_equal(before, after)
    assert Dataset(output).load_raw("sub-901", acquisition="parietal").ch_names == CHANNELS


def test_dates_shift_but_keep_their_spacing(source, output):
    run(source, output)
    table = pd.read_csv(output / "sub-901/sub-901_scans.tsv", sep="\t", keep_default_na=False)
    times = pd.to_datetime(table["acq_time"][:2])
    assert (times.iloc[1] - times.iloc[0]) == timedelta(hours=1)
    assert times.iloc[0] < pd.Timestamp("2024-03-05")
    assert table["acq_time"].iloc[2] == "n/a"


def test_offsets_differ_by_subject_and_repeat_with_a_key():
    assert date_offset("sub-1", b"k") == date_offset("sub-1", b"k")
    assert date_offset("sub-1", b"k") != date_offset("sub-1", b"other")
    assert len({date_offset(f"sub-{i}", b"k") for i in range(20)}) > 1


@pytest.mark.parametrize("seed", range(50))
def test_offset_stays_in_range(seed):
    days = -date_offset(f"sub-{seed}", b"k").days
    assert 30 <= days <= 365


def test_non_dates_pass_through():
    assert shift_datetime("n/a", timedelta(days=-40)) == "n/a"


def test_subject_selection(source, output):
    run(source, output, subjects=["sub-901"])
    assert not (output / "sub-902").exists()
    assert pd.read_csv(output / "participants.tsv", sep="\t")["participant_id"].tolist() == [
        "sub-901"
    ]


def test_participant_columns_can_be_dropped(source, output):
    run(source, output, drop_participant_columns=["smoker"])
    assert "smoker" not in pd.read_csv(output / "participants.tsv", sep="\t").columns


def test_head_geometry_is_kept_unless_dropped(source, tmp_path):
    run(source, tmp_path / "kept")
    assert (tmp_path / "kept/sub-901/eeg/sub-901_electrodes.tsv").exists()
    log = run(source, tmp_path / "dropped", drop_head_geometry=True)
    assert not (tmp_path / "dropped/sub-901/eeg/sub-901_electrodes.tsv").exists()
    assert log["fields_changed"]["head_geometry.removed_files"] == 1


def test_unfinished_downloads_are_not_copied(source, output):
    leftover = source / "sub-901/eeg/sub-901_task-tmseeg_acq-parietal_eeg.set.part"
    leftover.write_text(FAKE_PATH, encoding="utf-8")
    run(source, output)
    assert not list(output.rglob("*.part"))


def test_subject_labels_work_with_or_without_the_prefix(source, output):
    run(source, output, subjects=["901"])
    assert (output / "sub-901").is_dir()


def test_unknown_subject_is_an_error_not_an_empty_copy(source, output):
    with pytest.raises(ValueError, match="sub-999"):
        run(source, output, subjects=["sub-999"])


def test_signal_can_be_left_out(source, output):
    run(source, output, include_signal=False)
    assert not list(output.rglob("*.fdt"))
    assert list(output.rglob("*.set"))


def test_free_text_fields_are_blanked_even_without_a_suspicious_pattern(source, output):
    path = source / "sub-901/eeg/sub-901_task-tmseeg_acq-parietal_eeg.set"
    content = {k: v for k, v in loadmat(path).items() if not k.startswith("__")}
    content["comments"] = "Plain note naming a person"
    savemat(path, content, appendmat=False)
    run(source, output)
    copied = (output / "sub-901/eeg/sub-901_task-tmseeg_acq-parietal_eeg.set").read_bytes()
    assert b"naming a person" not in copied


def test_refuses_to_write_inside_the_source(source):
    with pytest.raises(ValueError, match="outside"):
        run(source, source / "derivatives" / "deid")


def test_refuses_to_overwrite_a_non_empty_folder(source, output):
    output.mkdir()
    (output / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        run(source, output)


def test_log_has_counts_but_never_the_removed_values(source, output):
    log = run(source, output)
    text = (output / LOG_NAME).read_text(encoding="utf-8")
    assert "synthetic.person" not in text
    assert "Fake Street" not in text
    assert log["fields_changed"]["header.comments"] == 3  # one per .set file
    assert log["date_shift_key"] == "supplied by caller, not stored"
    assert "not a certification" in log["certification"].lower()
    assert log["headers_with_suspicious_text_after"] == {}


def test_generated_recordings_still_work_for_write_recording(tmp_path):
    write_recording(tmp_path, "sub-900_task-tmseeg_acq-control", [1.0], "control", seconds=3.0)
    assert (tmp_path / "sub-900_task-tmseeg_acq-control_eeg.fdt").exists()


def test_log_says_when_the_key_was_random(source, output):
    assert deidentify(source, output)["date_shift_key"] == "random, discarded"
