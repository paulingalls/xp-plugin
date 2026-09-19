#!/usr/bin/env python3
"""Refuse stale node IDs and unowned or unconstructable falsifier scripts."""

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins/xp-plugin/scripts"))
sys.path.insert(0, str(ROOT / "plugins/xp-plugin/scripts/close"))

from env import data_root  # noqa: E402
from falsifier_batch import corpus  # noqa: E402
from work import falsifier_result  # noqa: E402

SCRIPT_PATH = re.compile(r"^tests/scripts/falsifier_[^/]+\.py$")


def _pytest_words(command: str) -> list[str]:
    try:
        words = shlex.split(command)
    except ValueError:
        return []
    return words if any(Path(w).name in ("pytest", "py.test") for w in words) else []


def selects_by_name(command: str) -> bool:
    """Any name-based selection, -k OR a node id. A node id IS a name (constraint
    11), and naming one buys nothing if nothing checks it still resolves — the
    2026-09-02 close aborted on a node id left behind by a test that moved file."""
    words = _pytest_words(command)
    broad = any(w.startswith("-k") or re.fullmatch(r"-[dflqsvx]+k.*", w) for w in words)
    return bool(words) and (broad or any("::" in w for w in words))


def selects_broadly(command: str) -> bool:
    """The -k half, which no node id can repair: replace it, do not resolve it."""
    words = _pytest_words(command)
    return any(w.startswith("-k") or re.fullmatch(r"-[dflqsvx]+k.*", w) for w in words)


def node_ids(command: str) -> list[str]:
    return [w for w in _pytest_words(command) if "::" in w]


def resolves(node_id: str, collected: set[str]) -> bool:
    """A node id selects a SUBTREE, and `--collect-only -q` prints only leaves, so a
    class or file selector is legitimate and appears verbatim in nothing. Match on a
    `::` or `[` boundary, never a bare prefix: `...::TestLand` must not be satisfied
    by `...::TestLandFully::test_x`. BOTH boundaries were earned by a false positive:
    exact membership called four live class-level records stale, and `::` alone then
    called a parametrized leaf stale, its ids ending `...flip[planned-ready]`."""
    return node_id in collected or any(
        c.startswith(node_id + "::") or c.startswith(node_id + "[") for c in collected
    )


def collected_ids() -> tuple[set[str], str]:
    """Every node id pytest can collect, in ONE run. Per-id collection is correct
    and costs a subprocess each; batching them into one pytest call is NOT — a
    missing id there collects fewer tests and still exits 0, measured."""
    result = subprocess.run(
        ["pytest", "--collect-only", "-q"], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode:
        return set(), result.stdout[-400:] + result.stderr[-400:]
    return {line.strip() for line in result.stdout.splitlines() if "::" in line}, ""


def script_owners(records) -> dict[str, list[str]]:
    owners = {}
    for eid, _head, command, _coverage in records:
        try:
            paths = {word for word in shlex.split(command) if SCRIPT_PATH.fullmatch(word)}
        except ValueError:
            paths = set()
        for path in paths:
            owners.setdefault(path, []).append(eid)
    return owners


def script_correspondence(records, scripts_dir: Path) -> int:
    owners = script_owners(records)
    present = {f"tests/scripts/{path.name}" for path in scripts_dir.glob("falsifier_*.py")}
    orphans = present - owners.keys()
    missing = owners.keys() - present
    for path in sorted(orphans):
        print(
            f"refused: orphan falsifier script {path}; no live Falsifier line owns it."
            " Remove it if its record was archived, or restore a live Falsifier line",
            file=sys.stderr,
        )
    for path in sorted(missing):
        print(
            f"refused: live record(s) {', '.join(owners[path])} name missing script {path}."
            " Restore the script or repoint the live Falsifier line",
            file=sys.stderr,
        )
    return int(bool(orphans or missing))


def could_not_run(command: str, result) -> bool:
    output = result.stdout + result.stderr
    if "COULD NOT RUN" in output:
        return True
    if "Traceback" not in output:
        return False
    if "ImportError" in output or "ModuleNotFoundError" in output:
        return True
    paths = [word for word in shlex.split(command) if SCRIPT_PATH.fullmatch(word)]
    return "FileNotFoundError" in output and any(path in output for path in paths)


def audit_scripts(records, runner=falsifier_result) -> int:
    commands = {}
    for eid, _head, command, _coverage in records:
        try:
            owns_script = any(SCRIPT_PATH.fullmatch(word) for word in shlex.split(command))
        except ValueError:
            owns_script = False
        if owns_script:
            commands.setdefault(command, []).append(eid)
    status = 0
    for command, eids in commands.items():
        result = runner(command)
        if not result.returncode:
            continue
        unrunnable = could_not_run(command, result)
        status = 2 if unrunnable else max(status, 1)
        print(
            f"{'COULD NOT RUN' if unrunnable else 'RED'}: {command} (record(s) {', '.join(eids)})",
            file=sys.stderr,
        )
        print(f"stdout:\n{result.stdout or '(empty)'}", file=sys.stderr)
        print(f"stderr:\n{result.stderr or '(empty)'}", file=sys.stderr)
        print(
            "Repair the command or fixture" if unrunnable else "Fix the falsified claim",
            file=sys.stderr,
        )
    return status


def check_scripts(records, scripts_dir: Path, execute=True, runner=falsifier_result) -> int:
    if status := script_correspondence(records, scripts_dir):
        return status
    return audit_scripts(records, runner) if execute else 0


def check_node_ids(records, work: Path) -> int:
    broad = [eid for eid, _h, command, _c in records if selects_broadly(command)]
    named = [(eid, nid) for eid, _h, command, _c in records for nid in node_ids(command)]
    if broad:
        print(
            f"refused: open falsifiers {', '.join(broad)} select tests by name; replace"
            " each broad selector with an exact node id",
            file=sys.stderr,
        )
        return 1
    if not named:
        print(f"checked open falsifiers in {work}")
        return 0
    collected, failure = collected_ids()
    if failure:  # UNCOLLECTABLE is not STALE: do not blame records for a broken suite
        print(
            f"refused: pytest could not collect, so no node id was checked:\n{failure}",
            file=sys.stderr,
        )
        return 2
    if stale := [(eid, nid) for eid, nid in named if not resolves(nid, collected)]:
        for eid, nid in stale:
            print(f"refused: {eid} names {nid}, which pytest no longer collects", file=sys.stderr)
        print(
            "a moved or renamed test leaves the id selecting nothing, so its falsifier"
            " fails for the wrong reason. The lead re-points the record with `work.py"
            " resolve` at close, on the landed tree; a branch missing a node that landed"
            " on trunk merges trunk instead.",
            file=sys.stderr,
        )
        return 1
    print(f"checked open falsifiers in {work} ({len(named)} node ids resolve)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # A ROOT, not a work.md path, because corpus() reads root/work.md itself: a file
    # argument it ignored would report a clean scan of a file it never opened. Resolved
    # after parsing so --help needs neither a git repo nor XP_DATA.
    parser.add_argument("root", nargs="?", type=Path, help="data root holding work.md")
    parser.add_argument(
        "--scripts-dir",
        type=Path,
        default=ROOT / "tests" / "scripts",
        help="directory holding falsifier scripts",
    )
    parser.add_argument(
        "--skip-script-audit",
        action="store_true",
        help="check script ownership without executing live script commands",
    )
    args = parser.parse_args()
    root = args.root or data_root()
    work = root / "work.md"
    if not work.exists():
        print(f"scanned nothing: {work} is absent")
        return 0
    try:
        records = list(corpus(root))
    except OSError as exc:
        print(f"refused: cannot read {work}: {exc}", file=sys.stderr)
        return 2
    if script_correspondence(records, args.scripts_dir):
        return 1
    if status := check_node_ids(records, work):
        return status
    if not args.skip_script_audit:
        return audit_scripts(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
