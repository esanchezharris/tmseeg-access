"""Counts about the project itself, cited in the docs. Writes results/project_facts.json."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

from tmseeg_access.report import RULE_MEANINGS

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results" / "project_facts.json"


def collected(*extra: str) -> int:
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sum(int(n) for n in re.findall(r"^tests\S*: (\d+)\s*$", done.stdout, re.MULTILINE))


def main() -> None:
    issues = pd.read_csv(ROOT / "results" / "issues.csv")
    source = sorted((ROOT / "src").rglob("*.py"))
    tests = sorted((ROOT / "tests").glob("*.py"))
    total = collected()
    real = collected("-m", "realdata")
    facts = {
        "rules_defined": len(RULE_MEANINGS),
        "rules_that_fired_on_real_data": int(issues["rule"].nunique()),
        "issues": len(issues),
        "tests_total": total,
        "tests_needing_real_data": real,
        "tests_synthetic": total - real,
        "package_modules": len(source),
        "package_lines": sum(len(p.read_text(encoding="utf-8").splitlines()) for p in source),
        "test_lines": sum(len(p.read_text(encoding="utf-8").splitlines()) for p in tests),
    }
    OUTPUT.write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(facts, indent=2))


if __name__ == "__main__":
    main()
