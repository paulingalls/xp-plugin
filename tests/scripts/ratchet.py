#!/usr/bin/env python3
"""Size ratchet: measure shipped Python against the sub-budgets, red if over.

Sole holder of the sub-budget numbers in code; DESIGN §9 keeps the total and
the rationale (its pre-named reserve is empty), and test_ratchet pins its copy of
the sub-allocation to the constants below so the two cannot drift (bug c2d7ffdf
was that drift, between two prose copies nobody could run).

Usage: python3 ratchet.py [--root PATH]
"""

import argparse
import ast
import sys
import tokenize
from pathlib import Path

SPAWN = 1415
CLOSE = 2375
HOOKS = 535
MISC = 1175
TOTAL = 5500

CLOSE_NAMES = {"close", "review", "bookkeep", "sprint_close"}
HOOKS_NAMES = {"hooks", "session_start", "stop_gate", "bash_status"}
SPAWN_NAMES = {"spawn", "teammate_tee"}

DENSITY_THRESHOLD = 0.20
# Sized to what this walk consumes today (measured at story-033). Legal under
# constraint 11 because it counts a structurally enumerated set, never a name.
PLUGIN_FILE_FLOOR = 21
TEST_FILE_FLOOR = 45

# Tests are production code (constraint 8, amended at sprint-004 open): the
# 500-line hard cap binds tests/ exactly as it binds the shipped plugin.
# Pins are the CURRENT sizes of files caught over — they may only FALL, and a
# pin whose file is back under the cap reds until it is deleted. Empty since
# the sprint-004 split; the mechanism stays for the next file caught over.
FILE_CAP = 500
GRANDFATHER = {}


class NoScriptsFound(Exception):
    """A measurement of nothing must not read as a pass — it certifies (constraint 2)."""


class CoverageShrank(Exception):
    pass


def plugin_dir(root):
    return root / "plugins" / "xp-plugin"


def component_for(rel):
    """Every path part, not just the basename: constraint 8 caps a file at 500
    lines, so close.py -> close/ is the sanctioned growth path."""
    names = {part.removesuffix(".py") for part in rel.parts}
    if names & SPAWN_NAMES:
        return "spawn"
    if names & CLOSE_NAMES:
        return "close"
    if names & HOOKS_NAMES:
        return "hooks"
    return "misc"


def count_lines(path):
    return len(path.read_text().splitlines())


def comment_and_docstring_lines(path):
    text = path.read_text()
    lines = set()

    for tok in tokenize.generate_tokens(iter(text.splitlines(keepends=True)).__next__):
        if tok.type == tokenize.COMMENT:
            lines.add(tok.start[0])

    tree = ast.parse(text)
    docstring_owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, docstring_owners) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            end = first.end_lineno or first.lineno
            for lineno in range(first.lineno, end + 1):
                lines.add(lineno)

    return len(lines)


def measure(root):
    d = plugin_dir(root)
    paths = sorted(p for p in d.rglob("*.py") if "__pycache__" not in p.parts)
    if not paths:
        raise NoScriptsFound(d)
    if len(paths) < PLUGIN_FILE_FLOOR:
        raise CoverageShrank(d, "PLUGIN_FILE_FLOOR", len(paths))

    totals = {"spawn": 0, "close": 0, "hooks": 0, "misc": 0}
    total_lines = 0
    total_commented = 0
    worst = None  # (ratio, path) — diagnostic only, not the trigger

    for path in paths:
        n = count_lines(path)
        totals[component_for(path.relative_to(d))] += n
        total_lines += n

        commented = comment_and_docstring_lines(path)
        total_commented += commented

        ratio = commented / n if n else 0
        if worst is None or ratio > worst[0]:
            worst = (ratio, path)

    density = total_commented / total_lines if total_lines else 0

    tests_dir = root / "tests"
    test_paths = sorted(p for p in tests_dir.rglob("*.py") if "__pycache__" not in p.parts)
    if not test_paths:
        raise NoScriptsFound(tests_dir)  # constraint 8 binds tests; zero of them is not a pass
    if len(test_paths) < TEST_FILE_FLOOR:
        raise CoverageShrank(tests_dir, "TEST_FILE_FLOOR", len(test_paths))
    file_findings = []
    for path in paths + test_paths:
        rel = path.relative_to(root).as_posix()
        n = count_lines(path)
        cap = GRANDFATHER.get(rel, FILE_CAP)
        if n > cap:
            file_findings.append(("over", rel, n, cap))
        elif rel in GRANDFATHER and n <= FILE_CAP:
            file_findings.append(("stale", rel, n, cap))
    return totals, density, worst, file_findings


def report(root):
    totals, density, worst, file_findings = measure(root)
    budgets = {"spawn": SPAWN, "close": CLOSE, "hooks": HOOKS, "misc": MISC}
    lines = ["component   measured   cap"]
    violations = []

    for name in ("spawn", "close", "hooks", "misc"):
        measured, cap = totals[name], budgets[name]
        lines.append(f"{name:<10}  {measured:>6}   {cap}")
        if measured > cap:
            violations.append(
                f"BUDGET EXCEEDED: {name} measured {measured}, cap {cap}, over by {measured - cap}"
                "\n  fix by displacing equal weight in this component; or move budget"
                " between components (here + DESIGN §9, zero-sum, the human's call);"
                " or cut real surface, priced against what DESIGN §9 measures —"
                " never a gate, never a test"
            )

    worst_path = worst[1]
    lines.append(
        f"density     {density:>6.2%}   {DENSITY_THRESHOLD:.2%}  (worst file: {worst_path.name})"
    )
    if density > DENSITY_THRESHOLD:
        violations.append(
            f"DENSITY EXCEEDED: comments+docstrings {density:.2%} of shipped Python, "
            f"cap {DENSITY_THRESHOLD:.2%}, worst file {worst_path}"
            "\n  before deleting words: a comment carrying a checkable claim becomes a"
            " test (it leaves the ratio and rots loudly); one explaining WHAT becomes a"
            " rename; one restating the code just goes. Keep the why (constraint 9)"
        )

    for kind, rel, n, cap in file_findings:
        if kind == "over":
            violations.append(
                f"FILE CAP EXCEEDED: {rel} measured {n}, cap {cap}, over by {n - cap}"
                "\n  over-cap means extract, not scroll (constraint 8): shed a cohesive"
                " leaf module — component_for charges close/ and spawn leaf files to"
                " their component — and never delete tests to fit"
            )
        else:
            violations.append(
                f"GRANDFATHER STALE: {rel} measures {n} <= {FILE_CAP} — delete its pin"
            )

    return "\n".join(lines), violations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()

    try:
        table, violations = report(args.root)
    except NoScriptsFound as exc:
        print(f"MEASURED NOTHING: no *.py under {exc.args[0]} — the ratchet cannot certify")
        return 2
    except CoverageShrank as exc:
        directory, floor, measured = exc.args
        print(
            f"COVERAGE SHRANK under {directory}: a broken glob silently shrinks coverage"
            " while every component still reports under cap"
            f"\n  fix the glob; or, if files were deliberately deleted, lower {floor}"
            f" in tests/scripts/ratchet.py to the {measured} this walk consumed"
        )
        return 2

    print(table)
    if violations:
        print()
        for v in violations:
            print(v)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
