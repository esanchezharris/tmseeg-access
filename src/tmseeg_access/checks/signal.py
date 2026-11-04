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


def check_reference_channel(
    data_uv: np.ndarray,
    names: list[str],
    reference: str | None,
    protocol: dict,
    subject: str,
    recording_id: str,
) -> list[Issue]:
    """Report a declared reference channel that carries signal.

    Data recorded against a channel leaves that channel flat, so signal on it means the data is
    not in the reference the sidecar states.
    """
    upper = [name.upper() for name in names]
    if not reference or reference.upper() not in upper:
        return []
    index = upper.index(reference.upper())
    spread = float(data_uv[index].std())
    if spread < protocol["thresholds"]["flat_channel_uv"]:
        return []
    return [
        Issue(
            "signal.reference_channel_active",
            "warning",
            f"channel {names[index]}",
            f"sidecar reference is {reference}, but that channel has "
            f"standard deviation {spread:.1f} uV",
            "a flat reference channel, or a sidecar naming the true reference",
            "Do not rely on the stated reference. Re-reference explicitly before analysis.",
            subject,
            recording_id,
        )
    ]


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


def measure_pulse_artifact(
    data_uv: np.ndarray, samples: np.ndarray, protocol: dict, names: list[str] | None = None
) -> dict | None:
    """Measure how the signal departs from its pre-pulse character around the markers.

    Roughness (absolute second difference) shows where the signal's character changes, including
    the smoothing interpolation leaves. Deviation (distance from the mean of the pre-pulse window)
    gives the size on each channel, in the recorded reference. Field power (the spread across
    channels of the averaged response) leaves out whatever all channels share, so a large deviation
    with small field power is mostly common to every channel. Roughness and deviation are medians
    across pulses and channels, so an artifact on a few channels can be invisible to them. The
    peak channel value catches that: the largest deviation of any one channel's averaged response.

    Leave non-EEG channels out of ``data_uv``. A flat channel beside channels that move together
    creates false spread in field power.

    Window offsets are in samples, which are milliseconds at this dataset's 1 kHz. Returns None if
    no pulse has a complete window.
    """
    thresholds = protocol["thresholds"]
    first, last = thresholds["window_offsets_ms"]
    low, high = thresholds["baseline_offsets_ms"]
    window = np.arange(first - 1, last + 2)
    usable = samples[(samples + window[0] >= 0) & (samples + window[-1] < data_uv.shape[1])]
    if len(usable) == 0:
        return None
    stack = np.stack([data_uv[:, s + window[0] : s + window[-1] + 1] for s in usable])

    offsets = window[1:-1]
    profile = np.median(np.abs(np.diff(stack, n=2, axis=2)), axis=(0, 1))
    in_baseline = (offsets >= low) & (offsets <= high)
    baseline = float(np.median(profile[in_baseline]))
    ratio = profile / baseline

    before = stack[:, :, (window >= low) & (window <= high)].mean(axis=2, keepdims=True)
    deviation = np.median(np.abs(stack - before), axis=(0, 1))[1:-1]
    averaged = (stack - before).mean(axis=0)[:, 1:-1]
    field_power = averaged.std(axis=0)
    channel_peaks = np.abs(averaged).max(axis=1)
    worst = int(np.argmax(channel_peaks))

    start, stop = protocol["published"]["artifact_window_ms"]
    smooth = offsets[ratio < thresholds["smoother_below"]]
    span = _longest_span(offsets[ratio > thresholds["rougher_above"]])
    return {
        "pulses_used": len(usable),
        "baseline_roughness_uv": round(baseline, 2),
        "peak_roughness_ratio": round(float(ratio.max()), 1),
        "peak_deviation_uv": round(float(deviation.max()), 1),
        "peak_deviation_at_ms": int(offsets[np.argmax(deviation)]),
        "peak_field_power_uv": round(float(field_power.max()), 1),
        "peak_channel_uv": round(float(channel_peaks[worst]), 1),
        "peak_channel": names[worst] if names else str(worst),
        "rough_from_ms": span[0] if span else None,
        "rough_to_ms": span[1] if span else None,
        "smooth_offsets_in_window": int(((smooth >= start) & (smooth <= stop)).sum()),
    }


def check_pulse_artifact(
    measured: dict | None,
    protocol: dict,
    subject: str,
    recording_id: str,
    header_says_interpolated: bool = False,
) -> list[Issue]:
    """Report a pulse artifact left in the data, or markers with no sign of a pulse at all."""
    if measured is None:
        return [
            Issue(
                "signal.no_usable_pulses",
                "warning",
                "whole run",
                "no marker has a complete window of signal around it",
                "markers inside the recording",
                "The artifact check could not run on this recording: inspect it by hand.",
                subject,
                recording_id,
            )
        ]
    thresholds = protocol["thresholds"]
    start, stop = protocol["published"]["artifact_window_ms"]
    span = None
    if measured["rough_from_ms"] is not None:
        span = measured["rough_to_ms"] - measured["rough_from_ms"] + 1
    limit = thresholds["artifact_error_uv"]
    peak = measured["peak_deviation_uv"]
    channel_peak = measured.get("peak_channel_uv", 0.0)
    wide = span is not None and span >= thresholds["min_rough_span_ms"]
    if wide or channel_peak >= limit:
        return [
            Issue(
                "signal.residual_pulse_artifact",
                "error" if max(peak, channel_peak) >= limit else "warning",
                f"{measured['rough_from_ms']} to {measured['rough_to_ms']} ms around pulses"
                if wide
                else f"channel {measured.get('peak_channel')}",
                f"median deviation peaks at {peak} uV, {measured['peak_deviation_at_ms']} ms "
                f"after the marker; field power peaks at "
                f"{measured.get('peak_field_power_uv', 'n/a')} uV; largest averaged channel "
                f"{measured.get('peak_channel', 'n/a')} at {channel_peak} uV; "
                f"{measured['smooth_offsets_in_window']} of "
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
