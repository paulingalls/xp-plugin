"""story-010: size-ratchet. Verify: pytest -q tests/test_ratchet.py"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
RATCHET = REPO_ROOT / "plugins" / "xp-plugin" / "scripts" / "ratchet.py"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
SYSTEM_MD = REPO_ROOT / ".xp" / "system.md"
LEFTHOOK = REPO_ROOT / "lefthook.yml"
README = REPO_ROOT / "README.md"
DESIGN = REPO_ROOT / "docs" / "DESIGN.md"

# Matches the budget SHAPE: some label, then <= a number — e.g. "close ≤1,100",
# "Python ≤5,000 lines", "skill prose ≤3,000 words". Must NOT match
# "Python 3.11+" (no ≤), so a stray version string never trips this.
BUDGET_NUMBER_SHAPE = re.compile(r"[A-Za-z][A-Za-z+/ ]*≤\s*[\d,]+")


def run_ratchet(root=None):
    args = [sys.executable, str(RATCHET)]
    if root is not None:
        args += ["--root", str(root)]
    return subprocess.run(args, capture_output=True, text=True)


def build_scripts_tree(tmp_path, files):
    scripts_dir = tmp_path / "plugins" / "xp-plugin" / "scripts"
    scripts_dir.mkdir(parents=True)
    for name, content in files.items():
        path = scripts_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def violation_lines(stdout):
    """Only the EXCEEDED lines. The table prints every component name, every cap
    and the word `density` unconditionally, so asserting against whole stdout
    passes against a ratchet whose violation messages say nothing (measured:
    gutting both messages left all six tests green)."""
    return [ln for ln in stdout.splitlines() if "EXCEEDED" in ln]


def test_real_repo_within_budget_exits_zero_and_prints_table():
    """The four printed numbers must ACCOUNT for every shipped line — asserting
    only that the labels appear passes against a table of caps, of zeros, or of
    the cached constant the story exists to replace."""
    result = run_ratchet()
    assert result.returncode == 0, result.stdout + result.stderr
    for label in ("spawn", "close", "hooks", "misc"):
        assert label in result.stdout.lower(), result.stdout
    shipped = sum(
        len(p.read_text().splitlines())
        for p in RATCHET.parent.rglob("*.py")
        if "__pycache__" not in p.parts
    )
    printed = re.findall(r"^(?:spawn|close|hooks|misc)\s+(\d+)\s", result.stdout, re.M)
    assert sum(int(n) for n in printed) == shipped, result.stdout


def test_extracted_subpackage_counts_against_its_component(tmp_path):
    """Constraint 8 hard-caps a file at 500 lines, so a component's growth path is
    close.py -> close/. Scanning one directory level certified a tree with 3,000
    lines of close sitting one directory down (measured: exit 0)."""
    files = {"setup.py": "x = 1\n", "close/big.py": "x = 1\n" * 1300}
    root = build_scripts_tree(tmp_path, files)  # setup.py so the empty-tree refusal cannot mask it
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    (violation,) = violation_lines(result.stdout)
    assert "close" in violation, violation
    assert "over by 50" in violation, violation


def test_fixture_over_spawn_budget_reds_naming_budget_and_overage(tmp_path):
    padded = "x = 1\n" * 2100
    root = build_scripts_tree(tmp_path, {"spawn.py": padded})
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    (violation,) = violation_lines(result.stdout)
    assert "spawn" in violation, violation
    assert "cap 2000" in violation, violation
    assert "over by 100" in violation, violation


def test_fixture_dense_comments_reds_naming_density_and_file(tmp_path):
    lines = ["# comment line\n"] * 90 + ["x = 1\n"] * 10
    root = build_scripts_tree(tmp_path, {"chatty.py": "".join(lines)})
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    (violation,) = violation_lines(result.stdout)
    assert "DENSITY EXCEEDED" in violation, violation
    assert "90.00%" in violation, violation
    assert "chatty.py" in violation, violation


def test_density_is_the_aggregate_not_the_worst_file(tmp_path):
    """One chatty small file does not breach a repo that is overwhelmingly code.
    DESIGN §9 budgets the ratio of shipped Python, not of any single file, and the
    single-file fixture above passes against a per-file implementation too."""
    root = build_scripts_tree(
        tmp_path,
        {"chatty.py": "# comment\n" * 9 + "x = 1\n", "bulk.py": "x = 1\n" * 200},
    )
    result = run_ratchet(root)
    assert result.returncode == 0, result.stdout
    assert "chatty.py" in result.stdout, result.stdout  # still named as worst


def test_empty_scripts_tree_refuses_rather_than_certifying(tmp_path):
    root = build_scripts_tree(tmp_path, {})
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    assert "MEASURED NOTHING" in result.stdout, result.stdout


def test_design_sub_allocation_matches_ratchet_constants():
    """DESIGN §9 states the sub-allocation in prose and ratchet.py holds it in code.
    Bug c2d7ffdf was exactly this drift, between copies nobody could run."""
    stated = re.search(
        r"spawn CLI ≤ ([\d,]+) · close component ≤ ([\d,]+) · "
        r"hooks \+ both harness adapters ≤ ([\d,]+) · scaffolding/validators/misc ≤ ([\d,]+)",
        DESIGN.read_text(),
    )
    assert stated, "DESIGN §9's sub-allocation sentence no longer parses"
    sys.path.insert(0, str(RATCHET.parent))
    try:
        import ratchet

        assert [int(n.replace(",", "")) for n in stated.groups()] == [
            ratchet.SPAWN,
            ratchet.CLOSE,
            ratchet.HOOKS,
            ratchet.MISC,
        ]
    finally:
        sys.path.remove(str(RATCHET.parent))


def test_subbudgets_sum_to_total():
    sys.path.insert(0, str(RATCHET.parent))
    try:
        import ratchet

        assert ratchet.SPAWN + ratchet.CLOSE + ratchet.HOOKS + ratchet.MISC <= ratchet.TOTAL
    finally:
        sys.path.remove(str(RATCHET.parent))


def test_lefthook_pre_push_runs_ratchet():
    text = LEFTHOOK.read_text()
    pre_push = text.split("pre-push:", 1)[1]
    assert "ratchet.py" in pre_push


def test_no_budget_number_shape_in_the_injected_prose():
    for path in (CLAUDE_MD, SYSTEM_MD, README):
        matches = BUDGET_NUMBER_SHAPE.findall(path.read_text())
        assert not matches, f"{path}: {matches}"
