"""Fetch a pinned OpenNeuro snapshot, verifying every file against the release's own hashes.

Annexed files (the large binaries) carry a git-annex key holding their SHA-256. Other files are
identified by their git blob SHA-1. URLs are version-pinned, so a snapshot cannot change underneath
us. Files are written to ``<name>.part`` beside the target and renamed only after verification, so
a partial or corrupt file never appears under its real name.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from tmseeg_access.config import derivatives_dir

GRAPHQL_URL = "https://openneuro.org/crn/graphql"
USER_AGENT = "tmseeg-access"
CHUNK = 1024 * 1024
_ANNEX_KEY = re.compile(r"^(?P<backend>SHA256E?|MD5E?)-s(?P<size>\d+)--(?P<digest>[0-9a-f]+)")
_QUERY = """query($id: ID!, $tag: String!) {
  snapshot(datasetId: $id, tag: $tag) {
    files(recursive: true) { id filename directory size annexed urls }
  }
}"""


class VerificationError(RuntimeError):
    """A file's size or hash does not match the release."""


@dataclass(frozen=True)
class RemoteFile:
    path: str
    size: int
    hash_algo: str
    hash_value: str
    url: str


def parse_file_entry(entry: dict) -> RemoteFile:
    """Turn one OpenNeuro file record into a RemoteFile, working out how it can be verified."""
    path = entry["filename"]
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or ":" in path:
        raise ValueError(f"Unsafe path in manifest: {path!r}")
    if entry["annexed"]:
        match = _ANNEX_KEY.match(entry["id"])
        if match is None:
            raise ValueError(f"Unrecognised annex key for {path}: {entry['id']}")
        algo = "sha256" if match["backend"].startswith("SHA256") else "md5"
        digest = match["digest"]
    else:
        algo, digest = "git-blob-sha1", entry["id"]
    return RemoteFile(path, int(entry["size"]), algo, digest, entry["urls"][0])


def fetch_manifest(dataset: str, tag: str, timeout: int = 280) -> list[RemoteFile]:
    """Ask OpenNeuro for every file in one snapshot."""
    body = json.dumps({"query": _QUERY, "variables": {"id": dataset, "tag": tag}}).encode()
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(f"OpenNeuro returned errors: {payload['errors']}")
    entries = payload["data"]["snapshot"]["files"]
    return [parse_file_entry(e) for e in entries if not e["directory"]]


def manifest_path(root: Path, tag: str) -> Path:
    return derivatives_dir(root) / f"manifest-{tag}.json"


def save_manifest(files: Sequence[RemoteFile], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(f) for f in files], indent=0), encoding="utf-8")


def load_manifest(path: Path) -> list[RemoteFile]:
    return [RemoteFile(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


def select_files(
    files: Iterable[RemoteFile],
    tier: str,
    subjects: Sequence[str] | None = None,
    tasks: Sequence[str] | None = None,
) -> list[RemoteFile]:
    """Pick files by tier: ``metadata`` (text), ``headers`` (.set), or ``signal`` (.set + .fdt)."""
    suffixes = {"headers": {".set"}, "signal": {".set", ".fdt"}}
    if tier != "metadata" and tier not in suffixes:
        raise ValueError(f"Unknown tier {tier!r}")
    chosen = []
    for item in files:
        name = PurePosixPath(item.path)
        if item.path.startswith(".datalad/"):
            continue
        if tier == "metadata":
            if name.suffix not in {".set", ".fdt"}:
                chosen.append(item)
            continue
        if name.suffix not in suffixes[tier]:
            continue
        if subjects is not None and name.parts[0] not in subjects:
            continue
        if tasks is not None and not any(f"_task-{t}" in name.name for t in tasks):
            continue
        chosen.append(item)
    return chosen


def compute_hash(path: Path, algo: str) -> str:
    """Hash a file in chunks, including the header git prepends for a blob hash."""
    if algo == "git-blob-sha1":
        digest = hashlib.sha1()  # git's identifier, not a security control
        digest.update(b"blob %d\x00" % path.stat().st_size)
    else:
        digest = hashlib.new(algo)
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, remote: RemoteFile) -> None:
    """Raise VerificationError unless ``path`` matches the release exactly."""
    size = path.stat().st_size
    if size != remote.size:
        raise VerificationError(f"{remote.path}: size {size}, expected {remote.size}")
    actual = compute_hash(path, remote.hash_algo)
    if actual != remote.hash_value:
        raise VerificationError(
            f"{remote.path}: {remote.hash_algo} {actual}, expected {remote.hash_value}"
        )


def _stream(remote: RemoteFile, part: Path, timeout: int) -> None:
    offset = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(remote.url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        resumed = getattr(response, "status", None) == 206
        with part.open("ab" if resumed else "wb") as out:
            while chunk := response.read(CHUNK):
                out.write(chunk)


def download_one(remote: RemoteFile, root: Path, retries: int = 3, timeout: int = 120) -> str:
    """Fetch and verify one file. Returns ``present`` or ``downloaded``."""
    target = root / remote.path
    if target.exists():
        verify_file(target, remote)
        return "present"
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    for attempt in range(1, retries + 1):
        try:
            _stream(remote, part, timeout)
            verify_file(part, remote)
            part.replace(target)
            return "downloaded"
        except VerificationError:
            part.unlink(missing_ok=True)
            if attempt == retries:
                raise
        except OSError:  # includes URLError, timeouts and dropped connections
            if attempt == retries:
                raise
            time.sleep(attempt)
    raise AssertionError("unreachable")


def download_files(files: Sequence[RemoteFile], root: Path, workers: int = 8) -> dict:
    """Fetch many files concurrently. Any failure is reported, never hidden."""
    counts = {"downloaded": 0, "present": 0}
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(download_one, f, root): f for f in files}
        for job in as_completed(jobs):
            try:
                counts[job.result()] += 1
            except (OSError, VerificationError) as exc:
                failures.append({"path": jobs[job].path, "error": str(exc)})
    return {
        "requested": len(files),
        "bytes": sum(f.size for f in files),
        **counts,
        "failed": len(failures),
        "failures": failures,
    }
