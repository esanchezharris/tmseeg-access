"""Report tests against the SYNTHETIC fixture."""

from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
import pytest

from tmseeg_access.catalog import build_catalog
from tmseeg_access.checks import load_protocol, run_all
from tmseeg_access.dataset import Dataset
from tmseeg_access.report import (
    RULE_MEANINGS,
    gap_histogram,
    load_inputs,
    marker_count_table,
    rule_table,
    usable_gaps,
    write_report,
)


@pytest.fixture()
def inputs(synthetic_root, tmp_path):
    ds = Dataset(synthetic_root)
    catalog = tmp_path / "catalog.duckdb"
    build_catalog(ds, catalog)
    results = tmp_path / "results"
    results.mkdir()
    issues, extra = run_all(ds)
    issues.to_csv(results / "issues.csv", index=False)
    pd.DataFrame(extra["artifact"]).to_csv(results / "pulse_artifact.csv", index=False)
    (results / "check_summary.json").write_text(
        json.dumps({"coverage": extra["coverage"]}), encoding="utf-8"
    )
    return load_inputs(catalog, results)


def test_report_files_are_written(inputs, tmp_path):
    output = tmp_path / "report"
    path = write_report(inputs, output)
    assert path.exists()
    for name in ["issues.csv", "marker_counts.csv", "gap_histogram.csv", "report_facts.json"]:
        assert (output / name).exists()
    assert len(list((output / "charts").glob("*.png"))) == 4


def test_report_is_self_contained(inputs, tmp_path):
    text = write_report(inputs, tmp_path / "report").read_text(encoding="utf-8")
    assert "data:image/png;base64," in text
    assert not re.search(r'(?:src|href)="https?://', text)


def test_report_states_its_limits(inputs, tmp_path):
    text = write_report(inputs, tmp_path / "report").read_text(encoding="utf-8")
    assert "not a\nrandom sample" in text
    assert "Their\ncauses are not known" in text


def test_facts_match_the_inputs(inputs, tmp_path):
    output = tmp_path / "report"
    write_report(inputs, output)
    facts = json.loads((output / "report_facts.json").read_text(encoding="utf-8"))
    assert facts["subjects"] == 2
    assert facts["tmseeg_runs"] == 3
    assert facts["pulse_markers"] == 26
    assert facts["duplicate_markers"] == 2
    assert facts["distinct_pulses"] == 24
    assert facts["issues"] == len(inputs.issues)


def test_marker_bins_cover_every_run():
    recordings = pd.DataFrame(
        {"task": "tmseeg", "pulse_count": [108, 120, 120, 122, 200, 240, 240923]}
    )
    table = marker_count_table(recordings)
    assert table["runs"].sum() == 7
    assert table.set_index("markers_in_run")["runs"]["120"] == 2


def test_gaps_leave_out_duplicates_and_the_first_marker():
    pulses = pd.DataFrame(
        {"gap_from_previous_s": [np.nan, 0.0001, 3.0], "is_duplicate": [False, True, False]}
    )
    assert usable_gaps(pulses).tolist() == [3.0]


def test_gap_histogram_counts_within_range():
    table = gap_histogram(np.array([3.05, 3.05, 5.0, 40.0]))
    assert table["gaps"].sum() == 3
    assert table.loc[table["gap_from_s"] == 3.0, "gaps"].item() == 2


def test_rule_table_puts_errors_first():
    issues = pd.DataFrame(
        {
            "rule": ["pulse.count", "pulse.count", "pulse.duplicate"],
            "severity": ["warning"] * 2 + ["error"],
        }
    )
    assert rule_table(issues)["rule"].tolist() == ["pulse.duplicate", "pulse.count"]


def test_every_rule_in_the_package_has_a_plain_meaning():
    from pathlib import Path

    from tmseeg_access import checks

    folder = Path(checks.__file__).parent
    source = " ".join(path.read_text(encoding="utf-8") for path in folder.glob("*.py"))
    found = set(
        re.findall(
            r'"((?:pulse|signal|sidecar|channels|header|recording|rate|participant'
            r'|protocol|dataset|metadata)\.[a-z_]+)"',
            source,
        )
    )
    assert found
    assert found - {"channels.tsv"} <= set(RULE_MEANINGS)  # that one is a file name


def test_protocol_is_available_to_the_report_user():
    assert load_protocol()["published"]["pulses_per_run"] == 120
