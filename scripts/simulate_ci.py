"""Run the CI steps in a fresh clone with no dataset. Writes results/ci_simulation.json.

This approximates .github/workflows/tests.yml on the local machine. It is not a run on GitHub: the
operating system differs, and nothing is pushed anywhere.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results" / "ci_simulation.json"
STEPS = {
    "install": ["uv", "sync", "--frozen"],
    "lint": ["uv", "run", "ruff", "check", "src", "tests", "scripts", "examples"],
    "format": ["uv", "run", "ruff", "format", "--check", "src", "tests", "scripts", "examples"],
    "tests": ["uv", "run", "pytest"],
}


def main() -> None:
    environment = {k: v for k, v in os.environ.items() if k != "TMSEEG_DATA_ROOT"}
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    folder = Path(tempfile.mkdtemp(prefix="tmseeg-ci-"))
    clone = folder / "repo"
    subprocess.run(["git", "clone", "-q", str(ROOT), str(clone)], check=True)
    steps = {}
    started = time.perf_counter()
    summary = ""
    for name, command in STEPS.items():
        begin = time.perf_counter()
        done = subprocess.run(
            command, cwd=clone, env=environment, capture_output=True, text=True, check=False
        )
        steps[name] = {
            "exit_code": done.returncode,
            "seconds": round(time.perf_counter() - begin, 1),
        }
        if name == "tests":
            summary = done.stdout.strip().splitlines()[-1]
    result = {
        "commit": commit,
        "platform": platform.platform(),
        "is_a_github_run": False,
        "steps": steps,
        "total_seconds": round(time.perf_counter() - started, 1),
        "pytest_summary": summary,
        "passed": int(re.search(r"(\d+) passed", summary)[1]),
        "skipped": int(m[1]) if (m := re.search(r"(\d+) skipped", summary)) else 0,
    }
    shutil.rmtree(folder, ignore_errors=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
