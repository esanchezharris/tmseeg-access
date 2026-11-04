"""What the .set headers say about each TMS run's history. Writes results/header_provenance.json.

Answers: do site labels match the original filenames, which runs carry a record of artifact removal,
and do the runs without one form a batch? It also counts private-looking text, without storing it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from pymatreader import read_mat

from tmseeg_access.checks import load_protocol
from tmseeg_access.dataset import Dataset

OUTPUT = Path(__file__).resolve().parents[1] / "results" / "header_provenance.json"


def main() -> None:
    ds = Dataset()
    codes = load_protocol()["source_site_codes"]
    rows = []
    for row in ds.recordings(task="tmseeg").itertuples(index=False):
        stem = f"{row.subject}_task-tmseeg_acq-{row.acquisition}"
        eeg_dir = ds.root / row.subject / "eeg"
        fields = ["comments", "tmscut", "filepath", "chaninfo"]
        header = read_mat(str(eeg_dir / f"{stem}_eeg.set"), variable_names=fields)
        comments = str(header.get("comments", ""))
        record = header.get("tmscut")
        record = record if isinstance(record, dict) and record else None
        match = re.search(r"SP_([A-Za-z0-9]+)", comments)
        names = pd.read_csv(eeg_dir / f"{stem}_channels.tsv", sep="\t")["name"]
        chaninfo = header.get("chaninfo")
        rows.append(
            {
                "subject": row.subject,
                "site": row.acquisition,
                "site_code": match[1].upper() if match else None,
                "has_artifact_record": record is not None,
                "cut_ms": None if record is None else np.asarray(record["cutTimesTMS"]).tolist(),
                "record_rate_hz": None if record is None else float(record["srate"]),
                "record_interpolated": None if record is None else record["interpolated"],
                "mixed_case_names": bool((names != names.str.upper()).any()),
                "has_trigger_channel": bool((names == "TRIGGER").any()),
                "source_path_in_comments": "/" in comments,
                "path_in_filepath": "/" in str(header.get("filepath", "")),
                "path_in_chaninfo": isinstance(chaninfo, dict)
                and "/" in str(chaninfo.get("filename", "")),
            }
        )
    table = pd.DataFrame(rows)
    with_code = table[table["site_code"].notna()]
    agree = with_code["site_code"].map(codes) == with_code["site"]
    without = table[~table["has_artifact_record"]]
    result = {
        "runs": len(table),
        "site_labels": {
            "runs_with_a_site_code": len(with_code),
            "agree_with_label": int(agree.sum()),
            "control_runs_coded_SHAM": int((with_code["site_code"] == "SHAM").sum()),
        },
        "artifact_record": {
            "runs_with_record": int(table["has_artifact_record"].sum()),
            "cut_windows_ms": table["cut_ms"].dropna().astype(str).value_counts().to_dict(),
            "record_rates_hz": table["record_rate_hz"].dropna().value_counts().to_dict(),
            "interpolated_values": table["record_interpolated"].dropna().value_counts().to_dict(),
        },
        "batch_without_record": {
            "runs": len(without),
            "subjects": sorted(without["subject"].unique().tolist()),
            "runs_with_mixed_case_names": int(without["mixed_case_names"].sum()),
            "runs_with_trigger_channel": int(without["has_trigger_channel"].sum()),
            "mixed_case_runs_in_whole_dataset": int(table["mixed_case_names"].sum()),
            "runs_with_site_code": int(without["site_code"].notna().sum()),
        },
        "absolute_paths_left_in_headers": {
            "comments": int(table["source_path_in_comments"].sum()),
            "filepath": int(table["path_in_filepath"].sum()),
            "chaninfo": int(table["path_in_chaninfo"].sum()),
        },
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
