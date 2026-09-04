"""The 3.11 floor refuses by name, and does so on every shipped entry point.

Verify: pytest -q -n auto tests/test_interpreter_floor.py

12 of 13 shipped scripts traceback on 3.9 — `str | None` is evaluated at def time
there — and `python3` on a stock mac IS 3.9 (note 1e7b1197). README says 3.11+;
nothing enforced it, so a consuming project met a TypeError naming nothing. env.py
is the guard's home because it is the one module free of those annotations, so the
floor speaks for an entry point only if that entry point's imports REACH env before
any annotated module's body finishes. Measured false for plan_review.py, which
imported review.py first and tracebacked exactly as before the guard existed.
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"
MODULES = {p.stem: p for p in SCRIPTS.rglob("*.py")}
ENTRY_POINTS = sorted(n for n, p in MODULES.items() if '__name__ == "__main__"' in p.read_text())


def imports(module):
    """First-party imports, TOP LEVEL only: a function-local one runs after the
    annotations it would have to precede, so it buys the floor nothing."""
    found = []
    for node in ast.parse(MODULES[module].read_text()).body:
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name in MODULES]
        elif isinstance(node, ast.ImportFrom) and node.module in MODULES:
            found.append(node.module)
    return found


def annotated(module):
    """Carries a PEP-604 annotation — what 3.9 evaluates, and dies on, at def time."""
    for node in ast.walk(ast.parse(MODULES[module].read_text())):
        ann = getattr(node, "annotation", None) or getattr(node, "returns", None)
        if ann and any(
            isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(ann)
        ):
            return True
    return False


def execution_order(module, seen=None, order=None):
    """Module bodies in the order they FINISH: `import x` runs x to completion
    before the importer reaches its own defs, so this is the order the 3.9
    TypeErrors would fire in — and the order the refusal has to win."""
    seen, order = (set() if seen is None else seen), ([] if order is None else order)
    if module in seen:
        return order
    seen.add(module)
    for dep in imports(module):
        execution_order(dep, seen, order)
    order.append(module)
    return order


def test_the_measurement_is_not_of_nothing():
    """An empty parametrize passes, and a pass here certifies (constraint 2)."""
    assert {"spawn", "plan_review", "session_start", "setup", "work"} <= set(ENTRY_POINTS)


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_the_floor_speaks_before_any_annotation_is_evaluated(entry):
    order = execution_order(entry)
    assert "env" in order, f"{entry}.py imports nothing that reaches the floor guard"
    dies = [m for m in order if annotated(m)]
    if dies:
        assert order.index("env") < order.index(dies[0]), (
            f"{entry}.py runs {dies[0]}.py before env.py, so on 3.9 it tracebacks on"
            f" `X | None` instead of naming the interpreter it needs"
        )


class TestGuard:
    def test_an_old_interpreter_is_refused_by_name(self, monkeypatch):
        monkeypatch.setattr(sys, "version_info", (3, 9, 6, "final", 0))
        sys.modules.pop("env", None)
        try:
            with pytest.raises(SystemExit) as raised:
                importlib.import_module("env")
            said = str(raised.value)
            assert "3.9" in said and "3.11" in said, said
        finally:
            monkeypatch.undo()
            sys.modules.pop("env", None)
            importlib.import_module("env")
