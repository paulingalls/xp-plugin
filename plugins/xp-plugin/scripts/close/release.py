"""Finish a release only after its branch agrees with the merged tree."""

import json
import re
import tempfile
from pathlib import Path

import lifecycle as lc
from close import config_flat, config_has, default_branch, fail, git
from env import clear_sprint_branch, data_root, sprint_branch


def release_record_path(release_id: str) -> Path:
    return data_root() / "releases" / f"sprint-{int(release_id)}.json"


def write_release_record(release_id: str, tag: str | None) -> Path:
    path = release_record_path(release_id)
    record = {"sprint": int(release_id), "merged_sha": git("rev-parse", "HEAD").stdout.strip()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record | {"tag": tag}, stream)
            stream.write("\n")
        temporary.replace(path)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return path


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


VERSIONING_OFF_TEXT = "`versioning: off`: no tag is cut; `version_files` is ignored"


def versioning_mode() -> tuple[bool, str]:
    if not config_has("versioning"):
        return True, ""
    value = config_flat("versioning")
    if value == "off":
        return False, ""
    shown = value or "<empty>"
    return False, (
        f"refused: versioning is {shown!r}; `off` is the only valid value — remove"
        " the key to enable versioning"
    )


def version_files() -> list[str]:
    """Named once: the leg that REPORTS cannot drift from the leg that checks."""
    return [part.strip() for part in config_flat("version_files").split(",") if part.strip()]


WAIVED = (
    "NO manifest was checked — `version_files: none` waives the wall, and the tag"
    " can name a version no file in this tree declares"
)


def walled_text(names: list[str], version: str) -> str:
    """One sentence, two callers: the preview must say exactly what the real leg
    will, or the preview is not a preview. It names the VERSION because that is
    what the manifests were checked against."""
    if names == ["none"]:
        return WAIVED
    return f"manifests matching {version}: {', '.join(names)}"


def version_refusal(version: str, names: list[str] | None = None) -> str:
    names = version_files() if names is None else names
    if names == ["none"]:
        return ""  # walled by hand, on purpose: see WAIVED
    if not names:
        return (
            "refused: version_files is unset or empty — a release tag keys the"
            " consumer's plugin cache, so a tag no file declares ships the previous"
            " copy under the new name. Name your manifests in .xp/config.yml, or"
            " `version_files: none` to release without that wall."
        )
    target = tuple(map(int, version.removeprefix("v").split(".")))
    for name in names:
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
    release_id: str,
    merged_branch: str = "",
    part: str = "minor",
    retire_sprint: bool = True,
    dry_run: bool = False,
) -> int:
    versioned, refusal = versioning_mode()
    if refusal:
        return fail(refusal)
    if (head := git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()) != (
        trunk := default_branch()
    ):
        reason = "the release tag names" if versioned else "the release must finish on"
        return fail(f"refused: on {head}, not {trunk} — {reason} the MERGED sha")
    release_branch = merged_branch or sprint_branch()
    if retire_sprint and not release_branch:
        return fail("refused: no sprint branch recorded — open the sprint before releasing it")
    if retire_sprint and release_branch != f"sprint-{release_id.lstrip('0').zfill(3)}":
        return fail(f"refused: sprint {release_id} does not own recorded branch {release_branch}")
    if (
        release_branch
        and git("merge-base", "--is-ancestor", release_branch, "HEAD", check=False).returncode
    ):
        action = "tagging here would" if versioned else "shipping here would"
        return fail(
            f"refused: {release_branch} is not merged into {trunk} — {action}"
            f" name a commit containing none of {release_id}. Merge the release PR first"
        )
    if not versioned:
        if dry_run:
            if retire_sprint:
                print(
                    "dry run: would run the sprint-close lifecycle, which has NOT run here"
                    " and can still refuse, then clear the sprint branch"
                )
            print(VERSIONING_OFF_TEXT)
            return 0
        if retire_sprint and (red := lc.run(config_flat(lc.KEY), "sprint-close", release_id)):
            return fail(red)
        if retire_sprint:
            try:
                write_release_record(release_id, None)
            except OSError as exc:
                path = release_record_path(release_id)
                return fail(f"refused: could not write release record {path}: {exc}")
            clear_sprint_branch()
        print(VERSIONING_OFF_TEXT)
        if retire_sprint:
            print("sprint branch cleared; open the next sprint")
        return 0
    if not (version := next_version(part)):
        return refuse_unbumpable()
    if git("rev-parse", "--verify", "-q", f"refs/tags/{version}", check=False).returncode == 0:
        return fail(f"refused: tag {version} already exists — nothing was changed")
    config = Path(".xp/config.yml")
    if not config.exists():
        return fail("refused: no .xp/config.yml here — is this an xp-managed repo?")
    checked = version_files()
    if refusal := version_refusal(version, checked):
        return fail(refusal)
    if dry_run:
        # The sprint-close lifecycle runs BELOW this return and can still refuse,
        # so a preview that promised only "would tag" overstated what it checked.
        after = (
            "; then run the sprint-close lifecycle, which has NOT run here and can"
            " still refuse, and clear the sprint branch"
            if retire_sprint
            else ""
        )
        print(f"dry run: would tag {version}{after}; {walled_text(checked, version)}")
        return 0
    if retire_sprint and (red := lc.run(config_flat(lc.KEY), "sprint-close", release_id)):
        return fail(red)
    if git("tag", version, check=False).returncode:
        return fail(f"refused: could not create tag {version}")
    if retire_sprint:
        try:
            write_release_record(release_id, version)
        except OSError as exc:
            removed = git("tag", "-d", version, check=False)
            stranded = (
                f"; tag {version} was created but could not be removed — remove it before retrying"
                if removed.returncode
                else ""
            )
            return fail(
                f"refused: could not write release record {release_record_path(release_id)}:"
                f" {exc}{stranded}"
            )
        clear_sprint_branch()
    suffix = "; sprint branch cleared" if retire_sprint else ""
    walled = walled_text(checked, version)
    print(f"tagged {version} at {git('rev-parse', 'HEAD').stdout.strip()[:8]}{suffix}; {walled}")
    next_step = "push the tag and open the next sprint"
    print(next_step if retire_sprint else "push the tag")
    return 0
