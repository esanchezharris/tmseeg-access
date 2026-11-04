"""The shared record every check produces, and the protocol values checks compare against."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from importlib import resources

import pandas as pd

SEVERITIES = ("error", "warning", "info")
COLUMNS = [
    "rule",
    "severity",
    "subject",
    "recording_id",
    "where",
    "observed",
    "expected",
    "suggested_action",
]


@dataclass(frozen=True)
class Issue:
    """One finding: what was observed, where, under which rule, and what to do about it.

    Checks only ever report. Fixing or excluding data is the analyst's decision.
    """

    rule: str
    severity: str
    where: str
    observed: str
    expected: str
    suggested_action: str
    subject: str | None = None
    recording_id: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"Unknown severity: {self.severity}")


def issues_frame(issues: list[Issue]) -> pd.DataFrame:
    """Turn issues into a table with stable columns, even when there are none."""
    return pd.DataFrame([asdict(i) for i in issues], columns=COLUMNS)


def load_protocol(name: str = "ds008037") -> dict:
    """Load a protocol file shipped with the package."""
    text = resources.files("tmseeg_access.protocols").joinpath(f"{name}.toml").read_text("utf-8")
    return tomllib.loads(text)
