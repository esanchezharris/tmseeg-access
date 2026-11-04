"""Findings from hand-checking, saved so the docs can cite them. Writes results/hand_checks.json.

Covers claims that no check or report records directly. Identifying text is counted, never stored.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import mne
import numpy as np
import pandas as pd
from pymatreader import read_mat

from tmseeg_access.catalog import default_path, query
from tmseeg_access.checks import signal
from tmseeg_access.checks.issues import load_protocol
from tmseeg_access.checks.run import _read_header
from tmseeg_access.dataset import Dataset

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results" / "hand_checks.json"


def marker_pairs(ds: Dataset) -> dict:
    found = {}
    for subject, site in [("sub-047", "prefrontal"), ("sub-057", "parietal")]:
        gaps = ds.pulses(subject, site)["gap_from_previous_s"].dropna().to_numpy()
        paired = gaps[(gaps > 0.09) & (gaps < 0.11)]
        found[f"{subject} {site}"] = {
            "pairs": len(paired),
            "gap_min_s": round(float(paired.min()), 4),
            "gap_max_s": round(float(paired.max()), 4),
        }
    return found


def pair_interpolation(ds: Dataset) -> dict:
    """Is the signal smoothed at both markers of each pair? Compared with 5 to 10 ms before."""
    pulses = ds.pulses("sub-057", "parietal")
    samples = pulses.loc[~pulses["is_duplicate"], "onset_sample"].to_numpy()
    close = np.flatnonzero(np.diff(samples) < 200)
    data = ds.load_raw("sub-057", acquisition="parietal").get_data() * 1e6

    def ratio(positions: np.ndarray) -> float:
        rough = lambda start: np.median(
            [np.abs(np.diff(data[:, p + start : p + start + 4], n=2, axis=1)) for p in positions]
        )
        return round(float(rough(0) / rough(-10)), 2)

    return {
        "pairs": len(close),
        "roughness_ratio_first_marker": ratio(samples[close]),
        "roughness_ratio_second_marker": ratio(samples[close + 1]),
        "below_0_8_means_smoothed": True,
    }


def events_against_headers(ds: Dataset) -> dict:
    """Compare event times, not just counts, in every TMS run."""
    worst = 0.0
    runs = disagree = 0
    for row in ds.recordings(task="tmseeg").itertuples(index=False):
        stem = f"{row.subject}_task-tmseeg_acq-{row.acquisition}"
        path = ds.root / row.subject / "eeg" / f"{stem}_eeg.set"
        header = read_mat(str(path), variable_names=["event", "srate"])
        latency = np.atleast_1d(np.asarray(header["event"]["latency"], dtype=float))
        onsets = ds.events(row.subject, acquisition=row.acquisition)["onset"].to_numpy()
        difference = np.abs(onsets - (latency - 1) / float(header["srate"]))
        worst = max(worst, float(difference.max()))
        disagree += int((difference > 1e-6).any())
        runs += 1
    return {"runs": runs, "runs_disagreeing": disagree, "largest_difference_s": worst}


def identifying_text(ds: Dataset) -> dict:
    counts = dict.fromkeys(
        ["history_has_path", "chaninfo_has_user_folder", "comments_has_study_code", "runs"], 0
    )
    for path in ds.root.glob("sub-*/eeg/*task-tmseeg*_eeg.set"):
        header = read_mat(str(path), variable_names=["history", "chaninfo", "comments"])
        chaninfo = header.get("chaninfo")
        counts["runs"] += 1
        counts["history_has_path"] += "/" in str(header.get("history", ""))
        counts["chaninfo_has_user_folder"] += isinstance(chaninfo, dict) and "/Users/" in str(
            chaninfo.get("filename", "")
        )
        counts["comments_has_study_code"] += "GWM" in str(header.get("comments", ""))
    return counts


def mixed_case_everywhere(ds: Dataset) -> dict:
    found = {}
    for path in ds.root.glob("sub-*/eeg/*_channels.tsv"):
        task = re.search(r"task-([a-z]+)", path.name)[1]
        names = pd.read_csv(path, sep="\t")["name"]
        counts = found.setdefault(task, {"runs": 0, "mixed_case": 0})
        counts["runs"] += 1
        counts["mixed_case"] += int((names != names.str.upper()).any())
    return found


def trigger_channels(ds: Dataset, artifact: pd.DataFrame) -> dict:
    flat = with_channel = 0
    for row in artifact.itertuples(index=False):
        raw = ds.load_raw(row.subject, acquisition=row.acquisition)
        if "TRIGGER" in raw.ch_names:
            with_channel += 1
            flat += float(raw.get_data(picks=["TRIGGER"]).std()) * 1e6 < 0.1
    return {"signal_checked_runs_with_trigger": with_channel, "flat": flat}


def average_reference_effect(ds: Dataset, artifact: pd.DataFrame) -> list[dict]:
    """How much of each large artifact survives average referencing?"""
    rows = []
    large = artifact[
        (artifact["peak_channel_uv"] >= 1000) | (artifact["peak_deviation_uv"] >= 1000)
    ]
    for row in large.itertuples(index=False):
        epochs = ds.epochs_around_pulses(
            row.subject,
            row.acquisition,
            tmin=-0.02,
            tmax=0.04,
            baseline=(-0.018, -0.008),
            on_duplicate="keep_first",
            exclude_channels=("TRIGGER",),
        )
        before = float(np.abs(epochs.average().data).max() * 1e6)
        mne.set_log_level("ERROR")
        after = float(np.abs(epochs.copy().set_eeg_reference("average").average().data).max() * 1e6)
        rows.append(
            {
                "recording": f"{row.subject} {row.acquisition}",
                "peak_channel_recorded_uv": round(before, 1),
                "peak_channel_average_reference_uv": round(after, 1),
                "shrank_by": round(before / after, 1),
            }
        )
    return sorted(rows, key=lambda r: r["shrank_by"], reverse=True)


def spacing_variants(catalog: Path) -> list[dict]:
    """Count gaps in the published range under each reasonable way of handling duplicates."""
    pulses = query(
        catalog,
        "SELECT recording_id, onset_s, gap_from_previous_s AS gap, is_duplicate FROM pulses "
        "ORDER BY recording_id, pulse_index",
    )
    kept = pulses.loc[~pulses["is_duplicate"]]
    between_kept = kept.groupby("recording_id")["onset_s"].diff().dropna()
    with_duplicates = pulses.loc[pulses["is_duplicate"], "recording_id"].unique()
    untouched = kept.loc[~kept["recording_id"].isin(with_duplicates)]
    variants = {
        "all gaps of 2 ms or more (rule protocol.spacing)": pulses["gap"]
        .dropna()
        .loc[lambda gaps: gaps >= 0.002],
        "between markers kept by keep_first": between_kept,
        "only runs with no suspected duplicates": untouched.groupby("recording_id")["onset_s"]
        .diff()
        .dropna(),
    }
    return [
        {
            "method": name,
            "gaps": len(gaps),
            "median_s": round(float(gaps.median()), 4),
            "in_published_range": int(gaps.between(4, 6).sum()),
        }
        for name, gaps in variants.items()
    ]


def sub_134_by_code(ds: Dataset) -> dict:
    """Measure the artifact separately on code 128 and on the other codes in this mixed run."""
    run = "sub-134_task-tmseeg_acq-parietal"
    header = _read_header(ds.root / "sub-134" / "eeg" / f"{run}_eeg.set")
    is_128 = np.array(header["marker_codes"]) == "128"
    flagged = ds.pulses("sub-134", "parietal")
    distinct = ~flagged["is_duplicate"].to_numpy()
    samples = flagged["onset_sample"].to_numpy()
    raw = ds.load_raw("sub-134", acquisition="parietal")
    kept = [i for i, name in enumerate(raw.ch_names) if name != signal.TRIGGER]
    data = raw.get_data(picks=kept) * 1e6
    names = [raw.ch_names[i] for i in kept]
    result = {}
    for label, chosen in (
        ("code_128", is_128),
        ("other_codes", ~is_128),
        ("all", is_128 | ~is_128),
    ):
        use = samples[chosen & distinct]
        measured = signal.measure_pulse_artifact(data, use, load_protocol(), names)
        result[label] = {
            "markers": len(use),
            "peak_channel_uv": measured["peak_channel_uv"],
            "peak_channel": measured["peak_channel"],
            "smooth_offsets_in_window": measured["smooth_offsets_in_window"],
        }
    return result


def main() -> None:
    ds = Dataset()
    catalog = default_path(ds.root)
    artifact = pd.read_csv(ROOT / "results" / "pulse_artifact.csv")
    issues = pd.read_csv(ROOT / "results" / "issues.csv")
    flagged = set(issues.loc[issues["rule"] == "signal.residual_pulse_artifact", "recording_id"])
    unflagged = artifact[~artifact["recording_id"].isin(flagged)]
    duplicates = query(
        catalog,
        "SELECT recording_id, sum(is_duplicate::INT) AS n FROM pulses GROUP BY 1 HAVING n > 0",
    )
    biggest = duplicates.sort_values("n", ascending=False).iloc[0]
    result = {
        "marker_pairs_0_1_s": marker_pairs(ds),
        "pair_interpolation_sub_057": pair_interpolation(ds),
        "duplicate_markers": {
            "total": int(duplicates["n"].sum()),
            "runs": len(duplicates),
            "largest_run": biggest["recording_id"],
            "in_largest_run": int(biggest["n"]),
            "in_all_other_runs": int(duplicates["n"].sum() - biggest["n"]),
        },
        "identical_files": {
            kind: int(
                query(
                    catalog,
                    f"SELECT count(*) AS n FROM (SELECT hash_value FROM files WHERE path LIKE "
                    f"'%{kind}' GROUP BY 1 HAVING count(*) > 1)",
                )["n"][0]
            )
            for kind in [".fdt", "_events.tsv"]
        },
        "signal_files_gb": query(
            catalog,
            "SELECT local, round(sum(size_bytes) / 1e9, 2) AS gb FROM files "
            "WHERE path LIKE '%.fdt' GROUP BY 1 ORDER BY 1",
        ).to_dict(orient="records"),
        "events_against_headers": events_against_headers(ds),
        "identifying_text_in_headers": identifying_text(ds),
        "mixed_case_channels_by_task": mixed_case_everywhere(ds),
        "trigger_channel": trigger_channels(ds, artifact),
        "runs_with_no_artifact_flag": {
            "runs": len(unflagged),
            "peak_channel_uv_median": round(float(unflagged["peak_channel_uv"].median()), 1),
            "peak_channel_uv_max": float(unflagged["peak_channel_uv"].max()),
        },
        "residual_artifact_by_site": pd.crosstab(
            issues.loc[issues["rule"] == "signal.residual_pulse_artifact", "recording_id"]
            .str.extract(r"acq-(\w+)")[0]
            .rename("site"),
            issues.loc[issues["rule"] == "signal.residual_pulse_artifact", "severity"],
        ).to_dict(orient="index"),
        "large_runs_with_no_smooth_offset_in_window": int(
            (
                artifact.loc[
                    (artifact["peak_channel_uv"] >= 1000) | (artifact["peak_deviation_uv"] >= 1000),
                    "smooth_offsets_in_window",
                ]
                == 0
            ).sum()
        ),
        "average_reference_effect": average_reference_effect(ds, artifact),
        "sub_134_parietal_by_trigger_code": sub_134_by_code(ds),
        "spacing_variants": spacing_variants(catalog),
    }
    OUTPUT.write_text(json.dumps(result, indent=2, default=int) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, default=int))


if __name__ == "__main__":
    main()
