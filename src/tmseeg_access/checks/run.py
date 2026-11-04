"""Run every check that the local files allow, and say which ones could not run.

A check that cannot run is reported as coverage, not treated as a pass.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pymatreader import read_mat

from tmseeg_access.checks import consistency, sidecars, signal, timing
from tmseeg_access.checks.issues import Issue, issues_frame, load_protocol
from tmseeg_access.dataset import PULSE_COLUMN, Dataset


def _read_header(path) -> dict:
    fields = ["nbchan", "pnts", "srate", "chanlocs", "event", "comments", "tmscut"]
    header = read_mat(str(path), variable_names=fields)
    locations = header["chanlocs"]
    events = header["event"]
    latency = events.get("latency", []) if isinstance(events, dict) else []
    record = header.get("tmscut")
    return {
        "comments": str(header.get("comments", "")),
        "artifact_record": record if isinstance(record, dict) and record else None,
        "nbchan": header["nbchan"],
        "pnts": header["pnts"],
        "srate": header["srate"],
        "labels": list(np.atleast_1d(locations["labels"])),
        "n_events": np.size(latency),
    }


def run_all(ds: Dataset, protocol: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Run all checks. Returns the issues, and a summary of what each tier covered."""
    protocol = protocol or load_protocol()
    summary = ds.recording_summary()
    stems = ds._recordings["stem"].to_numpy()
    summary.insert(0, "recording_id", stems)
    task = protocol["dataset"]["task"]
    tms = summary[summary["task"] == task]

    issues: list[Issue] = []
    issues += consistency.check_missing_runs(ds.recordings(), ds.subjects(), protocol)
    issues += consistency.check_uniform(summary)
    issues += consistency.check_participants(ds._participants, ds.recordings())
    issues += sidecars.check_dangling_references(ds.root)
    issues += sidecars.check_dataset_type(ds.root)
    issues += sidecars.check_stimulation_dose(list(ds._participants.columns), ds.root)

    all_gaps = []
    names: dict[str, tuple[str, list[str]]] = {}
    triggers: dict[str, tuple[str, str]] = {}
    headers_checked = signal_checked = 0
    artifact_rows = []
    for row in tms.itertuples(index=False):
        events = ds._read_events_file(row.subject, row.recording_id)
        pulses = events.loc[events[PULSE_COLUMN] == 1].reset_index(drop=True)
        all_gaps.append(np.diff(pulses["onset"].to_numpy(dtype=float)))
        sidecar = ds._sidecar(row.subject, row.recording_id)
        issues += timing.check_run(
            pulses, protocol, row.subject, row.recording_id, sidecar.get("RecordingDuration")
        )

        eeg_dir = ds.root / row.subject / "eeg"
        channels_path = eeg_dir / f"{row.recording_id}_channels.tsv"
        tsv_channels = None
        if channels_path.exists():
            channels = pd.read_csv(channels_path, sep="\t")
            tsv_channels = channels["name"].tolist()
            names[row.recording_id] = (row.subject, tsv_channels)
            trigger = channels.loc[channels["name"] == signal.TRIGGER, "type"]
            if len(trigger):
                triggers[row.recording_id] = (row.subject, trigger.iloc[0])

        if row.has_header:
            header = _read_header(eeg_dir / f"{row.recording_id}_eeg.set")
            issues += sidecars.compare_with_header(
                row.recording_id, row.subject, sidecar, header, tsv_channels, len(events), protocol
            )
            issues += sidecars.check_header_provenance(
                row.recording_id,
                row.subject,
                row.acquisition,
                header["comments"],
                header["artifact_record"],
                protocol,
            )
            headers_checked += 1

        if row.has_signal:
            raw = ds.load_raw(row.subject, task=task, acquisition=row.acquisition)
            data, labels = raw.get_data() * 1e6, raw.ch_names
            issues += signal.check_channels(data, labels, protocol, row.subject, row.recording_id)
            flagged = ds.pulses(row.subject, row.acquisition, task=task)
            samples = flagged.loc[~flagged["is_duplicate"], "onset_sample"].to_numpy()
            samples = samples[samples < data.shape[1]]
            issues += signal.check_reference_channel(
                data,
                labels,
                sidecar.get("EEGReference"),
                protocol,
                row.subject,
                row.recording_id,
            )
            eeg_only = [i for i, name in enumerate(labels) if name != signal.TRIGGER]
            measured = signal.measure_pulse_artifact(
                data[eeg_only], samples, protocol, [labels[i] for i in eeg_only]
            )
            record = header["artifact_record"] if row.has_header else None
            says_interpolated = bool(record) and record.get("interpolated") == "yes"
            issues += signal.check_pulse_artifact(
                measured, protocol, row.subject, row.recording_id, says_interpolated
            )
            if measured is not None:
                artifact_rows.append(
                    {
                        "recording_id": row.recording_id,
                        "subject": row.subject,
                        "acquisition": row.acquisition,
                        "header_says_interpolated": says_interpolated,
                        **measured,
                    }
                )
            signal_checked += 1

    issues += consistency.check_channel_names(names)
    issues += consistency.check_name_spelling(names)
    issues += consistency.check_trigger_typed_as_eeg(triggers)
    issues += timing.check_published_spacing(np.concatenate(all_gaps), protocol)
    coverage = {
        "tmseeg_runs": len(tms),
        "runs_checked_events": len(tms),
        "runs_checked_against_header": headers_checked,
        "runs_checked_signal": signal_checked,
        "subjects_with_signal_checked": sorted(set(tms.loc[tms["has_signal"], "subject"].tolist())),
    }
    return issues_frame(issues), {"coverage": coverage, "artifact": artifact_rows}
