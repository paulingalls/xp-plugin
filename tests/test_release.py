"""The release identity: tag, manifest and CHANGELOG must name one version.

v0.6.0 was tagged with plugin.json still at 0.5.0 and CHANGELOG.md already at
0.6.0. The bump is mandated in the sprint-close skill's prose and was enforced
by nothing, so it was skipped and nothing said so. It is not cosmetic: the
manifest version keys the consumer's plugin cache (DESIGN §3), so the tag moved
and consumers kept running the previous cached copy under the new name.
"""

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
MANIFEST = REPO / "plugins" / "xp-plugin" / ".claude-plugin" / "plugin.json"
sys.path.insert(0, str(REPO / "plugins" / "xp-plugin" / "scripts"))
from close import config_flat  # noqa: E402


def parts(version):
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    return tuple(int(g) for g in m.groups()) if m else None


def declared():
    return json.loads(MANIFEST.read_text())["version"]


def latest_release(cwd=REPO):
    """Highest semver among the tags reachable from HEAD. NOT `git describe
    --abbrev=0`, which answers the NEAREST tag whatever its name: one `nightly-*`
    on HEAD made every version below unparseable and the check returned early —
    green, having compared nothing, for as long as that tag stayed closest."""
    tags = subprocess.run(
        ["git", "tag", "--list", "--merged", "HEAD"], cwd=cwd, capture_output=True, text=True
    )
    return max((p for t in tags.stdout.split() if (p := parts(t))), default=None)


def test_the_manifest_is_never_behind_the_latest_reachable_tag():
    """>= and not ==: a branch heading for the next release leads the tag by
    design, and only BEHIND ships stale code under a new name."""
    if not (released := latest_release()):
        return  # no reachable semver tag (shallow clone, fresh fork) — nothing to compare
    assert (mine := parts(declared())), f"manifest version is not MAJOR.MINOR.PATCH: {declared()}"
    assert mine >= released, (
        f"manifest {declared()} is BEHIND tag v{'.'.join(map(str, released))} — the manifest"
        " keys the consumer's plugin cache, so this tag ships the previous copy"
    )


def test_a_non_semver_tag_cannot_disable_the_check(tmp_path):
    """Constraint 2 on the guard itself: it must still find v0.1.0 with a tag
    named after a date sitting on top of it."""

    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "x")
    git("tag", "v0.1.0")
    git("commit", "-q", "--allow-empty", "-m", "y")
    git("tag", "nightly-2026-08-22")
    assert latest_release(tmp_path) == (0, 1, 0)


def test_the_changelog_carries_an_entry_for_the_declared_version():
    """A presence check, which is all a changelog admits — it catches the half-done
    bump (manifest moved, notes forgotten), not the contents of the notes."""
    assert f"v{declared()}" in (REPO / "CHANGELOG.md").read_text(), (
        f"CHANGELOG.md has no v{declared()} entry"
    )


def test_this_repos_release_guard_reads_an_existing_manifest():
    names = (name.strip() for name in config_flat("version_files").split(","))
    paths = [REPO / name for name in names if name]
    assert paths and all(path.is_file() for path in paths)


def _refusal(tmp_path, monkeypatch, manifest_body=None):
    """version_refusal against a scratch tree — the config key is read from cwd."""
    import sys as _sys

    _sys.path.insert(0, str(REPO / "plugins" / "xp-plugin" / "scripts" / "close"))
    import release

    xp = tmp_path / ".xp"
    xp.mkdir()
    (xp / "config.yml").write_text("version_files: pkg/manifest.json\n")
    if manifest_body is not None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "manifest.json").write_text(manifest_body)
    monkeypatch.chdir(tmp_path)
    return release.version_refusal("v1.2.3")


def test_a_missing_manifest_is_not_called_unreadable(tmp_path, monkeypatch):
    """Absent and unreadable are different problems with different fixes — the
    repo's most-filed defect class (90fcd7d4, 5a1abadb, c12ab60d, 2d32fe3d).
    OSError was caught beside ValueError/KeyError, so a manifest that does not
    exist and one full of garbage produced the same sentence, and the reader was
    sent to fix a version field in a file they have not created."""
    absent = _refusal(tmp_path, monkeypatch)
    assert "missing" in absent, f"a manifest that does not exist: {absent!r}"
    assert "no readable" not in absent, absent


def test_a_present_but_malformed_manifest_still_says_unreadable(tmp_path, monkeypatch):
    """The other arm, so the fix cannot collapse the pair the other way."""
    bad = _refusal(tmp_path, monkeypatch, manifest_body="{not json")
    assert "no readable" in bad, bad
    assert "missing" not in bad, bad


def test_a_release_that_checked_NO_manifest_says_so(tmp_path, monkeypatch):
    """version_files ships COMMENTED, so a consuming project's post-merge printed
    `tagged vX.Y.Z at <sha>` whether the manifest matched or whether nothing had
    ever looked — the same line for a wall that held and a wall that is absent.
    Constraint 14's whole failure mode is a release step nothing enforces."""
    import sys as _sys

    _sys.path.insert(0, str(REPO / "plugins" / "xp-plugin" / "scripts" / "close"))
    import release

    xp = tmp_path / ".xp"
    xp.mkdir()
    (xp / "config.yml").write_text("release: sprint\n")
    monkeypatch.chdir(tmp_path)
    assert release.version_files() == []
    assert release.version_refusal("v1.2.3") == "", "no key configured is not a refusal"


def test_a_release_that_DID_check_names_the_manifest_it_checked(tmp_path, monkeypatch):
    """The pair: a report that says the same thing either way is the wallpaper
    this replaces, so the two states must produce two different sentences."""
    import sys as _sys

    _sys.path.insert(0, str(REPO / "plugins" / "xp-plugin" / "scripts" / "close"))
    import release

    xp = tmp_path / ".xp"
    xp.mkdir()
    (xp / "config.yml").write_text("version_files: pkg/manifest.json, other.json\n")
    monkeypatch.chdir(tmp_path)
    assert release.version_files() == ["pkg/manifest.json", "other.json"]


def test_sprint_lifecycle_runs_after_validation_and_before_the_retryable_tag(tmp_path, monkeypatch):
    import release

    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(tmp_path / "data")}
    git = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True, check=True
    )
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / ".xp").mkdir()
    (repo / "manifest.json").write_text('{"version": "1.2.0"}\n')
    log = tmp_path / "released.jsonl"
    hook = tmp_path / "release_hook.py"
    hook.write_text(
        "import json, pathlib, subprocess, sys\n"
        f"p = pathlib.Path({str(log)!r})\n"
        "tag = subprocess.run(['git','rev-parse','--verify','-q','refs/tags/v1.2.0']).returncode\n"
        "with p.open('a') as f: f.write(json.dumps([sys.argv[1:], tag])+'\\n')\n"
        "raise SystemExit(int(p.with_suffix('.exit').read_text()) "
        "if p.with_suffix('.exit').exists() else 0)\n"
    )
    command = shlex.join([sys.executable, str(hook), "fixed value"])
    config = repo / ".xp" / "config.yml"
    config.write_text(f"lifecycle_command: {command}\nversion_files: manifest.json\n")
    git("add", "-A")
    git("commit", "-qm", "release tree")
    git("tag", "v1.1.0")
    git("branch", "sprint-011")
    state = tmp_path / "data" / "sprint_branch"
    state.parent.mkdir()
    state.write_text("sprint-011\n")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PATH", env["PATH"])
    monkeypatch.setenv("XP_DATA", env["XP_DATA"])

    assert release.cmd_post_merge("12") == 2
    assert not log.exists() and state.exists()
    (repo / "manifest.json").write_text("{}\n")
    assert release.cmd_post_merge("11") == 2
    assert not log.exists(), "project code ran before manifest validation"
    (repo / "manifest.json").write_text('{"version": "1.2.0"}\n')
    log.with_suffix(".exit").write_text("1")
    assert release.cmd_post_merge("11") == 2
    assert git("tag", "--list", "v1.2.0").stdout.strip() == ""
    assert state.exists(), "a refused lifecycle retired the sprint record"
    log.with_suffix(".exit").write_text("0")
    assert release.cmd_post_merge("11") == 0
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls == [
        [["fixed value", "sprint-close", "11"], 1],
        [["fixed value", "sprint-close", "11"], 1],
    ]
    assert git("tag", "--list", "v1.2.0").stdout.strip() == "v1.2.0"
    assert not state.exists()
