import subprocess


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.rstrip()


def render(base: str, head: str) -> str:
    full_base = _git("rev-parse", base)
    full_head = _git("rev-parse", head)
    diff_range = f"{full_base}..{full_head}"
    prefix = f"Base: {full_base}\nHead: {full_head}\nRange: {diff_range}\n"
    numstat = _git("-c", "core.quotepath=off", "diff", "--numstat", "--no-renames", diff_range)
    if not numstat:
        return prefix + "\nThis range holds no changes."
    commits = _git("log", "--format=%H%x09%s", diff_range) or "none"
    return (
        prefix
        + "\nRead the full diff from the reviewer's working directory:\n"
        + f"git diff {diff_range}\n\n"
        + "Read one changed path:\n"
        + f"git diff {diff_range} -- <path>\n\n"
        + "Commits (full SHA, subject):\n"
        + commits
        + "\n\nPer-file changes (added, deleted, full path):\n"
        + numstat
    )
