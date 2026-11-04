"""Make a de-identified copy of a dataset. The source is never modified.

This removes specific identifying fields from headers and sidecars, and shifts dates. It does not
make a dataset anonymous, and it is not a certification of HIPAA compliance. See docs/privacy.md for
what it covers and what it leaves. The log records what changed, never the removed values.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import re
import secrets
import shutil
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.io import loadmat, savemat

from tmseeg_access.download import compute_hash

LOG_NAME = "deidentification_log.json"
SIDECAR_FIELDS = (
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "DeviceSerialNumber",
    "StationName",
    "SoftwareVersions",
)
HEADER_FIELDS = ("comments", "history", "filepath", "subject", "group", "session", "condition")
HEAD_GEOMETRY = ("_electrodes.tsv", "_coordsystem.json")
_SUSPECT = re.compile(
    r"(?:[A-Za-z]:[\\/])"  # Windows drive path
    r"|(?:/(?:Users|home|Volumes|fs\d*|mnt|data|media)\b)"  # Unix path
    r"|(?:[\w.+-]+@[\w-]+\.[\w.-]+)"  # email address
    r"|(?:\b(?:19|20)\d{2}-\d{2}-\d{2}\b)",  # date
)
_MAX_SHIFT_DAYS = 365


def date_offset(subject: str, key: bytes) -> timedelta:
    """A per-subject shift of 30 to 365 days into the past. The same key gives the same shift."""
    digest = hmac.new(key, subject.encode(), hashlib.sha256).digest()
    return timedelta(days=-(30 + int.from_bytes(digest[:4], "big") % (_MAX_SHIFT_DAYS - 29)))


def shift_datetime(value: str, offset: timedelta) -> str:
    """Shift a BIDS date-time. Anything else, including ``n/a``, passes through unchanged."""
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return value
    return (moment + offset).isoformat()


def strip_sidecar(path: Path, target: Path, counts: Counter) -> None:
    """Copy a JSON sidecar without its identifying fields."""
    content = json.loads(path.read_text(encoding="utf-8"))
    for field in SIDECAR_FIELDS:
        if field in content:
            del content[field]
            counts[f"sidecar.{field}"] += 1
    target.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")


def shift_scans(path: Path, target: Path, offset: timedelta, counts: Counter) -> None:
    """Copy a scans table with its acquisition times shifted."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    fields = list(rows[0].keys()) if rows else []
    for row in rows:
        if "acq_time" in row:
            shifted = shift_datetime(row["acq_time"], offset)
            if shifted != row["acq_time"]:
                counts["scans.acq_time"] += 1
            row["acq_time"] = shifted
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _walk_strings(value):
    """Yield every string inside a loaded MAT structure."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, np.ndarray):
        if value.dtype.names:
            for item in value.flat:
                for name in value.dtype.names:
                    yield from _walk_strings(item[name])
        elif value.dtype.kind in {"U", "S"}:
            for item in value.flat:
                yield str(item)
        elif value.dtype == object:
            for item in value.flat:
                yield from _walk_strings(item)
    elif isinstance(value, np.void) and value.dtype.names:
        for name in value.dtype.names:
            yield from _walk_strings(value[name])


def _scrub(value, counts: Counter, label: str):
    """Blank strings that look like paths, addresses or dates, anywhere in a structure."""
    if isinstance(value, np.ndarray):
        if value.dtype.names:
            for index in np.ndindex(value.shape):
                for name in value.dtype.names:
                    value[index][name] = _scrub(value[index][name], counts, f"{label}.{name}")
            return value
        if value.dtype.kind in {"U", "S"}:
            if any(_SUSPECT.search(str(item)) for item in value.flat):
                counts[f"header.{label}"] += 1
                return np.array([""])
            return value
        if value.dtype == object:
            for index in np.ndindex(value.shape):
                value[index] = _scrub(value[index], counts, label)
    return value


def strip_set_header(path: Path, target: Path, counts: Counter) -> None:
    """Copy an EEGLAB ``.set`` file with free-text fields blanked and stray paths removed."""
    content = {k: v for k, v in loadmat(path).items() if not k.startswith("__")}
    for field in HEADER_FIELDS:
        if field in content and any(text.strip() for text in _walk_strings(content[field])):
            content[field] = np.array([""])
            counts[f"header.{field}"] += 1
    for field, value in content.items():
        content[field] = _scrub(value, counts, field)
    savemat(target, content, appendmat=False, oned_as="column")


def scan_set_header(path: Path) -> list[str]:
    """Return the names of top-level fields that still hold suspicious text."""
    content = {k: v for k, v in loadmat(path).items() if not k.startswith("__")}
    return sorted(
        field
        for field, value in content.items()
        if any(_SUSPECT.search(text) for text in _walk_strings(value))
    )


def scan_text_file(path: Path) -> bool:
    """True if a text file contains something that looks like a path, address or date."""
    return bool(_SUSPECT.search(path.read_text(encoding="utf-8", errors="ignore")))


def _check_locations(source: Path, output: Path) -> None:
    source, output = source.resolve(), output.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Output must be outside the source dataset, and not contain it.")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output folder is not empty: {output}")


def _wanted(relative: Path, subjects: set[str] | None) -> bool:
    if relative.parts[0] == "derivatives" or relative.parts[0].startswith(".datalad"):
        return False
    is_subject_path = relative.parts[0].startswith("sub-")
    return not is_subject_path or subjects is None or relative.parts[0] in subjects


def _filter_participants(path: Path, target: Path, subjects: set[str] | None, drop: Sequence[str]):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    kept = [c for c in rows[0] if c not in drop]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=kept, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(r for r in rows if subjects is None or r["participant_id"] in subjects)


def deidentify(
    source: Path,
    output: Path,
    subjects: Sequence[str] | None = None,
    key: bytes | None = None,
    drop_participant_columns: Sequence[str] = (),
    drop_head_geometry: bool = False,
    include_signal: bool = True,
) -> dict:
    """Write a de-identified copy of ``source`` to ``output`` and return what was done.

    ``key`` makes date shifts repeatable. Without one, a random key is used and discarded, so the
    shifts cannot be reversed.
    """
    source, output = Path(source), Path(output)
    _check_locations(source, output)
    key_note = "supplied by caller, not stored" if key else "random, discarded"
    key = key or secrets.token_bytes(32)
    chosen = set(subjects) if subjects is not None else None
    counts: Counter = Counter()
    files: Counter = Counter()
    signal_pairs: list[tuple[Path, Path]] = []
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        relative = path.relative_to(source)
        if not _wanted(relative, chosen):
            continue
        name = path.name
        if drop_head_geometry and name.endswith(HEAD_GEOMETRY):
            counts["head_geometry.removed_files"] += 1
            continue
        if name.endswith(".fdt") and not include_signal:
            continue
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if name == "participants.tsv":
            _filter_participants(path, target, chosen, drop_participant_columns)
            counts["participants.columns_dropped"] = len(drop_participant_columns)
        elif name.endswith("_scans.tsv"):
            shift_scans(path, target, date_offset(relative.parts[0], key), counts)
        elif name.endswith(".set"):
            strip_set_header(path, target, counts)
        elif name.endswith(".json"):
            strip_sidecar(path, target, counts)
        else:
            shutil.copyfile(path, target)
            if name.endswith(".fdt"):
                signal_pairs.append((path, target))
        files[path.suffix or path.name] += 1

    changed = [
        str(a.relative_to(source))
        for a, b in signal_pairs
        if compute_hash(a, "sha256") != compute_hash(b, "sha256")
    ]
    residual_headers = {
        str(p.relative_to(output)): scan_set_header(p) for p in output.rglob("*.set")
    }
    residual_text = [
        str(p.relative_to(output))
        for pattern in ("*.json", "*.tsv")
        for p in output.rglob(pattern)
        if scan_text_file(p)
    ]
    log = {
        "certification": "None. This is not a certification of HIPAA compliance.",
        "files_written": dict(files),
        "fields_changed": dict(sorted(counts.items())),
        "signal_files_identical_to_source": len(signal_pairs) - len(changed),
        "signal_files_changed": changed,
        "headers_with_suspicious_text_after": {k: v for k, v in residual_headers.items() if v},
        "text_files_with_suspicious_text_after": sorted(residual_text),
        "date_shift_key": key_note,
    }
    (output / LOG_NAME).write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    return log
