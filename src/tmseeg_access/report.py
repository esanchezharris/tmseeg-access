"""Write an HTML report and CSVs from saved results. Reads the catalog and check outputs only.

The report never touches the signal or recomputes a check, so it can be rebuilt in seconds and every
figure in it can be traced to ``issues.csv``, ``pulse_artifact.csv`` or the catalog.
"""

from __future__ import annotations

import base64
import html
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from tmseeg_access.catalog import query

SERIES = "#2a78d6"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e4e3df"
BAND = "#eeede9"
SURFACE = "#fcfcfb"
EXPECTED_PULSES = 120
COUNT_BINS = [
    ("under 120", 0, 119),
    ("120", 120, 120),
    ("121 to 125", 121, 125),
    ("126 to 239", 126, 239),
    ("240 to 242", 240, 242),
    ("over 242", 243, 10**9),
]
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
SITE_ORDER = ["control", "parietal", "premotor", "prefrontal"]
RULE_MEANINGS = {
    "channels.inconsistent": "Recordings declare different channel counts",
    "channels.name_spelling": "The same electrode is spelled two ways",
    "channels.names_differ": "A recording has different electrodes from the rest",
    "channels.trigger_typed_as_eeg": "A flat trigger channel is listed as EEG",
    "dataset.not_raw": "Labelled raw, but described as partly preprocessed",
    "header.no_artifact_record": "No record of artifact removal in the header",
    "header.site_mismatch": "Site label disagrees with the original filename",
    "metadata.no_stimulation_dose": "No stimulation intensity for any subject",
    "pulse.mixed_marker_codes": "Pulse markers carry more than one trigger code",
    "signal.frozen_signal": "Most channels hold their value at the same moment",
    "sidecar.reference_differs_from_published": "Sidecars and preprint name different references",
    "participant.missing_value": "A participant field has gaps",
    "participant.no_recordings": "A listed participant has no EEG recordings",
    "participant.unlisted": "Recordings exist for an unlisted participant",
    "protocol.spacing": "Pulse spacing differs from the published protocol",
    "pulse.count": "Markers left after duplicates differ from 120",
    "pulse.duplicate": "Pulse markers under 2 ms apart",
    "pulse.gap_long": "Gaps longer than the band seen in this release",
    "pulse.gap_short": "Gaps shorter than the band seen in this release",
    "pulse.marker_burst": "A continuous stream of markers",
    "pulse.out_of_order": "Markers out of time order",
    "pulse.outside_recording": "Markers outside the recording",
    "pulse.sample_mismatch": "The sample column disagrees with onset",
    "rate.inconsistent": "Recordings have different sampling rates",
    "recording.missing": "An expected TMS run is absent",
    "sidecar.channel_count": "Sidecar and header disagree on channels",
    "sidecar.channel_names": "channels.tsv and header disagree on names",
    "sidecar.dangling_reference": "Sidecars refer to files that do not exist",
    "sidecar.duration": "Sidecar and header disagree on duration",
    "sidecar.event_count": "events.tsv and header disagree on event count",
    "sidecar.sampling_rate": "Sidecar and header disagree on sampling rate",
    "signal.flat_channel": "A flat EEG channel",
    "signal.no_pulse_signature": "No change in the signal around markers",
    "signal.no_usable_pulses": "No marker has a complete window of signal",
    "signal.residual_pulse_artifact": "Disturbance around the pulse, or a very large channel",
    "signal.reference_channel_active": "The stated reference channel carries signal",
    "signal.saturated_channel": "A channel stuck at its extreme value",
    "signal.trigger_not_flat": "The trigger channel carries signal",
}
_STYLE = """
:root { color-scheme: light; }
body { margin: 0; background: #f6f5f2; color: #0b0b0b;
  font: 16px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 30px; line-height: 1.2; margin: 0 0 6px; }
h2 { font-size: 21px; margin: 44px 0 6px; }
p { margin: 8px 0; }
.lede { color: #52514e; margin-bottom: 22px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
.tile { background: #fcfcfb; border: 1px solid #e4e3df; border-radius: 8px; padding: 14px 16px; }
.tile b { display: block; font-size: 28px; line-height: 1.2; font-variant-numeric: tabular-nums; }
.tile span { color: #52514e; font-size: 14px; }
figure { margin: 14px 0; background: #fcfcfb; border: 1px solid #e4e3df; border-radius: 8px;
  padding: 10px; }
figure img { display: block; width: 100%; height: auto; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; background: #fcfcfb; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #e4e3df; vertical-align: top; }
th { color: #52514e; font-weight: 600; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
code { font-size: 13px; }
.note { background: #fcfcfb; border-left: 3px solid #52514e; padding: 10px 14px; margin: 14px 0; }
"""


@dataclass
class Inputs:
    recordings: pd.DataFrame
    pulses: pd.DataFrame
    participants: pd.DataFrame
    issues: pd.DataFrame
    artifact: pd.DataFrame
    summary: dict


def load_inputs(catalog: Path, results: Path) -> Inputs:
    """Read everything the report needs from saved files."""
    return Inputs(
        recordings=query(catalog, "SELECT * FROM recordings"),
        pulses=query(
            catalog,
            "SELECT recording_id, acquisition, gap_from_previous_s, is_duplicate FROM pulses",
        ),
        participants=query(catalog, "SELECT * FROM participants"),
        issues=pd.read_csv(results / "issues.csv"),
        artifact=pd.read_csv(results / "pulse_artifact.csv"),
        summary=json.loads((results / "check_summary.json").read_text(encoding="utf-8")),
    )


def marker_count_table(recordings: pd.DataFrame) -> pd.DataFrame:
    """How many TMS runs have each size of marker count."""
    counts = recordings.loc[recordings["task"] == "tmseeg", "pulse_count"]
    rows = [
        {"markers_in_run": label, "runs": int(((counts >= low) & (counts <= high)).sum())}
        for label, low, high in COUNT_BINS
    ]
    return pd.DataFrame(rows)


def usable_gaps(pulses: pd.DataFrame) -> np.ndarray:
    """Gaps between markers, with suspected duplicates left out."""
    kept = pulses.loc[~pulses["is_duplicate"].astype(bool), "gap_from_previous_s"]
    return kept.dropna().to_numpy(dtype=float)


def gap_histogram(gaps: np.ndarray, width: float = 0.1, top: float = 7.0) -> pd.DataFrame:
    """Gaps in fixed bins, up to ``top`` seconds."""
    edges = np.arange(0, top + width / 2, width)
    counts, _ = np.histogram(gaps, bins=edges)
    return pd.DataFrame(
        {"gap_from_s": edges[:-1].round(2), "gap_to_s": edges[1:].round(2), "gaps": counts}
    )


def rule_table(issues: pd.DataFrame) -> pd.DataFrame:
    """Issue counts by rule, worst severity first."""
    table = issues.groupby(["rule", "severity"]).size().reset_index(name="issues")
    table["meaning"] = table["rule"].map(RULE_MEANINGS).fillna("")
    table["order"] = table["severity"].map(SEVERITY_ORDER)
    table = table.sort_values(["order", "issues"], ascending=[True, False])
    return table.drop(columns="order").reset_index(drop=True)


def _axes(figsize: tuple[float, float]):
    figure, axes = plt.subplots(figsize=figsize, dpi=160, facecolor=SURFACE)
    axes.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color(GRID)
    axes.tick_params(colors=INK_SECONDARY, length=0, labelsize=9)
    axes.set_axisbelow(True)
    return figure, axes


def _finish(figure, path: Path) -> bytes:
    figure.tight_layout()
    figure.savefig(path, facecolor=SURFACE)
    plt.close(figure)
    return path.read_bytes()


def chart_marker_counts(table: pd.DataFrame, path: Path) -> bytes:
    figure, axes = _axes((7.4, 2.9))
    positions = np.arange(len(table))
    axes.bar(positions, table["runs"], width=0.42, color=SERIES)
    axes.set_xticks(positions, table["markers_in_run"])
    axes.set_yticks([])
    axes.spines["bottom"].set_visible(True)
    top = table["runs"].max()
    for x, value in zip(positions, table["runs"], strict=True):
        axes.text(x, value + top * 0.02, str(value), ha="center", color=INK, fontsize=10)
    axes.set_ylim(0, top * 1.13)
    axes.set_xlabel("Markers in the run (the protocol has 120)", color=INK_SECONDARY, fontsize=9)
    axes.set_title("TMS runs by marker count", loc="left", color=INK, fontsize=11)
    return _finish(figure, path)


def chart_gaps(table: pd.DataFrame, path: Path) -> bytes:
    figure, axes = _axes((7.4, 3.0))
    axes.axvspan(4, 6, color=BAND, linewidth=0)
    axes.bar(
        table["gap_from_s"], table["gaps"], width=0.09, align="edge", color=SERIES, linewidth=0
    )
    top = table["gaps"].max()
    axes.text(
        5,
        top * 0.93,
        "Published range\n4 to 6 s",
        ha="center",
        va="top",
        color=INK_SECONDARY,
        fontsize=9,
    )
    axes.set_xlim(0, 7)
    axes.grid(axis="y", color=GRID, linewidth=0.7)
    axes.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    axes.set_xlabel("Seconds between markers, duplicates left out", color=INK_SECONDARY, fontsize=9)
    axes.set_title("Pulse spacing across all TMS runs", loc="left", color=INK, fontsize=11)
    return _finish(figure, path)


def chart_rules(table: pd.DataFrame, path: Path) -> bytes:
    figure, axes = _axes((7.4, 0.5 + 0.28 * len(table)))
    labels = [f"{r.rule} ({r.severity})" for r in table.itertuples()]
    positions = np.arange(len(table))
    axes.barh(positions, table["issues"], height=0.5, color=SERIES)
    axes.set_yticks(positions, labels, fontsize=8.5)
    axes.invert_yaxis()
    axes.set_xticks([])
    axes.spines["bottom"].set_visible(False)
    top = table["issues"].max()
    for y, value in zip(positions, table["issues"], strict=True):
        axes.text(value + top * 0.012, y, str(value), va="center", color=INK, fontsize=9)
    axes.set_xlim(0, top * 1.08)
    axes.set_title("Issues by rule, worst severity first", loc="left", color=INK, fontsize=11)
    return _finish(figure, path)


def chart_artifact(artifact: pd.DataFrame, path: Path) -> bytes:
    figure, axes = _axes((7.4, 2.7))
    sites = [s for s in SITE_ORDER if s in set(artifact["acquisition"])]
    rng = np.random.default_rng(0)  # a fixed sideways jitter, so overlapping dots stay visible
    for row, site in enumerate(sites):
        values = artifact.loc[artifact["acquisition"] == site, "peak_channel_uv"]
        spread = rng.uniform(-0.17, 0.17, len(values))
        axes.scatter(
            values, row + spread, s=46, color=SERIES, edgecolors=SURFACE, linewidths=1.2, zorder=3
        )
    axes.set_xscale("log")
    axes.axvline(1000, color=INK_SECONDARY, linewidth=0.8, zorder=2)
    axes.text(1060, len(sites) - 0.52, "1,000 uV", color=INK_SECONDARY, fontsize=8.5)
    axes.set_yticks(range(len(sites)), sites)
    axes.set_ylim(len(sites) - 0.5, -0.5)
    axes.grid(axis="x", color=GRID, linewidth=0.7)
    axes.xaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    axes.set_xlabel(
        "Largest deviation of any averaged channel around the pulse, uV (log scale)",
        color=INK_SECONDARY,
        fontsize=9,
    )
    axes.set_title(
        "Largest channel deviation around pulses, per signal-checked run",
        loc="left",
        color=INK,
        fontsize=11,
    )
    return _finish(figure, path)


def _table_html(frame: pd.DataFrame, numeric: tuple[str, ...] = ()) -> str:
    head = "".join(
        f"<th{' class=n' if c in numeric else ''}>{html.escape(c.replace('_', ' '))}</th>"
        for c in frame.columns
    )
    rows = []
    for row in frame.itertuples(index=False):
        cells = "".join(
            f"<td{' class=n' if c in numeric else ''}>{html.escape(str(v))}</td>"
            for c, v in zip(frame.columns, row, strict=True)
        )
        rows.append(f"<tr>{cells}</tr>")
    return f'<div class="scroll"><table><tr>{head}</tr>{"".join(rows)}</table></div>'


def _img(data: bytes, alt: str) -> str:
    encoded = base64.b64encode(data).decode()
    return f'<figure><img alt="{html.escape(alt)}" src="data:image/png;base64,{encoded}"></figure>'


def build_facts(inputs: Inputs) -> dict:
    """The headline numbers, kept in one place and saved next to the report."""
    tms = inputs.recordings[inputs.recordings["task"] == "tmseeg"]
    gaps = usable_gaps(inputs.pulses)
    artifact = inputs.artifact
    large = (artifact["peak_deviation_uv"] >= 1000) | (artifact["peak_channel_uv"] >= 1000)
    severe = int(large.sum())
    flagged = inputs.issues[inputs.issues["rule"] == "signal.residual_pulse_artifact"]
    coverage = inputs.summary["coverage"]
    return {
        "subjects": len(inputs.participants),
        "tmseeg_runs": len(tms),
        "pulse_markers": len(inputs.pulses),
        "markers_after_duplicates": int((~inputs.pulses["is_duplicate"].astype(bool)).sum()),
        "duplicate_markers": int(inputs.pulses["is_duplicate"].astype(bool).sum()),
        "issues": len(inputs.issues),
        "runs_with_120_markers": int((tms["pulse_count"] == EXPECTED_PULSES).sum()),
        "runs_checked_events": coverage["runs_checked_events"],
        "runs_checked_against_header": coverage["runs_checked_against_header"],
        "runs_checked_signal": coverage["runs_checked_signal"],
        "subjects_signal_checked": len(coverage["subjects_with_signal_checked"]),
        "gap_median_s": round(float(np.median(gaps)), 3) if len(gaps) else None,
        "gaps_total": len(gaps),
        "gaps_in_published_range": int(((gaps >= 4) & (gaps <= 6)).sum()),
        "signal_runs_with_residual_artifact": len(flagged),
        "signal_runs_at_or_over_1000_uv": severe,
        "peak_channel_max_uv": float(artifact["peak_channel_uv"].max()) if len(artifact) else None,
        "signal_runs_header_says_interpolated_but_over_1000_uv": int(
            (artifact["header_says_interpolated"] & large).sum()
        ),
    }


def write_report(inputs: Inputs, output: Path) -> Path:
    """Write ``report.html``, chart images, CSVs and ``report_facts.json`` to ``output``."""
    output = Path(output)
    charts = output / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    counts = marker_count_table(inputs.recordings)
    gaps = gap_histogram(usable_gaps(inputs.pulses))
    rules = rule_table(inputs.issues)
    facts = build_facts(inputs)

    counts.to_csv(output / "marker_counts.csv", index=False)
    gaps.to_csv(output / "gap_histogram.csv", index=False)
    rules.to_csv(output / "issues_by_rule.csv", index=False)
    inputs.issues.to_csv(output / "issues.csv", index=False)
    inputs.artifact.to_csv(output / "pulse_artifact.csv", index=False)
    inputs.recordings.to_csv(output / "recordings.csv", index=False)
    (output / "report_facts.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")

    chart_a = chart_marker_counts(counts, charts / "marker_counts.png")
    chart_b = chart_gaps(gaps, charts / "pulse_spacing.png")
    chart_c = chart_rules(rules, charts / "issues_by_rule.png")
    chart_d = (
        chart_artifact(inputs.artifact, charts / "pulse_artifact.png")
        if len(inputs.artifact)
        else b""
    )

    tiles = [
        (f"{facts['subjects']}", "subjects"),
        (f"{facts['tmseeg_runs']}", "TMS runs"),
        (f"{facts['pulse_markers']:,}", "pulse markers"),
        (f"{facts['markers_after_duplicates']:,}", "markers after duplicates"),
        (f"{facts['issues']}", "issues recorded"),
    ]
    tile_html = "".join(f"<div class=tile><b>{a}</b><span>{b}</span></div>" for a, b in tiles)
    worst = inputs.artifact.sort_values("peak_channel_uv", ascending=False).head(10)
    worst = worst[
        [
            "subject",
            "acquisition",
            "peak_channel",
            "peak_channel_uv",
            "peak_deviation_uv",
            "peak_field_power_uv",
            "header_says_interpolated",
        ]
    ].rename(columns={"acquisition": "site"})
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TMS-EEG Quality Report</title><style>{_STYLE}</style></head><body><main>
<h1>TMS-EEG data quality report</h1>
<p class=lede>OpenNeuro ds008037 v1.0.1. These are observations from the published files. Their
causes are not known, and nothing here has been fixed or removed.</p>
<div class=tiles>{tile_html}</div>

<h2>What was checked</h2>
<p>Event timing was checked on {facts["runs_checked_events"]} of {facts["tmseeg_runs"]} TMS runs,
and sidecars against headers on {facts["runs_checked_against_header"]}. Signal checks covered
{facts["runs_checked_signal"]} runs from {facts["subjects_signal_checked"]} subjects.</p>
<div class=note>The signal-checked subjects were chosen to include known problems, so they are not a
random sample. Do not read their rates as rates for the whole dataset.</div>

<h2>Pulse counts</h2>
<p>{facts["runs_with_120_markers"]} of {facts["tmseeg_runs"]} runs have the planned 120 markers.
Counts near 240 are mostly suspected doubled markers.</p>
{_img(chart_a, "Bar chart of TMS runs grouped by how many pulse markers they contain")}
{_table_html(counts, ("runs",))}

<h2>Pulse spacing</h2>
<p>Counting every gap of 2 ms or more, the median gap between markers is {facts["gap_median_s"]} s. Of
{facts["gaps_total"]:,} gaps, {facts["gaps_in_published_range"]} fall in the published 4 to 6 s
range. Gaps over 7 s are not drawn, but are in the data.</p>
{_img(chart_b, "Histogram of seconds between markers, almost all below the published range")}

<h2>Disturbance around the pulse</h2>
<p>{facts["signal_runs_with_residual_artifact"]} of {facts["runs_checked_signal"]} signal-checked
runs show a pulse artifact or a very large channel, and {facts["signal_runs_at_or_over_1000_uv"]} peak at 1,000 uV or more.
{facts["signal_runs_header_says_interpolated_but_over_1000_uv"]} of those record interpolation in
their header, so the header alone cannot show a run is clean.</p>
{_img(chart_d, "Dot plot of the largest channel deviation around pulses per run, by stimulation site")}
<p>Peak channel is the largest deviation of any one channel's averaged response. Deviation is the
median across channels, so it misses an artifact on a few channels. Field power counts only what
differs between channels. All three are in the recorded reference.</p>
{_table_html(worst, ("peak_channel_uv", "peak_deviation_uv", "peak_field_power_uv"))}

<h2>Issues by rule</h2>
{_img(chart_c, "Bar chart of issue counts for each quality rule")}
{_table_html(rules[["rule", "severity", "issues", "meaning"]], ("issues",))}

<h2>Files</h2>
<p>Every value above comes from these files, in this folder: <code>issues.csv</code>,
<code>issues_by_rule.csv</code>, <code>marker_counts.csv</code>, <code>gap_histogram.csv</code>,
<code>pulse_artifact.csv</code>, <code>recordings.csv</code> and <code>report_facts.json</code>.</p>
</main></body></html>
"""
    path = output / "report.html"
    path.write_text(page, encoding="utf-8")
    return path
