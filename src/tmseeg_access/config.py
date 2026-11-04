"""Where the dataset lives. Nothing here assumes a drive or an operating system."""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "TMSEEG_DATA_ROOT"
DATASET = "ds008037"
TAG = "1.0.1"
DERIVATIVES = Path("derivatives") / "tmseeg-access"


def resolve_data_root(path: str | os.PathLike | None = None) -> Path:
    """Return the dataset root from an explicit path, else from ``TMSEEG_DATA_ROOT``."""
    value = path if path is not None else os.environ.get(ENV_VAR)
    if value is None:
        raise ValueError(f"No dataset path given. Pass one, or set {ENV_VAR}.")
    return Path(value).expanduser()


def derivatives_dir(root: Path) -> Path:
    """Folder for files this package generates, kept apart from the source data."""
    return root / DERIVATIVES
