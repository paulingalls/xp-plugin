import shlex
import subprocess


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.rstrip()


def render(base: str, head: str, excluded: set[str] | None = None, trunk_range: str = "") -> str:
    full_base = _git("rev-parse", base)
    full_head = _git("rev-parse", head)
    diff_range = f"{full_base}..{full_head}"
    prefix = f"Base: {full_base}\nHead: {full_head}\nRange: {diff_range}\n"
    pathspec = (
        ["--", ".", *(f":(exclude){path}" for path in sorted(excluded or set()))]
        if excluded
        else []
    )
    numstat = _git(
        "-c", "core.quotepath=off", "diff", "--numstat", "--no-renames", diff_range, *pathspec
    )
    notice = (
        f"\nExcluded trunk-only paths from {trunk_range}: {', '.join(sorted(excluded))}\n"
        if excluded
        else ""
    )
    if not numstat:
        empty = (
            "This range holds no included changes." if excluded else "This range holds no changes."
        )
        return prefix + notice + "\n" + empty
    commits = _git("log", "--format=%H%x09%s", diff_range) or "none"
    full_command = f"git diff {diff_range}"
    if pathspec:
        full_command += " " + " ".join(shlex.quote(p) for p in pathspec)
    return (
        prefix
        + notice
        + "\nRead the full diff from the reviewer's working directory:\n"
        + full_command
        + "\n\n"
        + "Read one changed path:\n"
        + f"git diff {diff_range} -- <path>"
        + (" " + " ".join(shlex.quote(p) for p in pathspec[2:]) if excluded else "")
        + "\n\n"
        + "Commits (full SHA, subject):\n"
        + commits
        + ("\n(Commit subjects include the excluded trunk merge.)" if excluded else "")
        + "\n\nPer-file changes (added, deleted, full path):\n"
        + numstat
    )
