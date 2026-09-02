#!/usr/bin/env python3
"""Refuse this repository's open falsifiers that select tests by name."""

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins/xp-plugin/scripts"))

from env import data_root  # noqa: E402
from sprint_close import corpus  # noqa: E402


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # A ROOT, not a work.md path, because corpus() reads root/work.md itself: a file
    # argument it ignored would report a clean scan of a file it never opened. Resolved
    # after parsing so --help needs neither a git repo nor XP_DATA.
    parser.add_argument("root", nargs="?", type=Path, help="data root holding work.md")
    args = parser.parse_args()
    root = args.root or data_root()
    work = root / "work.md"
    if not work.exists():
        print(f"scanned nothing: {work} is absent")
        return 0
    try:
        records = list(corpus(root))
        broad = [eid for eid, _h, command, _c in records if selects_broadly(command)]
        named = [(eid, nid) for eid, _h, command, _c in records for nid in node_ids(command)]
    except OSError as exc:
        print(f"refused: cannot read {work}: {exc}", file=sys.stderr)
        return 2
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
            "a moved or renamed test leaves the id green-by-absence: pytest exits 5 on"
            " no match. Re-point the record with `work.py resolve`.",
            file=sys.stderr,
        )
        return 1
    print(f"checked open falsifiers in {work} ({len(named)} node ids resolve)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
