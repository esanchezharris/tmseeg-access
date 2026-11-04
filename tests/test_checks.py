"""Each rule gets a planted fault in SYNTHETIC data, and clean data must raise nothing."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from tmseeg_access.checks import (
    consistency,
    issues_frame,
    load_protocol,
    run_all,
    sidecars,
    signal,
    timing,
)
from tmseeg_access.checks.issues import Issue
from tmseeg_access.dataset import Dataset

PROTOCOL = load_protocol()
SITES = PROTOCOL["dataset"]["sites"]


def clean_onsets() -> np.ndarray:
    return 5.0 + 3.0 * np.arange(120)


def pulses_frame(onsets: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"onset": onsets, "sample": np.rint(onsets * 1000) + 1})


def rules(found: list[Issue]) -> list[str]:
    return [issue.rule for issue in found]


def run_timing(onsets: np.ndarray, duration: float | None = 500.0) -> list[Issue]:
    return timing.check_run(pulses_frame(onsets), PROTOCOL, "sub-901", "rec", duration)


def test_clean_run_raises_nothing():
    assert run_timing(clean_onsets()) == []


def test_every_issue_says_what_where_rule_and_action():
    onsets = np.insert(clean_onsets(), 4, clean_onsets()[3] + 0.0002)
    issue = next(i for i in run_timing(onsets) if i.rule == "pulse.duplicate")
    assert issue.observed and issue.where and issue.suggested_action and issue.expected
    assert (issue.subject, issue.recording_id) == ("sub-901", "rec")


def test_issue_rejects_unknown_severity():
    with pytest.raises(ValueError, match="severity"):
        Issue("r", "fatal", "w", "o", "e", "a")


def test_empty_issue_list_still_has_columns():
    assert "suggested_action" in issues_frame([]).columns


def test_duplicate_within_window_is_caught_and_not_counted_as_extra():
    onsets = np.sort(np.append(clean_onsets(), clean_onsets()[:4] + 0.0003))
    found = rules(run_timing(onsets))
    assert found == ["pulse.duplicate"]


def test_exactly_identical_markers_are_duplicates():
    onsets = np.sort(np.append(clean_onsets(), clean_onsets()[0]))
    assert rules(run_timing(onsets)) == ["pulse.duplicate"]


def test_stream_of_markers_is_a_burst_not_a_doubled_pulse():
    ticks = clean_onsets()[20] + 0.0001 * np.arange(1, 5000)
    found = rules(run_timing(np.sort(np.concatenate([clean_onsets(), ticks]))))
    assert "pulse.duplicate" in found
    assert "pulse.marker_burst" in found


def test_doubled_markers_alone_are_not_a_burst():
    onsets = np.sort(np.append(clean_onsets(), clean_onsets() + 0.0001))
    assert rules(run_timing(onsets)) == ["pulse.duplicate"]


def test_short_run_is_caught():
    assert rules(run_timing(clean_onsets()[:108])) == ["pulse.count"]


def test_missed_pulse_gives_a_count_and_a_long_gap():
    found = rules(run_timing(np.delete(clean_onsets(), 50)))
    assert sorted(found) == ["pulse.count", "pulse.gap_long"]


def test_extra_pulse_gives_a_count_and_a_short_gap():
    onsets = np.sort(np.append(clean_onsets(), clean_onsets()[10] + 0.4))
    assert sorted(rules(run_timing(onsets))) == ["pulse.count", "pulse.gap_short"]


def test_out_of_order_marker_is_caught():
    onsets = clean_onsets()
    onsets[[4, 5]] = onsets[[5, 4]]
    assert "pulse.out_of_order" in rules(run_timing(onsets))


def test_marker_past_the_end_is_caught():
    assert "pulse.outside_recording" in rules(run_timing(clean_onsets(), duration=100.0))


def test_duration_is_optional():
    assert run_timing(clean_onsets(), duration=None) == []


def test_sample_column_disagreement_is_caught():
    frame = pulses_frame(clean_onsets())
    frame.loc[7, "sample"] += 50
    found = timing.check_run(frame, PROTOCOL, "sub-901", "rec", 500.0)
    assert rules(found) == ["pulse.sample_mismatch"]


def test_spacing_outside_the_published_range_is_reported_once():
    found = timing.check_published_spacing(np.full(1000, 3.0), PROTOCOL)
    assert rules(found) == ["protocol.spacing"]


def test_spacing_inside_the_published_range_passes():
    assert timing.check_published_spacing(np.full(1000, 5.0), PROTOCOL) == []


def recordings(subject_sites: dict[str, list[str]]) -> pd.DataFrame:
    rows = [
        {"subject": s, "task": "tmseeg", "acquisition": a}
        for s, sites in subject_sites.items()
        for a in sites
    ]
    return pd.DataFrame(rows)


def test_missing_run_is_caught():
    table = recordings({"sub-1": SITES, "sub-2": SITES[:3]})
    found = consistency.check_missing_runs(table, ["sub-1", "sub-2"], PROTOCOL)
    assert rules(found) == ["recording.missing"]
    assert found[0].subject == "sub-2"
    assert SITES[3] in found[0].observed


def test_subject_with_no_runs_is_caught():
    found = consistency.check_missing_runs(
        recordings({"sub-1": SITES}), ["sub-1", "sub-3"], PROTOCOL
    )
    assert all(site in found[0].observed for site in SITES)


def test_uniform_rates_and_channels_pass():
    table = pd.DataFrame(
        {
            "subject": ["sub-1", "sub-2"],
            "task": "tmseeg",
            "sampling_rate_hz": [1000, 1000],
            "channels_sidecar": [62, 62],
        }
    )
    assert consistency.check_uniform(table) == []


def test_differing_rate_and_channels_are_caught():
    table = pd.DataFrame(
        {
            "subject": ["sub-1", "sub-2", "sub-3"],
            "task": "tmseeg",
            "sampling_rate_hz": [1000, 1000, 500],
            "channels_sidecar": [62, 63, 63],
        }
    )
    assert sorted(rules(consistency.check_uniform(table))) == [
        "channels.inconsistent",
        "rate.inconsistent",
    ]


def test_channel_names_compare_to_the_common_set():
    names = {
        "a": ("sub-1", ["Fz", "Cz"]),
        "b": ("sub-2", ["Cz", "Fz"]),
        "c": ("sub-3", ["Fz", "Cz", "Pz"]),
    }
    found = consistency.check_channel_names(names)
    assert rules(found) == ["channels.names_differ"]
    assert found[0].recording_id == "c"
    assert "PZ" in found[0].observed


def test_case_and_trigger_are_not_name_differences():
    names = {
        "a": ("sub-1", ["FZ", "CZ", "TRIGGER"]),
        "b": ("sub-2", ["FZ", "CZ", "TRIGGER"]),
        "c": ("sub-3", ["Fz", "Cz"]),
    }
    assert consistency.check_channel_names(names) == []


def test_two_spellings_of_an_electrode_are_reported_once():
    names = {"a": ("sub-1", ["CZ"]), "b": ("sub-2", ["CZ"]), "c": ("sub-3", ["Cz"])}
    found = consistency.check_name_spelling(names)
    assert rules(found) == ["channels.name_spelling"]
    assert found[0].where.startswith("1 recordings")


def test_one_spelling_throughout_passes():
    assert consistency.check_name_spelling({"a": ("sub-1", ["CZ"]), "b": ("sub-2", ["FZ"])}) == []


def test_trigger_typed_as_eeg_is_caught():
    rows = {"a": ("sub-1", "EEG"), "b": ("sub-2", "TRIG")}
    found = consistency.check_trigger_typed_as_eeg(rows)
    assert rules(found) == ["channels.trigger_typed_as_eeg"]
    assert found[0].where == "1 recordings in 1 subjects"


def test_properly_typed_trigger_passes():
    assert consistency.check_trigger_typed_as_eeg({"a": ("sub-1", "TRIG")}) == []


def test_participants_both_directions_and_gaps():
    people = pd.DataFrame({"subject": ["sub-1", "sub-2"], "age": [20, None]})
    table = recordings({"sub-1": SITES, "sub-3": SITES})
    found = rules(consistency.check_participants(people, table))
    assert sorted(found) == [
        "participant.missing_value",
        "participant.no_recordings",
        "participant.unlisted",
    ]


HEADER = {"srate": 1000, "nbchan": 2, "pnts": 3000, "labels": ["Fz", "Cz"], "n_events": 5}
SIDECAR = {"SamplingFrequency": 1000, "EEGChannelCount": 2, "RecordingDuration": 3.0}


def compare(sidecar=None, header=None, tsv=("Fz", "Cz"), events=5) -> list[str]:
    found = sidecars.compare_with_header(
        "rec", "sub-1", sidecar or SIDECAR, header or HEADER, list(tsv), events, PROTOCOL
    )
    return rules(found)


def test_matching_sidecar_and_header_pass():
    assert compare() == []


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"SamplingFrequency": 5000}, "sidecar.sampling_rate"),
        ({"EEGChannelCount": 3}, "sidecar.channel_count"),
        ({"RecordingDuration": 4.0}, "sidecar.duration"),
    ],
)
def test_sidecar_disagreements(change, rule):
    assert compare(sidecar={**SIDECAR, **change}) == [rule]


def test_channel_names_differ_from_header():
    assert compare(tsv=("Fz", "Pz")) == ["sidecar.channel_names"]


def test_channel_order_differs_from_header():
    assert compare(tsv=("Cz", "Fz")) == ["sidecar.channel_names"]


def test_event_count_differs_from_header():
    assert compare(events=6) == ["sidecar.event_count"]


def provenance(comments: str, record: dict | None = None) -> list[str]:
    found = sidecars.check_header_provenance(
        "rec", "sub-1", "parietal", comments, record or {"interpolated": "yes"}, PROTOCOL
    )
    return rules(found)


def test_matching_site_code_passes():
    assert provenance("Original file: /x/001_SP_PP.dap") == []


def test_site_code_disagreeing_with_the_label_is_caught():
    assert provenance("Original file: /x/001_SP_DLPFC.dap") == ["header.site_mismatch"]


def test_filename_without_a_site_code_is_not_a_mismatch():
    assert provenance("Original file: sub-1_task-tmseeg_acq-parietal_eeg.eeg") == []


def test_absent_artifact_record_is_noted():
    found = sidecars.check_header_provenance("rec", "sub-1", "parietal", "", None, PROTOCOL)
    assert rules(found) == ["header.no_artifact_record"]


def test_dangling_reference_is_caught(tmp_path):
    eeg = tmp_path / "sub-1" / "eeg"
    eeg.mkdir(parents=True)
    (eeg / "sub-1_eeg.json").write_text(
        json.dumps({"Note": "see *_nibs.tsv/json files"}), encoding="utf-8"
    )
    assert rules(sidecars.check_dangling_references(tmp_path)) == ["sidecar.dangling_reference"]
    (eeg / "sub-1_nibs.tsv").write_text("x", encoding="utf-8")
    assert sidecars.check_dangling_references(tmp_path) == []


def test_raw_label_is_noted(tmp_path):
    (tmp_path / "dataset_description.json").write_text('{"DatasetType": "raw"}', encoding="utf-8")
    assert rules(sidecars.check_dataset_type(tmp_path)) == ["dataset.not_raw"]


def test_absent_dose_is_reported_and_present_dose_is_not(tmp_path):
    assert rules(sidecars.check_stimulation_dose(["age"], tmp_path)) == [
        "metadata.no_stimulation_dose"
    ]
    assert sidecars.check_stimulation_dose(["age", "intensity_pct"], tmp_path) == []


def noise(seed: int = 1, channels: int = 4, samples: int = 20000) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 5, (channels, samples))


NAMES = ["A", "B", "C", "D"]


def channel_rules(data: np.ndarray) -> list[str]:
    return rules(signal.check_channels(data, NAMES, PROTOCOL, "sub-1", "rec"))


def test_normal_channels_pass():
    assert channel_rules(noise()) == []


def test_flat_channel_is_caught():
    data = noise()
    data[2] = 12.5
    found = signal.check_channels(data, NAMES, PROTOCOL, "sub-1", "rec")
    assert rules(found) == ["signal.flat_channel"]
    assert "C" in found[0].where


def test_clipped_channel_is_caught():
    data = noise()
    data[1, 500:600] = data[1].max() + 1
    assert channel_rules(data) == ["signal.saturated_channel"]


def test_flat_trigger_is_normal_but_a_flat_eeg_channel_is_not():
    data = noise()
    data[3] = 0.0
    names = ["A", "B", "C", "TRIGGER"]
    assert rules(signal.check_channels(data, names, PROTOCOL, "sub-1", "rec")) == []
    data[0] = 0.0
    found = signal.check_channels(data, names, PROTOCOL, "sub-1", "rec")
    assert rules(found) == ["signal.flat_channel"]


def test_trigger_with_signal_is_noted():
    names = ["A", "B", "C", "TRIGGER"]
    found = signal.check_channels(noise(), names, PROTOCOL, "sub-1", "rec")
    assert rules(found) == ["signal.trigger_not_flat"]


def pulse_samples() -> np.ndarray:
    return np.arange(1000, 121000, 1000)


def realistic_noise() -> np.ndarray:
    """The size of a real run: 120 pulses on 62 channels gives a stable median."""
    return noise(channels=62, samples=125000)


def measure(data: np.ndarray) -> dict:
    return signal.measure_pulse_artifact(data, pulse_samples(), PROTOCOL)


def test_markers_with_no_signal_change_are_caught():
    found = signal.check_pulse_artifact(measure(realistic_noise()), PROTOCOL, "sub-1", "rec")
    assert rules(found) == ["signal.no_pulse_signature"]


def test_interpolated_window_alone_is_acceptable():
    data = realistic_noise()
    for sample in pulse_samples():
        for channel in range(data.shape[0]):
            start, stop = sample - 1, sample + 5
            data[channel, start : stop + 1] = np.linspace(
                data[channel, start], data[channel, stop], stop - start + 1
            )
    measured = measure(data)
    assert measured["smooth_offsets_in_window"] >= 4
    assert signal.check_pulse_artifact(measured, PROTOCOL, "sub-1", "rec") == []


def test_disturbance_outside_the_window_is_caught():
    data = realistic_noise()
    rng = np.random.default_rng(2)
    for sample in pulse_samples():
        data[:, sample : sample + 15] += rng.normal(0, 200, (62, 15))
    measured = measure(data)
    found = signal.check_pulse_artifact(measured, PROTOCOL, "sub-1", "rec")
    assert rules(found) == ["signal.residual_pulse_artifact"]
    assert measured["rough_to_ms"] >= 14
    assert found[0].severity == "warning"


def test_large_artifact_is_an_error_and_reports_its_size():
    data = realistic_noise()
    rng = np.random.default_rng(3)
    for sample in pulse_samples():
        data[:, sample : sample + 12] += rng.normal(5000, 500, (62, 12))
    measured = measure(data)
    found = signal.check_pulse_artifact(measured, PROTOCOL, "sub-1", "rec")
    assert found[0].severity == "error"
    assert measured["peak_deviation_uv"] > 3000


def test_artifact_says_when_the_header_claims_interpolation():
    measured = {
        "rough_from_ms": -5,
        "rough_to_ms": 15,
        "smooth_offsets_in_window": 0,
        "peak_deviation_uv": 9000.0,
        "peak_deviation_at_ms": 4,
    }
    found = signal.check_pulse_artifact(measured, PROTOCOL, "sub-1", "rec", True)
    assert "header records interpolation" in found[0].observed


def test_a_brief_rough_blip_is_not_an_artifact():
    measured = {
        "rough_from_ms": 12,
        "rough_to_ms": 13,
        "smooth_offsets_in_window": 7,
        "peak_deviation_uv": 10.0,
        "peak_deviation_at_ms": 0,
    }
    assert signal.check_pulse_artifact(measured, PROTOCOL, "sub-1", "rec") == []


def test_run_all_reports_coverage_and_never_changes_files(synthetic_root):
    before = {p: p.read_bytes() for p in synthetic_root.rglob("*") if p.is_file()}
    table, extra = run_all(Dataset(synthetic_root))
    after = {p: p.read_bytes() for p in synthetic_root.rglob("*") if p.is_file()}
    assert before == after
    assert extra["coverage"]["tmseeg_runs"] == 3
    assert extra["coverage"]["runs_checked_signal"] == 2
    assert "pulse.duplicate" in set(table["rule"])
    assert "recording.missing" in set(table["rule"])
