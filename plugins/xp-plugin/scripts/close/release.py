"""Cut a release tag only after its branch and manifest agree on the merged tree."""

import json
import re
from pathlib import Path

from close import config_flat, default_branch, fail, git
from env import clear_sprint_branch, sprint_branch


def next_version(part: str = "minor", ref: str = "HEAD") -> str:
    latest = git("describe", "--tags", "--abbrev=0", ref, check=False).stdout.strip() or "v0.0.0"
    if not (match := re.fullmatch(r"v?(\d+)\.(\d+)(\..*)?", latest)):
        return ""
    if part != "patch":
        return f"v{match.group(1)}.{int(match.group(2)) + 1}.0"
    patch = re.match(r"\.(\d+)", match.group(3) or "")
    return f"v{match.group(1)}.{match.group(2)}.{int(patch.group(1)) + 1 if patch else 1}"


def refuse_unbumpable(ref: str = "HEAD") -> int:
    latest = git("describe", "--tags", "--abbrev=0", ref, check=False).stdout.strip()
    return fail(f"refused: latest tag {latest!r} is not vMAJOR.MINOR — cannot bump it")


def version_files() -> list[str]:
    """Named once: the leg that REPORTS cannot drift from the leg that checks."""
    return [part.strip() for part in config_flat("version_files").split(",") if part.strip()]


def version_refusal(version: str) -> str:
    target = tuple(map(int, version.removeprefix("v").split(".")))
    for name in version_files():
        path = Path(name)
        # ABSENT and UNREADABLE are different problems with different fixes, and
        # OSError sat beside the parse errors: a manifest nobody has created yet
        # was reported as one whose version field is malformed, sending the reader
        # to edit a file that is not there (the repo's most-filed class).
        try:
            raw = path.read_text()
        except OSError:
            return (
                f"refused: manifest {path} is missing — version_files names it,"
                " so create it or drop it from that key"
            )
        try:
            declared = str(json.loads(raw)["version"])
            parts = tuple(map(int, declared.removeprefix("v").split(".")))
        except (ValueError, KeyError, TypeError):
            return f"refused: manifest {path} has no readable MAJOR.MINOR.PATCH version"
        if parts < target:
            return f"refused: manifest {path} version {declared} is BEHIND tag {version}"
        if parts != target:
            return f"refused: manifest {path} version {declared} does not match tag {version}"
    return ""


def cmd_post_merge(
    release_id: str, merged_branch: str = "", part: str = "minor", retire_sprint: bool = True
) -> int:
    if (head := git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()) != (
        trunk := default_branch()
    ):
        return fail(f"refused: on {head}, not {trunk} — the release tag names the MERGED sha")
    release_branch = merged_branch or sprint_branch()
    if retire_sprint and not release_branch:
        return fail("refused: no sprint branch recorded — open the sprint before releasing it")
    if (
        release_branch
        and git("merge-base", "--is-ancestor", release_branch, "HEAD", check=False).returncode
    ):
        return fail(
            f"refused: {release_branch} is not merged into {trunk} — tagging here would"
            f" name a commit containing none of {release_id}. Merge the release PR first"
        )
    if not (version := next_version(part)):
        return refuse_unbumpable()
    if git("rev-parse", "--verify", "-q", f"refs/tags/{version}", check=False).returncode == 0:
        return fail(f"refused: tag {version} already exists — nothing was changed")
    config = Path(".xp/config.yml")
    if not config.exists():
        return fail("refused: no .xp/config.yml here — is this an xp-managed repo?")
    if refusal := version_refusal(version):
        return fail(refusal)
    if git("tag", version, check=False).returncode:
        return fail(f"refused: could not create tag {version}")
    if retire_sprint:
        clear_sprint_branch()
    suffix = "; sprint branch cleared" if retire_sprint else ""
    # version_files ships COMMENTED, so the DEFAULT project cuts every tag with
    # no wall; a release's tag, manifest and CHANGELOG must name one version.
    walled = (
        f"manifests matching {version}: {', '.join(checked)}"
        if (checked := version_files())
        else "NO manifest was checked — set version_files: in .xp/config.yml to wall it"
    )
    print(f"tagged {version} at {git('rev-parse', 'HEAD').stdout.strip()[:8]}{suffix}; {walled}")
    next_step = "push the tag and open the next sprint"
    print(next_step if retire_sprint else "push the tag")
    return 0
