"""Ignored files bind by metadata: a dependency tree must not be read to fingerprint."""

import os
import subprocess

import pytest
from plan_confirmation import repository_fingerprint


def repo_with_ignored(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".gitignore").write_text("deps/\n")
    (repo / "tracked.txt").write_text("tracked\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"],
        cwd=repo,
        check=True,
    )
    (repo / "deps").mkdir()
    ignored = repo / "deps/package.js"
    ignored.write_text("original\n")
    return repo, ignored


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads mode-000 files")
def test_ignored_file_is_fingerprinted_without_opening_it(tmp_path, monkeypatch):
    repo, ignored = repo_with_ignored(tmp_path)
    ignored.chmod(0)
    monkeypatch.chdir(repo)
    try:
        assert repository_fingerprint(repo / "plan.md")["identity"]
    finally:
        ignored.chmod(0o644)


def test_ignored_rewrite_moves_the_fingerprint(tmp_path, monkeypatch):
    repo, ignored = repo_with_ignored(tmp_path)
    monkeypatch.chdir(repo)
    before = repository_fingerprint(repo / "plan.md")["identity"]
    stamp = ignored.stat().st_mtime_ns
    ignored.write_text("changed!\n")
    os.utime(ignored, ns=(stamp + 1_000_000_000, stamp + 1_000_000_000))
    assert repository_fingerprint(repo / "plan.md")["identity"] != before
