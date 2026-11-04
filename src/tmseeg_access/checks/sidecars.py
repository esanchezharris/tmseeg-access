"""Checks that sidecar metadata agrees with the file headers, and dataset-level claims hold up."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tmseeg_access.checks.issues import Issue


def compare_with_header(
    recording_id: str,
    subject: str,
    sidecar: dict,
    header: dict,
    tsv_channels: list[str] | None,
    tsv_events: int | None,
    protocol: dict,
) -> list[Issue]:
    """Compare one recording's sidecars with its ``.set`` header.

    ``header`` needs ``srate``, ``nbchan``, ``pnts``, ``labels`` and ``n_events``.
    """
    issues: list[Issue] = []

    def add(rule: str, where: str, seen: str, expected: str, action: str) -> None:
        issues.append(Issue(rule, "warning", where, seen, expected, action, subject, recording_id))

    rate = sidecar.get("SamplingFrequency")
    if rate is not None and float(rate) != float(header["srate"]):
        add(
            "sidecar.sampling_rate",
            "eeg.json vs .set",
            f"sidecar {rate} Hz, header {header['srate']} Hz",
            "the same value",
            "Trust the header for timing, and report the sidecar error.",
        )
    count = sidecar.get("EEGChannelCount")
    if count is not None and int(count) != int(header["nbchan"]):
        add(
            "sidecar.channel_count",
            "eeg.json vs .set",
            f"sidecar {count} channels, header {int(header['nbchan'])}",
            "the same value",
            "Use the header count, and find out which channels the sidecar counted.",
        )
    declared = sidecar.get("RecordingDuration")
    if declared is not None:
        actual = float(header["pnts"]) / float(header["srate"])
        tolerance = protocol["thresholds"]["duration_tolerance_s"]
        if abs(float(declared) - actual) > tolerance:
            add(
                "sidecar.duration",
                "eeg.json vs .set",
                f"sidecar {declared} s, header {actual:.3f} s",
                f"within {tolerance} s",
                "Use the header duration.",
            )
    if tsv_channels is not None and list(tsv_channels) != list(header["labels"]):
        same_names = sorted(tsv_channels) == sorted(header["labels"])
        extra = sorted(set(tsv_channels) - set(header["labels"]))
        missing = sorted(set(header["labels"]) - set(tsv_channels))
        add(
            "sidecar.channel_names",
            "channels.tsv vs .set",
            "same names in a different order"
            if same_names
            else f"only in tsv: {extra or 'none'}; only in header: {missing or 'none'}",
            "the same channels in the same order",
            "Match channels by name, never by position.",
        )
    if tsv_events is not None and int(tsv_events) != int(header["n_events"]):
        add(
            "sidecar.event_count",
            "events.tsv vs .set",
            f"events.tsv {tsv_events}, .set {int(header['n_events'])}",
            "the same count",
            "Compare the two event lists before trusting either.",
        )
    return issues


def check_header_provenance(
    recording_id: str,
    subject: str,
    acquisition: str,
    comments: str,
    artifact_record: dict | None,
    protocol: dict,
) -> list[Issue]:
    """Compare the site label with the original filename, and look for an artifact record.

    ``comments`` is EEGLAB's note of the source file, which often names the site. ``artifact_record``
    is TESA's ``tmscut`` entry, written when the artifact window is cut out.
    """
    issues = []
    codes = protocol["source_site_codes"]
    match = re.search(r"SP_([A-Za-z0-9]+)", comments)
    if match and codes.get(match[1].upper(), acquisition) != acquisition:
        issues.append(
            Issue(
                "header.site_mismatch",
                "error",
                ".set comments vs filename",
                f"source file says {match[1]}, recording is labelled {acquisition}",
                f"{match[1]} means {codes[match[1].upper()]}",
                "Do not trust the site label until the authors confirm it.",
                subject,
                recording_id,
            )
        )
    if not artifact_record:
        issues.append(
            Issue(
                "header.no_artifact_record",
                "warning",
                ".set tmscut field",
                "no record of artifact removal",
                "a tmscut entry, as most runs have",
                "Check the signal around pulses: this run may have had different processing.",
                subject,
                recording_id,
            )
        )
    return issues


def _referenced_suffixes(root: Path) -> set[str]:
    """File patterns that sidecars mention, such as ``*_nibs.tsv``."""
    found: set[str] = set()
    for path in root.glob("sub-*/eeg/*_eeg.json"):
        text = path.read_text(encoding="utf-8")
        found.update(re.findall(r"\*_[a-z]+\.[a-z]+(?:/[a-z]+)?", text))
    return found


def check_dangling_references(root: Path) -> list[Issue]:
    """Report file patterns mentioned in sidecars that match nothing in the dataset."""
    issues = []
    for pattern in sorted(_referenced_suffixes(root)):
        base, _, alternative = pattern.partition("/")
        stem, extension = base.split(".", 1)
        names = [f"{stem}.{extension}"] + ([f"{stem}.{alternative}"] if alternative else [])
        if any(next(root.glob(f"sub-*/**/{name}"), None) for name in names):
            continue
        issues.append(
            Issue(
                "sidecar.dangling_reference",
                "warning",
                "eeg.json sidecars",
                f"sidecars refer to {pattern}, but no such file exists",
                "every referenced file in the release",
                "Ask the authors for the stimulation metadata. Dose and coil data may be there.",
            )
        )
    return issues


def check_dataset_type(root: Path) -> list[Issue]:
    """Report a dataset labelled raw when its published methods describe preprocessing."""
    description = json.loads((root / "dataset_description.json").read_text(encoding="utf-8"))
    if description.get("DatasetType") != "raw":
        return []
    return [
        Issue(
            "dataset.not_raw",
            "info",
            "dataset_description.json",
            'DatasetType is "raw", but the preprint describes downsampling and interpolation',
            "a label that matches the processing applied",
            "Treat the data as partly preprocessed: do not reapply those steps blindly.",
        )
    ]


def check_stimulation_dose(participants_columns: list[str], root: Path) -> list[Issue]:
    """Report when no per-subject stimulation intensity is available."""
    words = ("intensity", "rmt", "mso", "dose")
    if any(any(w in column.lower() for w in words) for column in participants_columns):
        return []
    if any(
        any(w in path.read_text(encoding="utf-8").lower() for w in ('"rmt', "intensity"))
        for path in root.glob("sub-*/eeg/*task-tmseeg*_eeg.json")
    ):
        return []
    return [
        Issue(
            "metadata.no_stimulation_dose",
            "warning",
            "participants.tsv and eeg.json sidecars",
            "no stimulation intensity field for any subject",
            "per-subject intensity: the preprint reports two levels, 100% and 120% RMTadj",
            "Dose cannot be controlled for. Ask the authors for the per-subject values.",
        )
    ]
