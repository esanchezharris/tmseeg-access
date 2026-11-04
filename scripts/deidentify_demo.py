"""Run de-identification on one real subject and compare. Writes results/deidentify_demo.json."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from tmseeg_access.dataset import Dataset
from tmseeg_access.deidentify import LOG_NAME, deidentify, scan_set_header

OUTPUT = Path(__file__).resolve().parents[1] / "results" / "deidentify_demo.json"
SUBJECT = "sub-001"
SITES = ["control", "parietal", "prefrontal", "premotor"]


def main() -> None:
    source = Dataset()
    target = source.root.parent / f"{source.root.name}-deid-demo"
    if (target / LOG_NAME).exists():  # only ever removes an earlier demo
        shutil.rmtree(target)
    log = deidentify(source.root, target, subjects=[SUBJECT])
    copy = Dataset(target)
    identical = {
        site: bool(
            np.array_equal(
                source.epochs_around_pulses(SUBJECT, site).get_data(),
                copy.epochs_around_pulses(SUBJECT, site).get_data(),
            )
        )
        for site in SITES
    }
    eeg = source.root / SUBJECT / "eeg"
    before = {p.name: scan_set_header(p) for p in eeg.glob("*task-tmseeg*.set")}
    result = {
        "subject": SUBJECT,
        "log": log,
        "epochs_identical_to_source": identical,
        "header_fields_with_suspicious_text_before": sorted(
            {f for v in before.values() for f in v}
        ),
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "log"}, indent=2))


if __name__ == "__main__":
    main()
