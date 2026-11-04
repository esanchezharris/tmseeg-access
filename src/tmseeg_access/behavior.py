"""One-line behavioural summaries per subject, so they can be joined to recordings.

Each summary is a plain statistic of a column in that task's ``*_beh.tsv``. These are convenience
values for filtering and joining. They are not validated scores: for analysis, read the trial-level
table with ``Dataset.behavior(task)``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# output column -> (task, source column, statistic)
SUMMARIES: dict[str, tuple[str, str, str]] = {
    "nback_accuracy": ("nback", "correctness", "mean"),
    "gng_accuracy": ("gng", "correct", "mean"),
    "smt_accuracy": ("smt", "accuracy", "mean"),
    "ort_mean_abs_error_deg": ("ort", "abs_error_deg", "mean"),
    "sbs_total_correct": ("sbs", "total_correct_sum", "max"),
}


def read_beh(root: Path, subject: str, task: str) -> pd.DataFrame | None:
    """Read one subject's trial table, or None if this subject has no file for the task."""
    path = root / subject / "beh" / f"{subject}_task-{task}_beh.tsv"
    if not path.exists():
        return None
    return pd.read_csv(path, sep="\t", na_values=["n/a"], low_memory=False)


def summarize_subject(root: Path, subject: str) -> dict[str, float]:
    """Compute every summary for a subject. A missing file or column gives NaN."""
    tables: dict[str, pd.DataFrame | None] = {}
    row: dict[str, float] = {}
    for name, (task, column, statistic) in SUMMARIES.items():
        table = tables.setdefault(task, read_beh(root, subject, task))
        if table is None or column not in table:
            row[name] = np.nan
            continue
        values = pd.to_numeric(table[column], errors="coerce").dropna()
        row[name] = float(getattr(values, statistic)()) if len(values) else np.nan
    return row
