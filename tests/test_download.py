"""Downloader tests. All files here are synthetic bytes written by the tests."""

from __future__ import annotations

import hashlib
import urllib.error

import pytest

from tmseeg_access.download import (
    RemoteFile,
    VerificationError,
    compute_hash,
    download_files,
    download_one,
    parse_file_entry,
    select_files,
)


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def remote_for(tmp_path, name: str, data: bytes, algo: str = "sha256") -> RemoteFile:
    source = tmp_path / "source" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest() if algo == "sha256" else blob_id(data)
    return RemoteFile(name, len(data), algo, digest, source.as_uri())


def test_annexed_entry_uses_sha256_from_key():
    digest = "ab" * 32
    entry = {
        "filename": "sub-001/eeg/a.fdt",
        "id": f"SHA256E-s12--{digest}.fdt",
        "size": 12,
        "annexed": True,
        "urls": ["https://example.test/a"],
    }
    parsed = parse_file_entry(entry)
    assert (parsed.hash_algo, parsed.hash_value) == ("sha256", digest)


def test_plain_entry_uses_git_blob_hash():
    entry = {"filename": "README", "id": "ab" * 20, "size": 3, "annexed": False, "urls": ["u"]}
    assert parse_file_entry(entry).hash_algo == "git-blob-sha1"


@pytest.mark.parametrize("bad", ["../evil.txt", "/etc/passwd", "C:/evil.txt", "a/../../b"])
def test_unsafe_paths_are_rejected(bad):
    entry = {"filename": bad, "id": "ab" * 20, "size": 3, "annexed": False, "urls": ["u"]}
    with pytest.raises(ValueError, match="Unsafe path"):
        parse_file_entry(entry)


def test_git_blob_hash_matches_git(tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(b"hello\n")
    # Value printed by: git hash-object on a file containing "hello\n"
    assert compute_hash(path, "git-blob-sha1") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_download_verifies_and_leaves_no_part_file(tmp_path):
    remote = remote_for(tmp_path, "sub-001/a.fdt", b"synthetic bytes")
    root = tmp_path / "root"
    assert download_one(remote, root) == "downloaded"
    assert (root / "sub-001/a.fdt").read_bytes() == b"synthetic bytes"
    assert not (root / "sub-001/a.fdt.part").exists()
    assert download_one(remote, root) == "present"


def test_corrupt_download_never_appears_under_its_real_name(tmp_path):
    good = remote_for(tmp_path, "a.fdt", b"synthetic bytes")
    bad = RemoteFile(good.path, good.size, "sha256", "0" * 64, good.url)
    root = tmp_path / "root"
    with pytest.raises(VerificationError):
        download_one(bad, root, retries=2)
    assert not (root / "a.fdt").exists()
    assert not (root / "a.fdt.part").exists()


def test_corrupted_local_file_is_caught_on_rerun(tmp_path):
    remote = remote_for(tmp_path, "a.tsv", b"onset\n1\n", algo="git-blob-sha1")
    root = tmp_path / "root"
    download_one(remote, root)
    (root / "a.tsv").write_bytes(b"onset\n2\n")
    with pytest.raises(VerificationError):
        download_one(remote, root)


class FakeResponse:
    """A stand-in for an HTTP response, built from synthetic bytes."""

    def __init__(self, body: bytes, status: int = 200):
        self.body, self.status, self.position = body, status, 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size: int = -1) -> bytes:
        chunk = self.body[self.position : self.position + size]
        self.position += len(chunk)
        return chunk


def remote_with(data: bytes, url: str = "https://example.test/a") -> RemoteFile:
    return RemoteFile("a.fdt", len(data), "sha256", hashlib.sha256(data).hexdigest(), url)


def serve(monkeypatch, *responses):
    """Make urlopen return these in turn. An exception in the list is raised instead."""
    queue, seen = list(responses), []

    def fake(request, timeout=None):
        seen.append(request.headers.get("Range"))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("urllib.request.urlopen", fake)
    monkeypatch.setattr("time.sleep", lambda _: None)
    return seen


def test_resume_asks_for_the_rest_and_appends(tmp_path, monkeypatch):
    data = b"0123456789"
    (tmp_path / "a.fdt.part").write_bytes(data[:4])
    seen = serve(monkeypatch, FakeResponse(data[4:], status=206))
    assert download_one(remote_with(data), tmp_path) == "downloaded"
    assert (tmp_path / "a.fdt").read_bytes() == data
    assert seen == ["bytes=4-"]


def test_server_ignoring_the_range_restarts_cleanly(tmp_path, monkeypatch):
    data = b"0123456789"
    (tmp_path / "a.fdt.part").write_bytes(data[:4])
    serve(monkeypatch, FakeResponse(data, status=200))
    download_one(remote_with(data), tmp_path)
    assert (tmp_path / "a.fdt").read_bytes() == data


def test_complete_partial_file_needs_no_request(tmp_path, monkeypatch):
    data = b"0123456789"
    (tmp_path / "a.fdt.part").write_bytes(data)
    seen = serve(monkeypatch)
    assert download_one(remote_with(data), tmp_path) == "downloaded"
    assert seen == []


def test_dropped_connection_keeps_progress_and_resumes(tmp_path, monkeypatch):
    data = b"0123456789"
    seen = serve(monkeypatch, FakeResponse(data[:6]), FakeResponse(data[6:], status=206))
    assert download_one(remote_with(data), tmp_path) == "downloaded"
    assert (tmp_path / "a.fdt").read_bytes() == data
    assert seen == [None, "bytes=6-"]


def test_an_incomplete_file_is_never_accepted(tmp_path, monkeypatch):
    data = b"0123456789"
    serve(monkeypatch, *[FakeResponse(b"") for _ in range(3)])
    with pytest.raises(ConnectionError):
        download_one(remote_with(data), tmp_path)
    assert not (tmp_path / "a.fdt").exists()


def test_range_not_satisfiable_discards_the_partial_file(tmp_path, monkeypatch):
    data = b"0123456789"
    (tmp_path / "a.fdt.part").write_bytes(data[:4])
    refused = urllib.error.HTTPError("u", 416, "Range Not Satisfiable", None, None)
    seen = serve(monkeypatch, refused, FakeResponse(data))
    assert download_one(remote_with(data), tmp_path) == "downloaded"
    assert seen == ["bytes=4-", None]


def test_failures_are_reported_not_hidden(tmp_path):
    good = remote_for(tmp_path, "good.fdt", b"synthetic")
    bad = RemoteFile("bad.fdt", 9, "sha256", "0" * 64, good.url)
    summary = download_files([good, bad], tmp_path / "root", workers=2)
    assert (summary["downloaded"], summary["failed"]) == (1, 1)
    assert summary["failures"][0]["path"] == "bad.fdt"


def test_select_files_by_tier_subject_and_task():
    def f(path: str) -> RemoteFile:
        return RemoteFile(path, 1, "sha256", "x", "u")

    files = [
        f("participants.tsv"),
        f(".datalad/config"),
        f("sub-001/eeg/sub-001_task-tmseeg_acq-control_eeg.set"),
        f("sub-001/eeg/sub-001_task-tmseeg_acq-control_eeg.fdt"),
        f("sub-001/eeg/sub-001_task-rest_eeg.fdt"),
        f("sub-002/eeg/sub-002_task-tmseeg_acq-control_eeg.fdt"),
    ]
    assert [x.path for x in select_files(files, "metadata")] == ["participants.tsv"]
    assert len(select_files(files, "headers")) == 1
    picked = select_files(files, "signal", subjects=["sub-001"], tasks=["tmseeg"])
    assert [x.path.rsplit(".", 1)[1] for x in picked] == ["set", "fdt"]
