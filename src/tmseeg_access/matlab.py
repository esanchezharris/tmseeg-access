"""Export epochs and metadata so MATLAB users can work with the same data.

Two epoch formats. ``.mat`` is a plain structure, with signal in microvolts as trials x channels x
samples, for direct use in MATLAB. ``.set`` opens in EEGLAB. EEGLAB files cannot carry the per-epoch
table or provenance, so those are written beside the ``.set`` file.
"""

from __future__ import annotations

import json
from pathlib import Path

import mne
import numpy as np
import pandas as pd
from scipy.io import loadmat, savemat

UV_PER_VOLT = 1e6


def _column_for_mat(column: pd.Series) -> np.ndarray:
    """Numbers stay numeric with NaN for gaps. Everything else becomes a cell of strings."""
    if pd.api.types.is_bool_dtype(column):
        return column.to_numpy(dtype=float)
    if pd.api.types.is_numeric_dtype(column):
        return column.to_numpy(dtype=float, na_value=np.nan)
    return np.array(["" if pd.isna(v) else str(v) for v in column], dtype=object)


def _table_for_mat(table: pd.DataFrame) -> dict:
    return {name: _column_for_mat(table[name]) for name in table.columns}


def export_epochs_mat(epochs: mne.Epochs, path: Path) -> Path:
    """Write epochs, times, channel names, the per-epoch table and provenance to a ``.mat`` file."""
    path = Path(path)
    content = {
        "data_uv": epochs.get_data(copy=True) * UV_PER_VOLT,
        "times_s": epochs.times,
        "channels": np.array(epochs.ch_names, dtype=object),
        "sampling_rate_hz": float(epochs.info["sfreq"]),
        "dimensions": "trials x channels x samples",
        "provenance_json": epochs.info["description"] or "",
    }
    if epochs.metadata is not None:
        content["epochs_table"] = _table_for_mat(epochs.metadata.reset_index(drop=True))
    savemat(path, content, appendmat=False, do_compression=True, oned_as="column")
    return path


def read_epochs_mat(path: Path) -> dict:
    """Read a ``.mat`` export back into Python. Used to verify the round trip."""
    content = loadmat(path, squeeze_me=True, struct_as_record=False)
    table = content["epochs_table"]
    channels = [str(name) for name in np.atleast_1d(content["channels"])]
    times = np.atleast_1d(content["times_s"])
    return {
        "data_uv": content["data_uv"].reshape(-1, len(channels), len(times)),
        "times_s": times,
        "channels": channels,
        "sampling_rate_hz": float(content["sampling_rate_hz"]),
        "provenance": json.loads(content["provenance_json"]),
        "epochs_table": {name: np.atleast_1d(getattr(table, name)) for name in table._fieldnames},
    }


def export_epochs_set(epochs: mne.Epochs, path: Path) -> Path:
    """Write an EEGLAB ``.set`` file, with its epoch table and provenance beside it."""
    path = Path(path)
    epochs.export(path, fmt="eeglab", overwrite=True, verbose="ERROR")
    if epochs.metadata is not None:
        epochs.metadata.to_csv(path.with_name(f"{path.stem}_epochs.csv"), index=False)
    path.with_name(f"{path.stem}_provenance.json").write_text(
        (epochs.info["description"] or "{}") + "\n", encoding="utf-8"
    )
    return path


def export_metadata(table: pd.DataFrame, path: Path) -> Path:
    """Write a metadata table to a ``.mat`` structure with one field per column."""
    path = Path(path)
    savemat(path, {"metadata": _table_for_mat(table)}, appendmat=False, oned_as="column")
    return path


def read_metadata_mat(path: Path) -> pd.DataFrame:
    """Read a metadata export back into Python. Used to verify the round trip."""
    content = loadmat(path, squeeze_me=True, struct_as_record=False)["metadata"]
    return pd.DataFrame({name: getattr(content, name) for name in content._fieldnames})
