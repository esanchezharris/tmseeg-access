"""Open the exports in GNU Octave and EEGLAB, and compare with the original epochs.

Writes results/octave_roundtrip.json. Octave is a separate implementation of the MATLAB language, so
this tests the file formats and the documented code, but it isn't a test in MATLAB itself.

Needs OCTAVE_CLI (path to octave-cli) and EEGLAB_PATH (an EEGLAB checkout).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import mne
import numpy as np

from tmseeg_access.config import derivatives_dir
from tmseeg_access.dataset import Dataset
from tmseeg_access.matlab import export_epochs_mat, export_epochs_set, export_metadata

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "results" / "octave_roundtrip.json"
TIMEOUT_S = 540


def run_octave(export_dir: Path, report_path: Path) -> subprocess.CompletedProcess:
    call = "open_exports_check('{}', '{}', '{}')".format(
        export_dir.as_posix(), Path(os.environ["EEGLAB_PATH"]).as_posix(), report_path.as_posix()
    )
    command = [os.environ["OCTAVE_CLI"], "--no-gui", "--norc", "--quiet"]
    command += ["--path", (REPO / "scripts").as_posix(), "--eval", call]
    return subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_S, check=False)


def max_difference(seen: list[float], expected: np.ndarray) -> float:
    return float(np.abs(np.asarray(seen, dtype=float) - expected).max())


def check_mat(seen: dict, epochs: mne.BaseEpochs, uv: np.ndarray) -> dict:
    return {
        "shape_match": seen["data_size"] == list(uv.shape),
        "channels_match": seen["channels"] == epochs.ch_names,
        "epoch_ids_match": seen["event_ids"] == epochs.metadata["event_id"].tolist(),
        "provenance_fields": len(seen["provenance_fields"]),
        "times_match": bool(
            np.isclose(seen["times_first_s"], epochs.times[0])
            and np.isclose(seen["times_last_s"], epochs.times[-1])
        ),
        "channel_mean_max_difference_uv": max_difference(
            seen["channel_mean_uv"], uv.mean(axis=2).mean(axis=0)
        ),
        "trial_mean_max_difference_uv": max_difference(
            seen["trial_mean_uv"], uv.mean(axis=2).mean(axis=1)
        ),
        "largest_abs_difference_uv": abs(seen["largest_abs_uv"] - float(np.abs(uv).max())),
    }


def check_metadata(seen: dict, table) -> dict:
    columns = {c["name"]: c for c in seen["columns"]}
    numeric = [n for n in table.columns if table[n].dtype.kind in "fiub"]
    return {
        "columns_match": sorted(columns) == sorted(table.columns),
        "rows_match": all(c["rows"] == len(table) for c in columns.values()),
        "gaps_match": all(columns[n]["gaps"] == int(table[n].isna().sum()) for n in numeric),
        "numeric_columns": len(numeric),
        "struct2table_available": seen["struct2table_available"],
    }


def check_eeglab(seen: dict, epochs: mne.BaseEpochs, uv: np.ndarray, resaved: Path) -> dict:
    back = mne.read_epochs_eeglab(resaved, verbose="ERROR")
    pulse_sample = int(np.argmin(np.abs(epochs.times)))
    return {
        "shape_match": [seen["trials"], seen["nbchan"], seen["pnts"]] == list(uv.shape),
        "events": seen["events"],
        "one_event_per_epoch": seen["event_epochs"] == list(range(1, len(epochs) + 1)),
        "events_at_time_zero": bool(np.allclose(seen["event_positions"], pulse_sample)),
        "channels_match": seen["labels"] == epochs.ch_names,
        "sampling_rate_match": seen["srate"] == epochs.info["sfreq"],
        "time_range_match": bool(
            np.isclose(seen["xmin"], epochs.times[0]) and np.isclose(seen["xmax"], epochs.times[-1])
        ),
        "channel_mean_max_difference_uv": max_difference(
            seen["channel_mean_uv"], uv.mean(axis=2).mean(axis=0)
        ),
        "resaved_max_difference_uv": float(np.abs(back.get_data() * 1e6 - uv).max()),
        "resaved_channels_match": back.ch_names == epochs.ch_names,
    }


def main() -> None:
    ds = Dataset()
    epochs = ds.epochs_around_pulses("sub-001", "parietal", baseline=(-0.1, -0.01))
    uv = epochs.get_data() * 1e6
    table = ds.metadata()

    folder = derivatives_dir(ds.root) / "export"
    folder.mkdir(parents=True, exist_ok=True)
    export_epochs_mat(epochs, folder / "sub-001_parietal_epochs.mat")
    export_epochs_set(epochs, folder / "sub-001_parietal_epochs.set")
    export_metadata(table, folder / "metadata.mat")

    report_path = folder / "octave_report.json"
    report_path.unlink(missing_ok=True)
    finished = run_octave(folder, report_path)
    if not report_path.exists():
        raise SystemExit(f"Octave wrote no report:\n{finished.stdout}\n{finished.stderr}")
    seen = json.loads(report_path.read_text(encoding="utf-8"))

    result: dict = {
        "runtime": seen["runtime"],
        "verified_in_matlab": False,
        "eeglab": Path(os.environ["EEGLAB_PATH"]).name,
        "octave_exit_code": finished.returncode,
        "steps_ok": {name: seen[name]["ok"] for name in ("mat", "metadata", "eeglab")},
        "errors": {n: seen[n]["error"] for n in ("mat", "metadata", "eeglab") if not seen[n]["ok"]},
    }
    if seen["mat"]["ok"]:
        result["mat"] = check_mat(seen["mat"], epochs, uv)
    if seen["metadata"]["ok"]:
        result["metadata"] = check_metadata(seen["metadata"], table)
    if seen["eeglab"]["ok"]:
        result["eeglab_load"] = check_eeglab(
            seen["eeglab"], epochs, uv, folder / "resaved_by_eeglab.set"
        )
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
