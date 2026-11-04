"""The analyst-facing API: subjects, recordings, metadata, raw data and epochs around pulses.

Tables are read on first use and kept in memory. Signal is opened lazily through MNE, so listing
and filtering never touch the large binary files. Nothing here repairs or drops data without being
told to: ambiguous pulses raise an error that names the problem.

ds008037 has no BIDS sessions. Stimulation site is the ``acquisition`` entity (``parietal``,
``prefrontal``, ``premotor``, ``control``).
"""

from __future__ import annotations

import json
import os
import re
from functools import cached_property, lru_cache

import mne
import numpy as np
import pandas as pd
from mne_bids import BIDSPath, read_raw_bids

from tmseeg_access.behavior import SUMMARIES, read_beh, summarize_subject
from tmseeg_access.config import resolve_data_root

_SIDECAR = re.compile(
    r"^(?P<subject>sub-[^_]+)_task-(?P<task>[^_]+)(?:_acq-(?P<acq>[^_]+))?_eeg\.json$"
)
PULSE_COLUMN = "is_tms_pulse"
DEFAULT_DUPLICATE_GAP_S = 0.002


class DataNotLocalError(FileNotFoundError):
    """The recording exists in the dataset but its signal has not been downloaded."""


class DuplicatePulseError(ValueError):
    """Pulse markers sit too close together to be separate pulses."""


def _subject_label(subject: str) -> str:
    return subject if subject.startswith("sub-") else f"sub-{subject}"


class Dataset:
    """A local copy of a BIDS TMS-EEG dataset.

    Parameters
    ----------
    path
        Dataset root. Defaults to the ``TMSEEG_DATA_ROOT`` environment variable.
    cache_size
        How many opened raw recordings to keep in memory.
    """

    def __init__(self, path: str | os.PathLike | None = None, cache_size: int = 4) -> None:
        self.root = resolve_data_root(path)
        if not (self.root / "dataset_description.json").is_file():
            raise FileNotFoundError(f"Not a BIDS dataset: {self.root}")
        self._open_raw = lru_cache(maxsize=cache_size)(self._open_raw_uncached)
        self._events = lru_cache(maxsize=64)(self._events_uncached)

    def __repr__(self) -> str:
        return f"Dataset({str(self.root)!r}, subjects={len(self.subjects())})"

    # ----- listings -----

    @cached_property
    def _recordings(self) -> pd.DataFrame:
        rows = []
        for sidecar in sorted(self.root.glob("sub-*/eeg/*_eeg.json")):
            match = _SIDECAR.match(sidecar.name)
            if match is None:
                continue
            stem = sidecar.name.removesuffix("_eeg.json")
            eeg_dir = sidecar.parent
            rows.append(
                {
                    "subject": match["subject"],
                    "task": match["task"],
                    "acquisition": match["acq"],
                    "stem": stem,
                    "has_header": (eeg_dir / f"{stem}_eeg.set").exists(),
                    "has_signal": (eeg_dir / f"{stem}_eeg.fdt").exists(),
                }
            )
        return pd.DataFrame(rows)

    @cached_property
    def _participants(self) -> pd.DataFrame:
        table = pd.read_csv(self.root / "participants.tsv", sep="\t", na_values=["n/a"])
        return table.rename(columns={"participant_id": "subject"}).sort_values("subject")

    def subjects(self) -> list[str]:
        """Every subject in ``participants.tsv``, including any with no EEG files."""
        return self._participants["subject"].tolist()

    def sessions(self, subject: str) -> list[str]:
        """BIDS sessions for a subject. Empty when the dataset has no session level."""
        directory = self.root / _subject_label(subject)
        if not directory.is_dir():
            raise KeyError(f"Unknown subject: {subject}")
        return sorted(p.name for p in directory.glob("ses-*") if p.is_dir())

    def recordings(self, subject: str | None = None, task: str | None = None) -> pd.DataFrame:
        """List recordings, showing whether each one's signal is available locally."""
        table = self._recordings.drop(columns="stem")
        if subject is not None:
            table = table[table["subject"] == _subject_label(subject)]
        if task is not None:
            table = table[table["task"] == task]
        return table.reset_index(drop=True)

    # ----- metadata -----

    def _sidecar(self, subject: str, stem: str) -> dict:
        path = self.root / subject / "eeg" / f"{stem}_eeg.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def recording_summary(self) -> pd.DataFrame:
        """One row per recording, built from text metadata only."""
        rows = []
        for row in self._recordings.itertuples(index=False):
            sidecar = self._sidecar(row.subject, row.stem)
            events = self._read_events_file(row.subject, row.stem)
            rows.append(
                {
                    "subject": row.subject,
                    "task": row.task,
                    "acquisition": row.acquisition,
                    "sampling_rate_hz": sidecar.get("SamplingFrequency"),
                    "channels_sidecar": sidecar.get("EEGChannelCount"),
                    "duration_s_sidecar": sidecar.get("RecordingDuration"),
                    "reference": sidecar.get("EEGReference"),
                    "n_events": None if events is None else len(events),
                    "pulse_count": _pulse_count(events),
                    "has_header": row.has_header,
                    "has_signal": row.has_signal,
                }
            )
        table = pd.DataFrame(rows)
        for column in ["n_events", "pulse_count"]:
            table[column] = table[column].astype("Int64")  # whole numbers, empty when not TMS
        return table

    def metadata(self, behavior: bool = True) -> pd.DataFrame:
        """Recordings joined to participant fields and, optionally, behavioural summaries.

        ds008037 publishes no per-subject stimulation intensity, so none appears here. See
        NOTES.md.
        """
        table = self.recording_summary().merge(self._participants, on="subject", how="left")
        if behavior:
            table = table.merge(self.behavior_summary(), on="subject", how="left")
        return table

    def behavior_summary(self) -> pd.DataFrame:
        """One row per subject. See ``tmseeg_access.behavior.SUMMARIES`` for the definitions."""
        rows = [{"subject": s, **summarize_subject(self.root, s)} for s in self.subjects()]
        return pd.DataFrame(rows, columns=["subject", *SUMMARIES])

    def behavior(self, task: str) -> pd.DataFrame:
        """Trial-level behavioural data for one task, across all subjects that have it."""
        frames = []
        for subject in self.subjects():
            table = read_beh(self.root, subject, task)
            if table is not None:
                table = table.drop(columns=["participant_id"], errors="ignore")
                frames.append(table.assign(subject=subject))
        if not frames:
            raise KeyError(f"No behavioural files for task {task!r}")
        return pd.concat(frames, ignore_index=True)

    # ----- events -----

    def _stem(self, subject: str, task: str, acquisition: str | None) -> str:
        subject = _subject_label(subject)
        stem = f"{subject}_task-{task}" + (f"_acq-{acquisition}" if acquisition else "")
        if not (self.root / subject / "eeg" / f"{stem}_eeg.json").exists():
            raise KeyError(f"No recording for {stem}")
        return stem

    def _read_events_file(self, subject: str, stem: str) -> pd.DataFrame | None:
        path = self.root / subject / "eeg" / f"{stem}_events.tsv"
        if not path.exists():
            return None
        return pd.read_csv(path, sep="\t", na_values=["n/a"], low_memory=False)

    def _events_uncached(self, subject: str, stem: str) -> pd.DataFrame | None:
        return self._read_events_file(subject, stem)

    def events(
        self, subject: str, task: str = "tmseeg", acquisition: str | None = None
    ) -> pd.DataFrame:
        """The recording's ``events.tsv`` exactly as published."""
        subject = _subject_label(subject)
        table = self._events(subject, self._stem(subject, task, acquisition))
        if table is None:
            raise KeyError(f"No events file for {subject} {task} {acquisition}")
        return table.copy()

    def pulses(
        self,
        subject: str,
        acquisition: str,
        task: str = "tmseeg",
        duplicate_gap_s: float = DEFAULT_DUPLICATE_GAP_S,
    ) -> pd.DataFrame:
        """TMS pulse markers with their spacing, and suspected duplicates flagged, not removed.

        ``onset_sample`` is the 0-based sample for MNE, computed from ``onset``. The published
        ``sample`` column is EEGLAB's 1-based latency, so it is deliberately not used here.
        """
        events = self.events(subject, task, acquisition)
        if PULSE_COLUMN not in events:
            raise KeyError(f"{task} events have no {PULSE_COLUMN} column")
        pulses = events.loc[events[PULSE_COLUMN] == 1].reset_index(drop=True)
        rate = self._sidecar(_subject_label(subject), self._stem(subject, task, acquisition))[
            "SamplingFrequency"
        ]
        return flag_duplicates(pulses, rate, duplicate_gap_s)

    # ----- signal -----

    def _open_raw_uncached(self, stem: str, subject: str, preload: bool) -> mne.io.BaseRaw:
        fields = dict(part.split("-", 1) for part in stem.split("_"))
        path = BIDSPath(
            root=self.root,
            subject=fields["sub"],
            task=fields["task"],
            acquisition=fields.get("acq"),
            datatype="eeg",
            suffix="eeg",
            extension=".set",
        )
        if not (self.root / subject / "eeg" / f"{stem}_eeg.fdt").exists():
            raise DataNotLocalError(
                f"{stem} is in the dataset but its signal is not downloaded. Run: "
                f"tmseeg-access download --tier signal --subjects {subject}"
            )
        raw = read_raw_bids(path, verbose="ERROR")
        return raw.load_data(verbose="ERROR") if preload else raw

    def load_raw(
        self,
        subject: str,
        session: str | None = None,
        task: str = "tmseeg",
        acquisition: str | None = None,
        preload: bool = False,
    ) -> mne.io.BaseRaw:
        """Open one recording. Returns a copy, so editing it cannot affect the cache."""
        if session is not None:
            raise ValueError("This dataset has no sessions. Use acquisition= to pick a site.")
        subject = _subject_label(subject)
        return self._open_raw(self._stem(subject, task, acquisition), subject, preload).copy()

    def epochs_around_pulses(
        self,
        subject: str,
        acquisition: str,
        tmin: float = -0.1,
        tmax: float = 0.5,
        baseline: tuple[float | None, float | None] | None = None,
        on_duplicate: str = "error",
        duplicate_gap_s: float = DEFAULT_DUPLICATE_GAP_S,
    ) -> mne.Epochs:
        """Cut epochs around each TMS pulse.

        ``on_duplicate="error"`` (the default) refuses to continue if any markers are closer than
        ``duplicate_gap_s``. ``"keep_first"`` keeps the first marker of each group. Either way the
        choice and what it removed are recorded in ``epochs.info["description"]`` as JSON, and
        each epoch's source marker is in ``epochs.metadata``. No baseline is applied unless asked.
        """
        if on_duplicate not in {"error", "keep_first"}:
            raise ValueError("on_duplicate must be 'error' or 'keep_first'")
        pulses = self.pulses(subject, acquisition, duplicate_gap_s=duplicate_gap_s)
        duplicates = int(pulses["is_duplicate"].sum())
        if duplicates and on_duplicate == "error":
            raise DuplicatePulseError(
                f"{_subject_label(subject)} {acquisition}: {duplicates} of {len(pulses)} markers "
                f"are within {duplicate_gap_s} s of the previous one (QC rule pulse.duplicate). "
                "Review them, then pass on_duplicate='keep_first' to keep the first of each group."
            )
        kept = pulses.loc[~pulses["is_duplicate"]].reset_index(drop=True)
        raw = self._open_raw(
            self._stem(subject, "tmseeg", acquisition), _subject_label(subject), True
        )
        samples = kept["onset_sample"].to_numpy(dtype=int) + raw.first_samp
        events = np.column_stack(
            [samples, np.zeros(len(samples), dtype=int), np.ones(len(samples), dtype=int)]
        )
        metadata = kept[["event_id", "onset", "onset_sample", "gap_from_previous_s"]].copy()
        metadata.insert(0, "subject", _subject_label(subject))
        metadata.insert(1, "acquisition", acquisition)
        epochs = mne.Epochs(
            raw,
            events,
            event_id={acquisition: 1},
            tmin=tmin,
            tmax=tmax,
            baseline=baseline,
            metadata=metadata,
            reject_by_annotation=False,
            preload=True,
            verbose="ERROR",
        )
        epochs.info["description"] = json.dumps(
            {
                "source": self._stem(subject, "tmseeg", acquisition),
                "on_duplicate": on_duplicate,
                "duplicate_gap_s": duplicate_gap_s,
                "markers_in_events_tsv": len(pulses),
                "duplicates_removed": duplicates,
                "epochs_lost_at_recording_edges": len(kept) - len(epochs),
                "tmin": tmin,
                "tmax": tmax,
                "baseline": baseline,
            }
        )
        return epochs


def _pulse_count(events: pd.DataFrame | None) -> int | None:
    if events is None or PULSE_COLUMN not in events:
        return None
    return int((events[PULSE_COLUMN] == 1).sum())


def flag_duplicates(pulses: pd.DataFrame, rate: float, gap_s: float) -> pd.DataFrame:
    """Add spacing columns and flag each marker that follows the previous one within ``gap_s``."""
    table = pulses.copy()
    table["gap_from_previous_s"] = table["onset"].diff()
    table["is_duplicate"] = table["gap_from_previous_s"] < gap_s
    table["onset_sample"] = np.rint(table["onset"] * rate).astype(int)
    return table
