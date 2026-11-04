"""Measure the MATLAB export round trip on real data. Writes results/matlab_roundtrip.json.

Files are read back in Python. MATLAB itself was not available, so opening them in MATLAB or EEGLAB
is still unverified.
"""

from __future__ import annotations

import json
from pathlib import Path

import mne
import numpy as np

from tmseeg_access.config import derivatives_dir
from tmseeg_access.dataset import Dataset
from tmseeg_access.matlab import (
    export_epochs_mat,
    export_epochs_set,
    export_metadata,
    read_epochs_mat,
    read_metadata_mat,
)

OUTPUT = Path(__file__).resolve().parents[1] / "results" / "matlab_roundtrip.json"


def main() -> None:
    ds = Dataset()
    epochs = ds.epochs_around_pulses("sub-001", "parietal", baseline=(-0.1, -0.01))
    folder = derivatives_dir(ds.root) / "export"
    folder.mkdir(parents=True, exist_ok=True)
    original = epochs.get_data()

    mat_path = export_epochs_mat(epochs, folder / "sub-001_parietal_epochs.mat")
    mat = read_epochs_mat(mat_path)
    set_path = export_epochs_set(epochs, folder / "sub-001_parietal_epochs.set")
    from_set = mne.read_epochs_eeglab(set_path, verbose="ERROR")

    table = ds.metadata()
    back = read_metadata_mat(export_metadata(table, folder / "metadata.mat"))
    result = {
        "verified_in_matlab": False,
        "epochs_shape": list(original.shape),
        "mat": {
            "max_abs_difference_uv": float(np.abs(mat["data_uv"] - original * 1e6).max()),
            "channels_match": mat["channels"] == epochs.ch_names,
            "epoch_table_rows": len(mat["epochs_table"]["event_id"]),
            "file_bytes": mat_path.stat().st_size,
        },
        "set": {
            "max_abs_difference_uv": float(np.abs(from_set.get_data() - original).max() * 1e6),
            "channels_match": from_set.ch_names == epochs.ch_names,
            "file_bytes": set_path.stat().st_size,
        },
        "metadata": {"rows": len(back), "columns": len(back.columns)},
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
