"""Branch change notes and their publication after merge."""

import json
import re

from xpcore import gitx, release
from xpcore.config import parse_config, refuse, repo_root, trunk


def parse(path, text):
    bumps = re.findall(r"^Bump:.*$", text, re.M)
    if len(bumps) != 1 or not re.fullmatch(r"Bump: (major|minor|patch)", bumps[0]):
        refuse(f"{path}: add exactly one Bump: major|minor|patch line")
    body = re.sub(r"^Bump:.*\n?", "", text, flags=re.M).strip()
    if not body or not re.search(r"^Release steps:", body, re.M):
        refuse(f"{path}: write a nonempty note with a Release steps: line")
    return bumps[0].split()[1], body


def committed_mode(root, ref):
    source = f"{ref}:.xp/config.yml"
    return release.versioning(parse_config(gitx.git("show", source, cwd=root), source))


def land_version(part, root, branch, base, into):
    mode = committed_mode(root, into)
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
        release.manifest_version(path, root)
        release.manifest_version(path, root, base)
        old = json.loads(gitx.git("show", f"{base}:{path}", cwd=root))["version"]
        if json.loads((root / path).read_text())["version"] != old:
            refuse(f"leave {path} version to xp.py release stamp; revert its version edit")
    return ""


def pending(root, ref="HEAD"):
    return [
        p
        for p in gitx.git("ls-tree", "-r", "--name-only", ref, cwd=root).splitlines()
        if p.startswith("changes/") and p.endswith(".md") and p != "changes/README.md"
    ]


def post_merge_mode(root, ref):
    mode = committed_mode(root, ref)
    if mode == "notes":
        for path in pending(root, ref):
            parse(path, gitx.git("show", f"{ref}:{path}", cwd=root))
    return mode


def remote_state(root, main):
    gitx.git(
        "fetch", "--no-tags", "origin", f"+refs/heads/{main}:refs/remotes/origin/{main}", cwd=root
    )
    tags = {}
    for line in gitx.git("ls-remote", "--tags", "origin", "refs/tags/v*", cwd=root).splitlines():
        sha, ref = line.split()
        name = ref.removeprefix("refs/tags/")
        if re.fullmatch(r"v\d+\.\d+\.\d+", name):
            tags[name] = sha
    if not tags:
        refuse(
            "no exact vX.Y.Z tag on origin; git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z"
        )
    return gitx.git("rev-parse", f"refs/remotes/origin/{main}", cwd=root), tags


def replace_version(path, original, version):
    """`original` with only its top-level version changed, every other byte kept."""
    want = json.loads(original) | {"version": version}
    for match in re.finditer(r'("version"\s*:\s*)("(?:[^"\\]|\\.)*")', original):
        updated = original[: match.start(2)] + json.dumps(version) + original[match.end(2) :]
        if json.loads(updated) == want:
            return updated
    refuse(f"{path}: cannot replace root version; fix the manifest")


def prepare(root, tags):
    paths, bodies, bumps = pending(root), [], []
    if not paths:
        refuse("no pending change notes; add changes/<branch>.md before stamping")
    for path in paths:
        part, body = parse(path, (root / path).read_text())
        added = gitx.git(
            "log", "-m", "--diff-filter=A", "--format=%ct", "--", path, cwd=root
        ).split()
        if not added:
            refuse(f"{path}: adding commit unavailable; fetch its history")
        bodies.append((int(added[-1]), path, body))
        bumps.append(part)
    latest = max(tags, key=release.key)
    version = release.bump(latest, max(bumps, key=["patch", "minor", "major"].index))
    if gitx.ref_exists(f"refs/tags/v{version}", root):
        refuse(
            f"local tag v{version} exists; inspect and remove the unpublished tag before stamping"
        )
    text = (root / "CHANGELOG.md").read_bytes().decode("utf-8")
    heading = re.search(r"^## ", text, re.M)
    if not heading:
        refuse("CHANGELOG.md: add an existing ## X.Y.Z heading before stamping")
    if re.search(rf"^## v?{re.escape(version)}(?:\s|$)", text, re.M):
        refuse(f"CHANGELOG.md already names {version}; inspect and push its missing tag")
    files = {}
    for path in release.version_files():
        release.manifest_version(path, root)
        files[path] = replace_version(path, (root / path).read_bytes().decode("utf-8"), version)
    files["CHANGELOG.md"] = (
        text[: heading.start()]
        + f"## {version}\n\n"
        + "\n\n".join(body for _, _, body in sorted(bodies))
        + "\n\n"
        + text[heading.start() :]
    )
    for path, content in files.items():
        (root / path).write_bytes(content.encode("utf-8"))
    gitx.git("add", "--", *files, cwd=root)
    gitx.git("rm", "--", *paths, cwd=root)
    return version


def cmd_stamp(args):
    if release.versioning() != "notes":
        refuse("release stamp requires versioning: notes in .xp/config.yml; set it before stamping")
    root, main = repo_root(), trunk()
    if gitx.current_branch(root) != main:
        refuse(f"release stamp runs on trunk; git switch {main}, then run again")
    if gitx.is_dirty(root):
        refuse("dirty tree; commit or discard changes before release stamp")
    if "origin" not in gitx.git("remote", cwd=root).split():
        refuse("release stamp needs origin; add the trunk remote first")
    base = gitx.head(root)
    remote, tags = remote_state(root, main)
    if base != remote:
        refuse(
            f"{main} differs from origin/{main}; fast-forward or reconcile trunk before stamping"
        )
    for attempt in range(2):
        try:
            version = prepare(root, tags)
        except (OSError, ValueError) as exc:
            refuse(f"cannot prepare release: {exc}; repair the release files and run again")
        gitx.git("commit", "-m", f"release: {version}", cwd=root)
        commit = gitx.head(root)
        release.tag(version, commit)
        tag = f"refs/tags/v{version}"
        tag_object = gitx.git("rev-parse", tag, cwd=root)
        try:
            gitx.git("push", "--atomic", "origin", main, tag, cwd=root)
        except gitx.GitError as exc:
            remote, tags = remote_state(root, main)
            if remote == commit:
                if tags.get(f"v{version}") != tag_object:
                    refuse("origin commit landed without matching annotated tag; inspect origin")
                print(f"stamped v{version} on origin")
                return 0
            if (
                gitx.head(root) != commit
                or gitx.is_dirty(root)
                or gitx.current_branch(root) != main
                or gitx.git("rev-parse", tag, cwd=root, check=False) != tag_object
            ):
                refuse("local state changed during push; inspect before retrying release stamp")
            if not gitx.is_ancestor(base, remote, root):
                refuse(f"origin/{main} diverged; inspect before retrying release stamp")
            gitx.git("tag", "-d", f"v{version}", cwd=root)
            gitx.git("reset", "--hard", remote, cwd=root)
            if remote == base:
                refuse(
                    f"{exc}; push rejected without concurrent publication; "
                    "fix the push error and rerun release stamp"
                )
            if not pending(root):
                print(f"already stamped as {max(tags, key=release.key)}")
                return 0
            if attempt:
                refuse(f"{exc}; second push rejected; inspect origin and rerun release stamp")
            base = remote
        else:
            print(f"stamped v{version} on origin")
            return 0
