"""Checks across recordings: missing runs, and rates or channels that differ between files."""

from __future__ import annotations

import pandas as pd

from tmseeg_access.checks.issues import Issue


def check_missing_runs(
    recordings: pd.DataFrame, subjects: list[str], protocol: dict
) -> list[Issue]:
    """Report every expected TMS run that is not in the dataset."""
    task = protocol["dataset"]["task"]
    sites = protocol["dataset"]["sites"]
    present = recordings[recordings["task"] == task]
    have = set(zip(present["subject"], present["acquisition"], strict=True))
    issues = []
    for subject in subjects:
        missing = [site for site in sites if (subject, site) not in have]
        if missing:
            issues.append(
                Issue(
                    "recording.missing",
                    "warning",
                    "subject folder",
                    f"no {', '.join(missing)} run" + ("s" if len(missing) > 1 else ""),
                    f"{len(sites)} TMS runs: {', '.join(sites)}",
                    "Exclude from within-subject site comparisons, or ask the authors why.",
                    subject,
                )
            )
    return issues


def _majority_issue(
    table: pd.DataFrame, column: str, rule: str, label: str, action: str
) -> list[Issue]:
    values = table[column].dropna()
    if values.nunique() < 2:
        return []
    usual = values.mode().iloc[0]
    counts = values.value_counts().to_dict()
    odd = table[table[column].notna() & (table[column] != usual)]
    subjects = sorted(set(odd["subject"]))
    return [
        Issue(
            rule,
            "warning",
            f"{len(odd)} recordings in {len(subjects)} subjects",
            f"{label} values and recording counts: {counts}",
            f"one {label} across the dataset (most common: {usual})",
            action,
        )
    ]


def check_uniform(recordings: pd.DataFrame) -> list[Issue]:
    """Report sampling rates or channel counts that differ between TMS recordings."""
    tms = recordings[recordings["task"] == "tmseeg"]
    issues = _majority_issue(
        tms,
        "sampling_rate_hz",
        "rate.inconsistent",
        "sampling rate",
        "Resample deliberately before combining recordings.",
    )
    issues += _majority_issue(
        tms,
        "channels_sidecar",
        "channels.inconsistent",
        "channel count",
        "Compare channel names and pick a shared set before combining subjects.",
    )
    return issues


def _channel_key(names: list[str]) -> tuple[str, ...]:
    """Electrodes in a recording, ignoring spelling case and the trigger channel."""
    return tuple(sorted(name.upper() for name in names if name.upper() != "TRIGGER"))


def check_channel_names(names_by_recording: dict[str, tuple[str, list[str]]]) -> list[Issue]:
    """Report recordings whose channel names differ from the most common set."""
    sets = pd.Series({rid: _channel_key(n) for rid, (_, n) in names_by_recording.items()})
    if sets.empty or sets.nunique() < 2:
        return []
    usual = set(sets.mode().iloc[0])
    issues = []
    for recording_id, names in sets.items():
        current = set(names)
        if current == usual:
            continue
        subject = names_by_recording[recording_id][0]
        only_here = sorted(current - usual)
        absent = sorted(usual - current)
        issues.append(
            Issue(
                "channels.names_differ",
                "info",
                "channels.tsv",
                f"extra: {only_here or 'none'}; missing: {absent or 'none'}",
                f"the {len(usual)}-channel set most recordings use",
                "Use the shared channels when combining this recording with others.",
                subject,
                recording_id,
            )
        )
    return issues


def check_name_spelling(names_by_recording: dict[str, tuple[str, list[str]]]) -> list[Issue]:
    """Report when the same electrode is spelled two ways, such as ``Cz`` and ``CZ``."""
    mixed = {
        rid: subject
        for rid, (subject, names) in names_by_recording.items()
        if any(name != name.upper() for name in names)
    }
    if not mixed or len(mixed) == len(names_by_recording):
        return []
    return [
        Issue(
            "channels.name_spelling",
            "warning",
            f"{len(mixed)} recordings in {len(set(mixed.values()))} subjects",
            "these recordings use mixed-case names (Cz, Fp1). The others use upper case (CZ, FP1)",
            "one spelling for each electrode",
            "Compare names case-insensitively, or matching by name will split electrodes.",
        )
    ]


def check_trigger_typed_as_eeg(trigger_rows: dict[str, tuple[str, str]]) -> list[Issue]:
    """Report a trigger channel listed as EEG. ``trigger_rows``: recording -> (subject, type)."""
    wrong = {rid: subject for rid, (subject, kind) in trigger_rows.items() if kind == "EEG"}
    if not wrong:
        return []
    return [
        Issue(
            "channels.trigger_typed_as_eeg",
            "error",
            f"{len(wrong)} recordings in {len(set(wrong.values()))} subjects",
            "channels.tsv lists TRIGGER as type EEG, so it loads as EEG and sidecars count it",
            "a TRIGGER type, counted in TriggerChannelCount",
            "Exclude it before average referencing: exclude_channels=('TRIGGER',).",
        )
    ]


def check_participants(participants: pd.DataFrame, recordings: pd.DataFrame) -> list[Issue]:
    """Report subjects that appear on one side only, and missing participant fields."""
    issues = []
    listed = set(participants["subject"])
    with_files = set(recordings["subject"])
    for subject in sorted(with_files - listed):
        issues.append(
            Issue(
                "participant.unlisted",
                "warning",
                "participants.tsv",
                "has recordings but no participants row",
                "a row for every subject",
                "Demographic joins will be empty for this subject.",
                subject,
            )
        )
    for subject in sorted(listed - with_files):
        issues.append(
            Issue(
                "participant.no_recordings",
                "warning",
                "subject folder",
                "listed in participants.tsv but has no EEG recordings",
                "EEG recordings for every listed subject",
                "Expect behavioural data only for this subject, if any.",
                subject,
            )
        )
    for column in participants.columns.drop("subject"):
        missing = int(participants[column].isna().sum())
        if missing:
            issues.append(
                Issue(
                    "participant.missing_value",
                    "info",
                    f"participants.tsv column {column}",
                    f"{missing} of {len(participants)} subjects have no value",
                    "a value for every subject",
                    "Handle the gap explicitly in any analysis that uses this field.",
                )
            )
    return issues
