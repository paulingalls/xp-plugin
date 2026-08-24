"""The release identity: tag, manifest and CHANGELOG must name one version.

v0.6.0 was tagged with plugin.json still at 0.5.0 and CHANGELOG.md already at
0.6.0. The bump is mandated in the sprint-close skill's prose and was enforced
by nothing, so it was skipped and nothing said so. It is not cosmetic: the
manifest version keys the consumer's plugin cache (DESIGN §3), so the tag moved
and consumers kept running the previous cached copy under the new name.
"""

import json
import re
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
