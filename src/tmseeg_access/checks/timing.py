"""Checks on pulse markers: duplicates, missing or extra pulses, order and spacing.

These need only ``events.tsv``, so they run on every recording. They work on the published order of
rows, so an out-of-order marker is seen rather than sorted away.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from tmseeg_access.checks.issues import Issue


def _list(values: np.ndarray, limit: int = 3) -> str:
    shown = ", ".join(f"{v:.3f}" for v in values[:limit])
    return f"{shown}, and {len(values) - limit} more" if len(values) > limit else shown


def check_run(
    pulses: pd.DataFrame,
    protocol: dict,
    subject: str,
    recording_id: str,
    duration_s: float | None = None,
) -> list[Issue]:
    """Check one run's pulse markers. ``pulses`` needs ``onset``, and ``sample`` if published."""
    thresholds = protocol["thresholds"]
    published = protocol["published"]
    observed = protocol["observed"]
    onsets = pulses["onset"].to_numpy(dtype=float)
    gaps = np.diff(onsets)
    issues: list[Issue] = []

    def add(rule: str, severity: str, where: str, seen: str, expected: str, action: str) -> None:
        issues.append(Issue(rule, severity, where, seen, expected, action, subject, recording_id))

    backwards = gaps < 0
    if backwards.any():
        add(
            "pulse.out_of_order",
            "error",
            f"onsets {_list(onsets[1:][backwards])} s",
            f"{int(backwards.sum())} markers earlier than the row before",
            "onsets strictly increasing",
            "Check how events were exported before relying on row order.",
        )

    duplicate_gap = thresholds["duplicate_gap_s"]
    is_duplicate = (gaps >= 0) & (gaps < duplicate_gap)
    unique = len(onsets) - int(is_duplicate.sum())
    if is_duplicate.any():
        add(
            "pulse.duplicate",
            "error",
            f"onsets {_list(onsets[1:][is_duplicate])} s",
            f"{int(is_duplicate.sum())} of {len(onsets)} markers within "
            f"{duplicate_gap * 1000:g} ms of the previous one "
            f"(largest gap {gaps[is_duplicate].max() * 1000:.2f} ms)",
            "one marker per pulse",
            "Treat as one pulse if justified: on_duplicate='keep_first' records that choice.",
        )

        starts = np.flatnonzero(np.concatenate([[True], ~is_duplicate]))
        stops = np.concatenate([starts[1:] - 1, [len(onsets) - 1]])
        spans = onsets[stops] - onsets[starts]
        bursts = spans > thresholds["burst_span_s"]
        if bursts.any():
            add(
                "pulse.marker_burst",
                "error",
                f"starting at onsets {_list(onsets[starts][bursts])} s",
                f"{int(bursts.sum())} runs of closely spaced markers lasting up to "
                f"{spans[bursts].max():.2f} s, {len(onsets) - unique} extra markers in all",
                "a marker for each pulse, not a continuous stream",
                "A stuck trigger can hide real pulses: review these periods before keep_first.",
            )

    expected_pulses = published["pulses_per_run"]
    if unique != expected_pulses:
        shortfall = unique < expected_pulses
        add(
            "pulse.count",
            "warning",
            "whole run",
            f"{unique} markers left from {len(onsets)} after removing duplicates",
            f"{expected_pulses} pulses ({published['source']})",
            "Fewer epochs than planned: check whether the run was cut short."
            if shortfall
            else "Find which markers are extra before epoching: some may not be real pulses.",
        )

    usable = gaps[gaps >= duplicate_gap]
    low, high = observed["gap_min_s"], observed["gap_max_s"]
    short = usable < low
    if short.any():
        positions = onsets[1:][gaps >= duplicate_gap][short]
        add(
            "pulse.gap_short",
            "warning",
            f"onsets {_list(positions)} s",
            f"{int(short.sum())} gaps from {usable[short].min():.3f} to "
            f"{usable[short].max():.3f} s",
            f"{low} to {high} s (band observed in this release)",
            "Review these markers: epochs around them overlap or may not be real pulses.",
        )
    long = usable > high
    if long.any():
        positions = onsets[1:][gaps >= duplicate_gap][long]
        add(
            "pulse.gap_long",
            "info",
            f"onsets {_list(positions)} s",
            f"{int(long.sum())} gaps from {usable[long].min():.3f} to {usable[long].max():.3f} s",
            f"{low} to {high} s (band observed in this release)",
            "Probably a pause or missed pulse: check against the pulse count for this run.",
        )

    if duration_s is not None:
        outside = (onsets < 0) | (onsets > duration_s)
        if outside.any():
            add(
                "pulse.outside_recording",
                "error",
                f"onsets {_list(onsets[outside])} s",
                f"{int(outside.sum())} markers outside the recording",
                f"between 0 and {duration_s} s",
                "These cannot be epoched. Check the events file belongs to this recording.",
            )

    if "sample" in pulses:
        rate = published["shared_sampling_rate_hz"]
        difference = np.abs(pulses["sample"].to_numpy(dtype=float) - (onsets * rate + 1))
        wrong = difference > thresholds["sample_tolerance"]
        if wrong.any():
            add(
                "pulse.sample_mismatch",
                "warning",
                f"onsets {_list(onsets[wrong])} s",
                f"{int(wrong.sum())} rows where sample disagrees with onset "
                f"(up to {difference[wrong].max():.1f} samples)",
                "sample = onset * rate + 1",
                "Use onset, and find out which column is right for these rows.",
            )
    return issues


def check_marker_codes(codes: list[str], subject: str, recording_id: str) -> list[Issue]:
    """Report a run whose pulse markers carry more than one original trigger code.

    A second code can mean one pulse marked twice, or a marker that was never a pulse. Which one
    needs the signal, so this only reports it.
    """
    counts = Counter(codes)
    if len(counts) < 2:
        return []
    shown = ", ".join(f"{code}: {n}" for code, n in counts.most_common(4))
    others = f", and {len(counts) - 4} other codes" if len(counts) > 4 else ""
    return [
        Issue(
            "pulse.mixed_marker_codes",
            "warning",
            "events flagged is_tms_pulse",
            f"trigger codes in the header {shown}{others}",
            "one trigger code for every pulse",
            "Find which codes are pulses before epoching. Other codes dilute averages.",
            subject,
            recording_id,
        )
    ]


def check_published_spacing(all_gaps: np.ndarray, protocol: dict) -> list[Issue]:
    """Compare the spacing of every pulse in the dataset with the published protocol."""
    published = protocol["published"]
    gaps = all_gaps[all_gaps >= protocol["thresholds"]["duplicate_gap_s"]]
    if len(gaps) == 0:
        return []
    low, high = published["gap_min_s"], published["gap_max_s"]
    inside = (gaps >= low) & (gaps <= high)
    if inside.mean() >= 0.5:
        return []
    return [
        Issue(
            "protocol.spacing",
            "warning",
            "all TMS runs",
            f"median gap {np.median(gaps):.3f} s; {int(inside.sum())} of {len(gaps)} gaps "
            f"fall in the published range",
            f"{low} to {high} s ({published['source']})",
            "Confirm the true interval with the authors before using it in a report or model.",
        )
    ]
