"""Evidence for how a TMS pulse is identified in ds008037. Writes results/pulse_identification.json.

Three questions, answered from the data rather than assumed:
1. What is the time base of ``onset``, and of the ``sample`` column? (compare with the .set events)
2. Do the markers line up with the signal? If they do, the signal should change character at fixed
   offsets from each marker, in any direction, and the same analysis with the markers moved 1 s
   later should show nothing. That placebo is what makes this evidence about the markers.
3. How far apart are markers across every TMS run?
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from pymatreader import read_mat

from tmseeg_access.dataset import PULSE_COLUMN, Dataset

OUTPUT = Path(__file__).resolve().parents[1] / "results" / "pulse_identification.json"
SUBJECT = "sub-001"
SITES = ["control", "parietal", "prefrontal", "premotor"]
WINDOW = np.arange(-20, 31)
PLACEBO_SHIFT_SAMPLES = 1000  # markers are at least 2.5 s apart in this subject
BASELINE_OFFSETS = (-18, -8)
SMOOTHER_BELOW = 0.8
ROUGHER_ABOVE = 1.25
GAP_BINS = [
    ("0 (identical)", 0.0, 1e-12),
    ("under 1 ms", 1e-12, 0.001),
    ("1 ms to 2 ms", 0.001, 0.002),
    ("2 ms to 10 ms", 0.002, 0.01),
    ("10 ms to 100 ms", 0.01, 0.1),
    ("100 ms to 1 s", 0.1, 1.0),
    ("1 s to 2.5 s", 1.0, 2.5),
    ("2.5 s to 3.6 s", 2.5, 3.6),
    ("3.6 s to 4 s", 3.6, 4.0),
    ("4 s to 6 s", 4.0, 6.0),
    ("6 s and over", 6.0, np.inf),
]


def time_base(ds: Dataset) -> dict:
    results = {}
    for site in SITES:
        stem = f"{SUBJECT}_task-tmseeg_acq-{site}"
        header = read_mat(str(ds.root / SUBJECT / "eeg" / f"{stem}_eeg.set"))
        latency = np.asarray(header["event"]["latency"], dtype=float)
        rate = float(header["srate"])
        events = ds.events(SUBJECT, acquisition=site)
        results[site] = {
            "events_in_set": len(latency),
            "events_in_tsv": len(events),
            "max_abs_diff_onset_vs_latency_minus_1_over_rate_s": float(
                np.abs(events["onset"] - (latency - 1) / rate).max()
            ),
            "max_abs_diff_onset_vs_latency_over_rate_s": float(
                np.abs(events["onset"] - latency / rate).max()
            ),
        }
    return results


def roughness(data: np.ndarray, samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Median absolute second difference at each offset, across pulses and channels."""
    valid = samples[(samples + WINDOW[0] >= 0) & (samples + WINDOW[-1] < data.shape[1])]
    stack = np.stack([data[:, s + WINDOW[0] : s + WINDOW[-1] + 1] for s in valid])
    return WINDOW[1:-1], np.median(np.abs(np.diff(stack, n=2, axis=2)), axis=(0, 1))


def departures(offsets: np.ndarray, profile: np.ndarray) -> dict:
    """Offsets where the signal is unusually smooth or rough relative to before the pulse."""
    low, high = BASELINE_OFFSETS
    baseline = float(np.median(profile[(offsets >= low) & (offsets <= high)]))
    ratio = profile / baseline
    return {
        "baseline_uv": round(baseline, 2),
        "smoother_offsets_ms": [int(o) for o in offsets[ratio < SMOOTHER_BELOW]],
        "rougher_offsets_ms": [int(o) for o in offsets[ratio > ROUGHER_ABOVE]],
        "peak_ratio_to_baseline": round(float(ratio.max()), 1),
        "lowest_ratio_to_baseline": round(float(ratio.min()), 2),
    }


def alignment(ds: Dataset) -> dict:
    results = {}
    for site in SITES:
        data = ds.load_raw(SUBJECT, acquisition=site, preload=True).get_data() * 1e6
        samples = ds.pulses(SUBJECT, site)["onset_sample"].to_numpy()
        offsets, at_markers = roughness(data, samples)
        _, placebo = roughness(data, samples + PLACEBO_SHIFT_SAMPLES)
        results[site] = {
            "pulses": len(samples),
            "at_markers": departures(offsets, at_markers),
            "placebo_markers_shifted_1s": departures(offsets, placebo),
            "median_roughness_uv_by_offset_ms": {
                int(o): round(float(v), 2) for o, v in zip(offsets, at_markers, strict=True)
            },
        }
    return results


def gap_survey(ds: Dataset) -> dict:
    gaps = []
    runs = counts = 0
    for path in sorted(ds.root.glob("sub-*/eeg/*task-tmseeg*_events.tsv")):
        events = pd.read_csv(path, sep="\t", low_memory=False)
        onsets = events.loc[events[PULSE_COLUMN] == 1, "onset"].to_numpy()
        gaps.append(np.diff(onsets))
        runs += 1
        counts += len(onsets)
    joined = np.concatenate(gaps)
    table = {label: int(((joined >= low) & (joined < high)).sum()) for label, low, high in GAP_BINS}
    return {
        "tmseeg_runs": runs,
        "markers": counts,
        "gaps": len(joined),
        "negative_gaps": int((joined < 0).sum()),
        "gap_counts": table,
        "bins_sum_to_gaps": sum(table.values()) == len(joined) - int((joined < 0).sum()),
    }


def main() -> None:
    ds = Dataset()
    result = {"time_base": time_base(ds), "alignment": alignment(ds), "gaps": gap_survey(ds)}
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for site, values in result["alignment"].items():
        print(site, "markers:", values["at_markers"])
        print(site, "placebo:", values["placebo_markers_shifted_1s"])


if __name__ == "__main__":
    main()
