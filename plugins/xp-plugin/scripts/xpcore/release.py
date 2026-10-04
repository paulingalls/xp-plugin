"""The version wall: manifests, CHANGELOG and tag name one new version before anything ships."""

import json
import re
from datetime import datetime, timezone

from xpcore import gitx
from xpcore.config import data_root, load_config, refuse, repo_root

SEMVER = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def versioning() -> bool:
    """`versioning: on` tags each release from version_files; `off` leaves versions and
    tags to the project. Unset refuses: a consumer upgrading must say which it wants."""
    raw = str(load_config().get("versioning") or "").strip().lower()
    if raw not in ("on", "off"):
        refuse(
            "set versioning: on or off in .xp/config.yml; on tags each release from"
            " version_files, off leaves versions and tags to the project"
        )
    return raw == "on"


def version_files() -> list[str]:
    raw = str(load_config().get("version_files") or "").strip()
    if not raw:
        refuse(
            "set version_files in .xp/config.yml to the JSON manifests the tag must match,"
            " or `none` to release without that wall"
        )
    return [] if raw == "none" else [p.strip() for p in raw.split(",") if p.strip()]


def manifest_version(path: str, root=None) -> str:
    full = (root or repo_root()) / path
    if full.suffix != ".json":
        refuse(f"version file {path} is not JSON; list only JSON manifests in version_files")
    try:
        data = json.loads(full.read_text())
    except (OSError, ValueError) as exc:
        refuse(f"cannot read {full} as JSON ({exc}); fix it or drop it from version_files")
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        refuse(f'{path} has no top-level "version": "X.Y.Z"; add one')
    return version.removeprefix("v")


def changelog_version(root=None) -> str:
    path = (root or repo_root()) / "CHANGELOG.md"
    if not path.is_file():
        refuse(f"no {path}; add one whose first `## ` heading names the release version")
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            if match := SEMVER.search(line):
                return match[0].removeprefix("v")
            refuse(f"CHANGELOG.md's first `## ` heading {line!r} names no X.Y.Z; name one")
    refuse("CHANGELOG.md has no `## ` heading; add `## X.Y.Z` above this release's notes")


def key(version: str) -> tuple[int, ...]:
    match = SEMVER.fullmatch(version)
    return tuple(map(int, match.groups())) if match else (0, 0, 0)


def latest_tag() -> str:
    tags = gitx.git("tag", "--list", "v*", cwd=repo_root()).split()
    tags = [t.removeprefix("v") for t in tags if SEMVER.fullmatch(t)]
    return max(tags, key=key, default="")


def tag_at_head(root) -> str:
    """The highest vX.Y.Z tag on HEAD, or "": a release that already tagged this commit."""
    tags = gitx.git("tag", "--points-at", "HEAD", cwd=root).split()
    tags = [t for t in tags if t.startswith("v") and SEMVER.fullmatch(t)]
    return max(tags, key=lambda t: key(t.removeprefix("v")), default="")


def bump(version: str, part: str) -> str:
    major, minor, patch = key(version)
    return {
        "major": f"{major + 1}.0.0",
        "minor": f"{major}.{minor + 1}.0",
        "patch": f"{major}.{minor}.{patch + 1}",
    }[part]


def version_wall(part: str, root=None) -> str:
    """The release version X that `root`'s tree (default: this one) names, or "" under
    `versioning: off`. `part` only matters under `version_files: none`, where the latest
    tag bumped by it is X."""
    if not versioning():
        return ""
    files, latest = version_files(), latest_tag()
    if not files:
        return bump(latest or "0.0.0", part)
    found = {path: manifest_version(path, root) for path in files}
    version = found[files[0]]
    problems = []
    if len(set(found.values())) > 1:
        named = ", ".join(f"{p}={v}" for p, v in found.items())
        problems.append(f"manifests disagree ({named})")
    if (named := changelog_version(root)) != version:
        problems.append(f"CHANGELOG.md's first `## ` heading names {named}, not {version}")
    if gitx.ref_exists(f"refs/tags/v{version}", cwd=repo_root()):
        problems.append(f"tag v{version} already exists")
    elif latest and key(version) <= key(latest):
        problems.append(f"{version} is not after the latest tag v{latest}")
    if problems:
        refuse(
            f"version wall: {'; '.join(problems)}; set every manifest and the CHANGELOG"
            " heading to one version above the latest tag, commit, and run again"
        )
    return version


def tag_note(version: str) -> str:
    if not version:
        return "; versions and tags are the project's (versioning: off)"
    return f" as v{version}. Push the tag: git push origin v{version}"


def tag(version: str) -> None:
    gitx.git("tag", "-a", f"v{version}", "-m", f"v{version}", cwd=repo_root())


def write_release_record(sprint_id, version: str, merge_sha: str):
    path = data_root() / "sprints" / str(sprint_id) / "release.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {"sprint": str(sprint_id), "version": version, "tag": f"v{version}" if version else ""}
    path.write_text(json.dumps(record | {"merge": merge_sha, "date": stamp}, indent=2) + "\n")
    return path
