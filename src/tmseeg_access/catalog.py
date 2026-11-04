"""A DuckDB catalog, so analysts can answer questions about the dataset with SQL.

Every recording is indexed from text metadata, whether or not its signal has been downloaded.
Header values appear only where the ``.set`` file is local, and stay NULL otherwise, so a query can
tell "not checked" from "fine". Values from different sources are kept in separate columns rather
than merged, because comparing them is the point.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import duckdb
import pandas as pd
from pymatreader import read_mat

from tmseeg_access.config import TAG, derivatives_dir
from tmseeg_access.dataset import (
    DEFAULT_DUPLICATE_GAP_S,
    PULSE_COLUMN,
    Dataset,
    flag_duplicates,
)
from tmseeg_access.download import load_manifest, manifest_path

CATALOG_NAME = "catalog.duckdb"
TABLES = ["recordings", "participants", "behavior", "pulses", "files"]
_HEADER_FIELDS = ["nbchan", "pnts", "srate"]
_PULSE_COLUMNS = [
    "recording_id",
    "subject",
    "acquisition",
    "pulse_index",
    "event_id",
    "onset_s",
    "gap_from_previous_s",
    "is_duplicate",
]


def default_path(root: Path) -> Path:
    return derivatives_dir(root) / CATALOG_NAME


def read_set_header(path: Path) -> dict[str, float]:
    """Read channel count, length and rate from a ``.set`` file, without touching the signal."""
    header = read_mat(str(path), variable_names=_HEADER_FIELDS)
    return {
        "channels_header": int(header["nbchan"]),
        "sampling_rate_header_hz": float(header["srate"]),
        "duration_s_header": float(header["pnts"]) / float(header["srate"]),
    }


def _channel_rows(path: Path) -> int | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return sum(1 for _ in handle) - 1


def _pulse_rows(ds: Dataset, row) -> pd.DataFrame:
    events = ds._read_events_file(row.subject, row.recording_id)
    pulses = events.loc[events[PULSE_COLUMN] == 1].reset_index(drop=True)
    flagged = flag_duplicates(pulses, row.sampling_rate_hz, DEFAULT_DUPLICATE_GAP_S)
    flagged = flagged.rename(columns={"onset": "onset_s"})
    flagged["recording_id"] = row.recording_id
    flagged["subject"] = row.subject
    flagged["acquisition"] = row.acquisition
    flagged["pulse_index"] = range(1, len(flagged) + 1)
    return flagged[_PULSE_COLUMNS]


def _recording_rows(ds: Dataset) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = ds.recording_summary()
    summary.insert(0, "recording_id", ds._recordings["stem"].to_numpy())
    extras, pulses = [], []
    for row in summary.itertuples(index=False):
        eeg_dir = ds.root / row.subject / "eeg"
        extra = {
            "recording_id": row.recording_id,
            "channels_tsv": _channel_rows(eeg_dir / f"{row.recording_id}_channels.tsv"),
            "channels_header": None,
            "sampling_rate_header_hz": None,
            "duration_s_header": None,
        }
        if row.has_header:
            extra.update(read_set_header(eeg_dir / f"{row.recording_id}_eeg.set"))
        extras.append(extra)
        if pd.notna(row.pulse_count):
            pulses.append(_pulse_rows(ds, row))
    table = summary.merge(pd.DataFrame(extras), on="recording_id")
    for column in ["channels_header", "sampling_rate_header_hz", "duration_s_header"]:
        table[column] = pd.to_numeric(table[column])
    pulse_table = (
        pd.concat(pulses, ignore_index=True) if pulses else pd.DataFrame(columns=_PULSE_COLUMNS)
    )
    return table, pulse_table


def _file_rows(root: Path, tag: str) -> pd.DataFrame:
    columns = ["path", "size_bytes", "hash_algo", "hash_value", "local"]
    manifest = manifest_path(root, tag)
    if not manifest.exists():
        return pd.DataFrame(
            {
                "path": pd.Series(dtype="str"),
                "size_bytes": pd.Series(dtype="int64"),
                "hash_algo": pd.Series(dtype="str"),
                "hash_value": pd.Series(dtype="str"),
                "local": pd.Series(dtype="bool"),
            }
        )
    rows = [
        (f.path, f.size, f.hash_algo, f.hash_value, (root / f.path).exists())
        for f in load_manifest(manifest)
    ]
    return pd.DataFrame(rows, columns=columns)


def build_catalog(ds: Dataset, path: Path | None = None, tag: str = TAG) -> dict:
    """Build the catalog from scratch. The new file replaces the old one only once complete."""
    target = Path(path) if path is not None else default_path(ds.root)
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_name(target.name + ".tmp")
    scratch.unlink(missing_ok=True)
    started = time.perf_counter()
    recordings, pulses = _recording_rows(ds)
    frames = {
        "recordings": recordings,
        "participants": ds._participants,
        "behavior": ds.behavior_summary(),
        "pulses": pulses,
        "files": _file_rows(ds.root, tag),
    }
    con = duckdb.connect(str(scratch))
    try:
        for name, frame in frames.items():
            con.register("frame", frame)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM frame")
            con.unregister("frame")
        counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        con.close()
    os.replace(scratch, target)
    return {
        "path": str(target),
        "tables": counts,
        "seconds_to_build": round(time.perf_counter() - started, 2),
        "file_bytes": target.stat().st_size,
    }


def query(path: Path, sql: str) -> pd.DataFrame:
    """Run read-only SQL against a catalog."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute(sql).df()
    finally:
        con.close()
