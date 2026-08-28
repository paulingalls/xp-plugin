import shlex
import shutil
import subprocess

KEY = "lifecycle_command"


def _commands(raw: str, owner: str, runnable: bool, chained: bool) -> list[list[str]]:
    parts, start, quote, i = [], 0, "", 0
    while i < len(raw):
        char = raw[i]
        if char == "\\" and quote != "'":
            i += 2
            continue
        if char in "'\"":
            quote = "" if quote == char else quote if quote else char
        elif char in "$`" or (not quote and char in "|&;<>()[#*?~{"):
            if chained and char == "&" and raw[i : i + 2] == "&&":
                parts.append(raw[start:i])
                start, i = i + 2, i + 1
            else:
                raise ValueError(
                    f"refused: {owner} contains shell syntax {char!r} — no shell runs it:"
                    " quote it and drop any trailing # comment (checks chain on unquoted &&)"
                )
        i += 1
    parts.append(raw[start:])
    try:
        commands = [shlex.split(part) for part in parts]
    except ValueError as e:
        raise ValueError(f"refused: {owner} is not runnable ({e})") from e
    if any(not argv for argv in commands):
        raise ValueError(f"refused: {owner} has an empty command around &&")
    if runnable and (
        missing := next((a[0] for a in commands if a[0] == "cd" or not shutil.which(a[0])), "")
    ):
        raise ValueError(
            f"refused: {owner} command {missing!r} is not runnable on PATH — no shell, no `cd`"
        )
    return commands


def declared_commands(
    owner: str, block: str, runnable: bool = True, label: str = "Verify"
) -> tuple[str, list[list[str]]]:
    field = f"{label}:"
    raw = next(
        (ln[len(field) :].strip() for ln in block.splitlines() if ln.startswith(field)), None
    )
    if raw is None:
        raise ValueError(f"refused: {owner} has no {field} line")
    if not raw:
        raise ValueError(f"refused: {owner}'s {field} line is empty — put it on the SAME line")
    return raw, _commands(raw, f"{owner}'s {field} line", runnable=runnable, chained=True)


def run(command: str, event: str, identity: str) -> str:
    if not command:
        return ""
    owner = f"lifecycle {event} command {command!r}"
    try:
        argv = _commands(command, owner, runnable=False, chained=False)[0] + [event, identity]
        result = subprocess.run(argv)
    except (OSError, ValueError) as e:
        return f"refused: {owner} could not run ({e})"
    return f"refused: {owner} red ({shlex.join(argv)})" if result.returncode else ""
