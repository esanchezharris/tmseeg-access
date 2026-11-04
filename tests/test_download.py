"""Downloader tests. All files here are synthetic bytes written by the tests."""

from __future__ import annotations

import hashlib

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
