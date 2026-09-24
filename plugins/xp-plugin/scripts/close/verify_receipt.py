"""Review-time Verify evidence and story/free land reuse."""

import json
import subprocess
from pathlib import Path

from close import git
from work import data_root


def path(story_id: str) -> Path:
    return data_root() / "markers" / f"{story_id}.verify.json"


def reads(card: str) -> tuple[str | None, list[str]]:
    lines = [
        line.removeprefix("Verify reads:")
        for line in card.splitlines()
        if line.startswith("Verify reads:")
    ]
    if not lines:
        return None, []
    if len(lines) != 1 or not lines[0].strip():
        raise ValueError("refused: Verify reads: requires one nonempty line of repo pathspecs")
    specs = [item.strip() for item in lines[0].split(",")]
    if any(not item or item.startswith("/") for item in specs):
        raise ValueError("refused: Verify reads: requires comma-separated repo pathspecs")
    return lines[0], specs


def verify_line(card: str) -> str:
    return next(line for line in card.splitlines() if line.startswith("Verify:"))


def record(story_id: str, card: str, verify: list[list[str]]) -> str:
    from overlap import run_checks

    destination = path(story_id)
    try:
        declaration, _ = reads(card)
        destination.unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        return f"refused: Verify receipt could not be prepared: {exc}"
    if red := run_checks(verify, None, " on the reviewed tree"):
        return red
    written = git("write-tree", check=False)
    if written.returncode:
        return f"refused: could not write reviewed Verify tree: {written.stderr.strip()}"
    receipt = {
        "tree": written.stdout.strip(),
        "head": git("rev-parse", "HEAD").stdout.strip(),
        "raw": verify_line(card),
        "verify": verify,
        "reads": declaration,
    }
    try:
        destination.write_text(json.dumps(receipt))
    except OSError as exc:
        return f"refused: could not record green Verify: {exc}"
    return ""


def decide(story_id: str, card: str, verify: list[list[str]], tree: str) -> tuple[bool, str]:
    destination = path(story_id)
    try:
        receipt = json.loads(destination.read_text())
    except FileNotFoundError:
        return False, "ran: Verify receipt missing"
    except (OSError, ValueError):
        return False, "ran: Verify receipt unreadable"
    required = {"tree", "head", "raw", "verify", "reads"}
    if (
        not isinstance(receipt, dict)
        or set(receipt) != required
        or any(not isinstance(receipt[key], str) for key in ("tree", "head", "raw"))
        or not isinstance(receipt["verify"], list)
        or (receipt["reads"] is not None and not isinstance(receipt["reads"], str))
    ):
        return False, "ran: Verify receipt unreadable"
    declaration, specs = reads(card)
    if receipt["raw"] != verify_line(card) or receipt["verify"] != verify:
        return False, "ran: Verify commands changed"
    if receipt["reads"] != declaration:
        return False, "ran: Verify reads declaration changed"
    if receipt["tree"] == tree:
        return True, "skipped on exact tree"
    current_head = git("rev-parse", "HEAD").stdout.strip()
    current_tree = git("rev-parse", "HEAD^{tree}").stdout.strip()
    if declaration is None:
        return False, "ran: gated tree changed; no Verify reads declaration"
    if current_head != receipt["head"] or current_tree != receipt["tree"]:
        return False, "ran: story changed since reviewed Verify"
    changed = git(
        "-c", "core.quotepath=off", "diff", "--cached", "--no-renames", "--name-only", "HEAD"
    ).stdout.splitlines()
    matched = subprocess.run(["git", "diff", "--cached", "--quiet", "HEAD", "--", *specs])
    if matched.returncode != 0:
        return False, "ran: trunk merge changed declared Verify reads"
    listed = ", ".join(changed) or "(none)"
    return True, f"skipped on declared inputs ({declaration.strip()}); merge changed: {listed}"
