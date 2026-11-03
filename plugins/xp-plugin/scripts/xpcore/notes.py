"""Branch change notes and their publication after merge."""

import re

from xpcore import gitx, release
from xpcore.config import refuse


def parse(path, text):
    bumps = re.findall(r"^Bump:.*$", text, re.M)
    if len(bumps) != 1 or not re.fullmatch(r"Bump: (major|minor|patch)", bumps[0]):
        refuse(f"{path}: add exactly one Bump: major|minor|patch line")
    body = re.sub(r"^Bump:.*\n?", "", text, flags=re.M).strip()
    if not body or not re.search(r"^Release steps:", body, re.M):
        refuse(f"{path}: write a nonempty note with a Release steps: line")
    return bumps[0].split()[1], body


def land_version(part, root, branch, base):
    mode = release.versioning()
    if mode == "on":
        return release.version_wall(part, root)
    if mode == "off":
        return ""
    expected = f"changes/{branch}.md"
    added = gitx.git(
        "diff", "--name-only", "--no-renames", "--diff-filter=A", base, "HEAD", cwd=root
    ).splitlines()
    if expected not in added:
        refuse(f"add {expected} with Bump: major|minor|patch and Release steps: before land")
    parse(expected, (root / expected).read_text())
    changed = gitx.changed_files(base, "HEAD", root)
    if "CHANGELOG.md" in changed:
        refuse("leave CHANGELOG.md to xp.py release stamp; revert its branch edits")
    for path in release.version_files():
        if release.manifest_version(path, root) != release.manifest_version(path, root, base):
            refuse(f"leave {path} version to xp.py release stamp; revert its version edit")
    return ""
