"""Regenerate the catalog, checks, report, evidence files and generated docs, in dependency order.

Needs TMSEEG_DATA_ROOT and the downloaded data. Run it whenever a check changes, so that results and
docs cannot drift apart. The Octave and EEGLAB step runs only if OCTAVE_CLI and EEGLAB_PATH are set.

Not regenerated here: the CI simulation (needs committed code), download verification logs and drive
status (records of past events), and published_values.json (hand-written quotes).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
TOOL = [sys.executable, "-m", "tmseeg_access.cli"]
SCRIPT = [sys.executable]
STEPS = [
    ("catalog", [*TOOL, "catalog"], "catalog_build.json"),
    ("checks", [*TOOL, "check"], "check_output.txt"),
    ("report", [*TOOL, "report"], None),
    ("pulse evidence", [*SCRIPT, "scripts/pulse_identification.py"], None),
    ("dataset facts", [*SCRIPT, "scripts/dataset_facts.py"], None),
    ("header evidence", [*SCRIPT, "scripts/header_provenance.py"], None),
    ("hand checks", [*SCRIPT, "scripts/hand_checks.py"], None),
    ("de-identification demo", [*SCRIPT, "scripts/deidentify_demo.py"], None),
    ("MATLAB round trip", [*SCRIPT, "scripts/matlab_roundtrip.py"], None),
    ("Octave and EEGLAB round trip", [*SCRIPT, "scripts/octave_roundtrip.py"], None),
    ("catalog query docs", [*SCRIPT, "scripts/catalog_queries.py"], None),
    ("API docs", [*SCRIPT, "scripts/build_api_docs.py"], None),
    ("quickstart", [*SCRIPT, "examples/quickstart.py"], "quickstart_output.txt"),
    ("tutorial", [*SCRIPT, "scripts/build_tutorial.py"], None),
    ("project facts", [*SCRIPT, "scripts/project_facts.py"], None),
    ("all tests with real data", [*SCRIPT, "-m", "pytest"], "pytest_real_data.txt"),
]


def main() -> None:
    if "TMSEEG_DATA_ROOT" not in os.environ:
        sys.exit("Set TMSEEG_DATA_ROOT first.")
    has_octave = {"OCTAVE_CLI", "EEGLAB_PATH"} <= set(os.environ)
    for name, command, capture in STEPS:
        if name.startswith("Octave") and not has_octave:
            print(f"{name}: skipped, OCTAVE_CLI and EEGLAB_PATH are not set")
            continue
        started = time.perf_counter()
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        print(f"{name}: exit {done.returncode}, {time.perf_counter() - started:.1f} s")
        if capture:
            (RESULTS / capture).write_text(done.stdout, encoding="utf-8")
        if done.returncode:
            sys.exit(done.stdout[-2000:] + done.stderr[-2000:])


if __name__ == "__main__":
    main()
