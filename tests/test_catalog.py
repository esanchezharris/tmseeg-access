"""Catalog tests against the synthetic fixture. Real-data tests skip without the dataset."""

from __future__ import annotations

import duckdb
import pytest

from tmseeg_access.catalog import build_catalog, default_path, query, read_set_header
from tmseeg_access.dataset import Dataset


@pytest.fixture()
def catalog(synthetic_root, tmp_path):
    path = tmp_path / "catalog.duckdb"
    build_catalog(Dataset(synthetic_root), path)
    return path


def test_every_recording_is_indexed_even_without_signal(catalog):
    table = query(catalog, "SELECT recording_id, has_signal FROM recordings ORDER BY 1")
    assert len(table) == 3
    assert table["has_signal"].sum() == 2


def test_recording_fields(catalog):
    row = query(
        catalog,
        "SELECT * FROM recordings WHERE recording_id = 'sub-901_task-tmseeg_acq-parietal'",
    ).iloc[0]
    assert row["pulse_count"] == 8
    assert row["channels_sidecar"] == row["channels_tsv"] == row["channels_header"] == 6
    assert row["sampling_rate_hz"] == row["sampling_rate_header_hz"] == 1000
    assert row["duration_s_header"] == row["duration_s_sidecar"] == 30


def test_header_columns_stay_null_when_the_header_is_absent(tmp_path, synthetic_root):
    path = tmp_path / "catalog.duckdb"
    ds = Dataset(synthetic_root)
    ds._recordings["has_header"] = False
    build_catalog(ds, path)
    assert query(path, "SELECT count(channels_header) AS n FROM recordings")["n"].item() == 0


def test_pulses_keep_suspected_duplicates(catalog):
    table = query(
        catalog,
        "SELECT count(*) AS n, sum(is_duplicate::INT) AS dup FROM pulses "
        "WHERE recording_id = 'sub-901_task-tmseeg_acq-control'",
    ).iloc[0]
    assert (table["n"], table["dup"]) == (10, 2)


def test_tables_join_on_subject(catalog):
    table = query(
        catalog,
        "SELECT r.recording_id, p.age, b.nback_accuracy FROM recordings r "
        "JOIN participants p USING (subject) JOIN behavior b USING (subject) "
        "WHERE r.recording_id = 'sub-901_task-tmseeg_acq-parietal'",
    ).iloc[0]
    assert table["age"] == 30
    assert table["nback_accuracy"] == pytest.approx(0.75)


def test_query_connection_cannot_write(catalog):
    with pytest.raises(duckdb.Error):
        query(catalog, "DELETE FROM recordings")


def test_failed_build_leaves_the_old_catalog_alone(catalog, synthetic_root, monkeypatch):
    before = query(catalog, "SELECT count(*) AS n FROM recordings")["n"].item()

    def boom(*_args):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr("tmseeg_access.catalog._file_rows", boom)
    with pytest.raises(RuntimeError):
        build_catalog(Dataset(synthetic_root), catalog)
    assert query(catalog, "SELECT count(*) AS n FROM recordings")["n"].item() == before


def test_header_reader_does_not_need_the_signal(synthetic_root):
    path = synthetic_root / "sub-902/eeg/sub-902_task-tmseeg_acq-parietal_eeg.set"
    assert read_set_header(path)["channels_header"] == 6


def test_default_location_is_under_derivatives(tmp_path):
    assert "derivatives" in default_path(tmp_path).parts
