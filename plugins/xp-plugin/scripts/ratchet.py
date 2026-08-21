#!/usr/bin/env python3
"""Size ratchet: measure shipped Python against the sub-budgets, red if over.

Sole holder of the sub-budget numbers in code; DESIGN §9 keeps the total, the
rationale and the sacrificial-feature order, and test_ratchet pins its copy of
the sub-allocation to the constants below so the two cannot drift (bug c2d7ffdf
was that drift, between two prose copies nobody could run).

Usage: python3 ratchet.py [--root PATH]
"""

import argparse
import ast
import sys
import tokenize
from pathlib import Path

SPAWN = 2000
CLOSE = 1250
HOOKS = 1000
MISC = 750
TOTAL = 5000

CLOSE_NAMES = {"close", "review", "bookkeep", "sprint_close"}
HOOKS_NAMES = {"hooks", "session_start", "stop_gate", "bash_status"}
SPAWN_NAMES = {"spawn"}

DENSITY_THRESHOLD = 0.20


class NoScriptsFound(Exception):
    """A measurement of nothing must not read as a pass — it certifies (constraint 2)."""


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
    return totals, density, worst


def report(root):
    totals, density, worst = measure(root)
    budgets = {"spawn": SPAWN, "close": CLOSE, "hooks": HOOKS, "misc": MISC}
    lines = ["component   measured   cap"]
    violations = []

    for name in ("spawn", "close", "hooks", "misc"):
        measured, cap = totals[name], budgets[name]
        lines.append(f"{name:<10}  {measured:>6}   {cap}")
        if measured > cap:
            violations.append(
                f"BUDGET EXCEEDED: {name} measured {measured}, cap {cap}, over by {measured - cap}"
            )

    worst_path = worst[1]
    lines.append(
        f"density     {density:>6.2%}   {DENSITY_THRESHOLD:.2%}  (worst file: {worst_path.name})"
    )
    if density > DENSITY_THRESHOLD:
        violations.append(
            f"DENSITY EXCEEDED: comments+docstrings {density:.2%} of shipped Python, "
            f"cap {DENSITY_THRESHOLD:.2%}, worst file {worst_path}"
        )

    return "\n".join(lines), violations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()

    try:
        table, violations = report(args.root)
    except NoScriptsFound as exc:
        print(f"MEASURED NOTHING: no *.py under {exc.args[0]} — the ratchet cannot certify")
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
