"""Checks that need the signal itself: flat and clipped channels, and the pulse artifact.

The pulse check needs a full-sized run: about 120 pulses on 62 channels gives a stable median. On
much smaller data, noise alone can look like a change around the markers.
"""

from __future__ import annotations

import numpy as np

from tmseeg_access.checks.issues import Issue

TRIGGER = "TRIGGER"


def check_channels(
    data_uv: np.ndarray,
    names: list[str],
    protocol: dict,
    subject: str,
    recording_id: str,
) -> list[Issue]:
    """Find flat EEG channels, clipped channels, and a trigger channel that carries signal."""
    thresholds = protocol["thresholds"]
    floor = thresholds["flat_channel_uv"]
    issues = []
    spread = data_uv.std(axis=1)
    flat = spread < floor
    for index, name in enumerate(names):
        if name == TRIGGER:
            if not flat[index]:
                issues.append(
                    Issue(
                        "signal.trigger_not_flat",
                        "info",
                        f"channel {TRIGGER}",
                        f"standard deviation {spread[index]:.2f} uV",
                        "constant, as in most recordings that have this channel",
                        "Look at this channel: it may help explain the run's markers.",
                        subject,
                        recording_id,
                    )
                )
            continue
        if flat[index]:
            issues.append(
                Issue(
                    "signal.flat_channel",
                    "error",
                    f"channel {name}",
                    f"standard deviation {spread[index]:.4f} uV",
                    f"at least {floor} uV",
                    "Mark the channel bad and interpolate it, or check the cap connection.",
                    subject,
                    recording_id,
                )
            )
            continue
        longest = _longest_extreme_run(data_uv[index])
        if longest >= thresholds["saturated_run_samples"]:
            issues.append(
                Issue(
                    "signal.saturated_channel",
                    "error",
                    f"channel {name}",
                    f"{longest} consecutive samples at the channel's extreme value",
                    f"fewer than {thresholds['saturated_run_samples']}",
                    "The amplifier may have clipped here. Mark the channel or those segments bad.",
                    subject,
                    recording_id,
                )
            )
    return issues


def _longest_extreme_run(trace: np.ndarray) -> int:
    longest = 0
    for extreme in (trace.max(), trace.min()):
        at_extreme = np.concatenate([[False], trace == extreme, [False]])
        edges = np.flatnonzero(np.diff(at_extreme.astype(np.int8)))
        if len(edges):
            longest = max(longest, int((edges[1::2] - edges[::2]).max()))
    return longest


def _longest_span(offsets: np.ndarray) -> tuple[int, int] | None:
    """The longest stretch of consecutive offsets, as (first, last)."""
    if len(offsets) == 0:
        return None
    breaks = np.flatnonzero(np.diff(offsets) > 1)
    starts = np.concatenate([[0], breaks + 1])
    stops = np.concatenate([breaks, [len(offsets) - 1]])
    best = int(np.argmax(stops - starts))
    return int(offsets[starts[best]]), int(offsets[stops[best]])


def measure_pulse_artifact(data_uv: np.ndarray, samples: np.ndarray, protocol: dict) -> dict:
    """Measure how the signal departs from its pre-pulse character around the markers.

    Two measures, medians across pulses and channels. Roughness (absolute second difference)
    shows where the signal's character changes, including the smoothing interpolation leaves.
    Deviation (distance from the mean of the pre-pulse window) gives the size in microvolts.
    """
    thresholds = protocol["thresholds"]
    first, last = thresholds["window_offsets_ms"]
    low, high = thresholds["baseline_offsets_ms"]
    window = np.arange(first - 1, last + 2)
    usable = samples[(samples + window[0] >= 0) & (samples + window[-1] < data_uv.shape[1])]
    stack = np.stack([data_uv[:, s + window[0] : s + window[-1] + 1] for s in usable])

    offsets = window[1:-1]
    profile = np.median(np.abs(np.diff(stack, n=2, axis=2)), axis=(0, 1))
    in_baseline = (offsets >= low) & (offsets <= high)
    baseline = float(np.median(profile[in_baseline]))
    ratio = profile / baseline

    before = stack[:, :, (window >= low) & (window <= high)].mean(axis=2, keepdims=True)
    deviation = np.median(np.abs(stack - before), axis=(0, 1))[1:-1]

    start, stop = protocol["published"]["artifact_window_ms"]
    smooth = offsets[ratio < thresholds["smoother_below"]]
    span = _longest_span(offsets[ratio > thresholds["rougher_above"]])
    return {
        "pulses_used": len(usable),
        "baseline_roughness_uv": round(baseline, 2),
        "peak_roughness_ratio": round(float(ratio.max()), 1),
        "peak_deviation_uv": round(float(deviation.max()), 1),
        "peak_deviation_at_ms": int(offsets[np.argmax(deviation)]),
        "rough_from_ms": span[0] if span else None,
        "rough_to_ms": span[1] if span else None,
        "smooth_offsets_in_window": int(((smooth >= start) & (smooth <= stop)).sum()),
    }


def check_pulse_artifact(
    measured: dict,
    protocol: dict,
    subject: str,
    recording_id: str,
    header_says_interpolated: bool = False,
) -> list[Issue]:
    """Report a pulse artifact left in the data, or markers with no sign of a pulse at all."""
    thresholds = protocol["thresholds"]
    start, stop = protocol["published"]["artifact_window_ms"]
    span = None
    if measured["rough_from_ms"] is not None:
        span = measured["rough_to_ms"] - measured["rough_from_ms"] + 1
    if span is not None and span >= thresholds["min_rough_span_ms"]:
        peak = measured["peak_deviation_uv"]
        return [
            Issue(
                "signal.residual_pulse_artifact",
                "error" if peak >= thresholds["artifact_error_uv"] else "warning",
                f"{measured['rough_from_ms']} to {measured['rough_to_ms']} ms around pulses",
                f"median deviation peaks at {peak} uV, {measured['peak_deviation_at_ms']} ms "
                f"after the marker; {measured['smooth_offsets_in_window']} of "
                f"{stop - start + 1} window samples look interpolated"
                + ("; the header records interpolation" if header_says_interpolated else ""),
                f"interpolated from {start} to {stop} ms, with no large deviation",
                "Do not interpret early responses in this run without removing the artifact.",
                subject,
                recording_id,
            )
        ]
    if measured["smooth_offsets_in_window"] == 0:
        return [
            Issue(
                "signal.no_pulse_signature",
                "error",
                "around every marker",
                "the signal does not change around the markers",
                f"a change at {start} to {stop} ms, as the preprint's interpolation would leave",
                "Check the markers belong to this recording before epoching.",
                subject,
                recording_id,
            )
        ]
    return []
