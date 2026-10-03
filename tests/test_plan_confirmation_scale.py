"""Plan confirmation stays bounded on a consumer with a large ignored dependency tree."""

import os
import subprocess

import pytest
from plan_confirmation import repository_fingerprint


def repo_with_ignored(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".gitignore").write_text("node_modules/\ndist/\n")
    (repo / "tracked.txt").write_text("tracked\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"],
        cwd=repo,
        check=True,
    )
    (repo / "node_modules").mkdir()
    ignored = repo / "node_modules/package.js"
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


def test_rebuilt_ignored_output_with_same_bytes_keeps_the_fingerprint(tmp_path, monkeypatch):
    repo, _ = repo_with_ignored(tmp_path)
    (repo / "dist").mkdir()
    built = repo / "dist/app.js"
    built.write_text("compiled\n")
    monkeypatch.chdir(repo)
    before = repository_fingerprint(repo / "plan.md")["identity"]
    built.unlink()
    built.write_text("compiled\n")
    stamp = built.stat().st_mtime_ns
    os.utime(built, ns=(stamp + 1_000_000_000, stamp + 1_000_000_000))
    assert repository_fingerprint(repo / "plan.md")["identity"] == before


def test_confirmation_prompt_carries_fingerprint_identity_not_components(tmp_path, monkeypatch):
    import plan_confirmation
    import plan_review
    import review

    fingerprint = {
        "repository": "/repo",
        "components": {"contents": [["6e6f64655f6d6f64756c6573", 33188, "0" * 64]] * 1000},
        "identity": "f" * 64,
    }
    context = {"fingerprint": fingerprint, "evidence": {"repository": fingerprint}}
    seen = {}

    def capture(*args, **kwargs):
        seen["prior"] = args[7]
        return 0, "confirm"

    monkeypatch.setattr(plan_confirmation, "preserve", lambda *_: tmp_path / "manifest.json")
    monkeypatch.setattr(plan_confirmation, "data_root", lambda: tmp_path)
    monkeypatch.setattr(plan_review, "incomplete_marker", lambda _: tmp_path / "marker.json")
    monkeypatch.setattr(review, "charter", lambda _: "charter")
    monkeypatch.setattr(plan_review, "card_for", lambda _: "card")
    monkeypatch.setattr(plan_review, "_run_review", capture)
    plan = tmp_path / "plan.md"
    plan.write_text("plan\n")

    plan_confirmation.run("story-042", plan, context)

    assert "components" not in seen["prior"]
    assert seen["prior"].count("f" * 64) == 2
