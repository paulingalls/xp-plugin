"""story-010: size-ratchet. Verify: pytest -q tests/test_ratchet.py"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugins" / "xp-plugin"
RATCHET = REPO_ROOT / "tests" / "scripts" / "ratchet.py"
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


def build_plugin_tree(tmp_path, files):
    """Keys are relative to the plugin root, not to scripts/ — the budget covers
    every directory of the shipped plugin and the fixtures have to be able to
    say so."""
    plugin_dir = tmp_path / "plugins" / "xp-plugin"
    plugin_dir.mkdir(parents=True)
    for name, content in files.items():
        path = plugin_dir / name
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
        for p in PLUGIN_ROOT.rglob("*.py")
        if "__pycache__" not in p.parts
    )
    printed = re.findall(r"^(?:spawn|close|hooks|misc)\s+(\d+)\s", result.stdout, re.M)
    assert sum(int(n) for n in printed) == shipped, result.stdout


def _budgets():
    """ratchet's own constants — so moving a cap under constraint 1 does not red a
    test that was only ever asserting the OVERAGE arithmetic."""
    sys.path.insert(0, str(RATCHET.parent))
    try:
        import ratchet

        return ratchet
    finally:
        sys.path.remove(str(RATCHET.parent))


def test_extracted_subpackage_counts_against_its_component(tmp_path):
    """Constraint 8 hard-caps a file at 500 lines, so a component's growth path is
    close.py -> close/. Scanning one directory level certified a tree with 3,000
    lines of close sitting one directory down (measured: exit 0)."""
    over = _budgets().CLOSE + 50  # derived, never a literal: a cap move must not red this
    files = {"scripts/setup.py": "x = 1\n", "scripts/close/big.py": "x = 1\n" * over}
    root = build_plugin_tree(tmp_path, files)  # setup.py so the empty-tree refusal cannot mask it
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    (violation,) = [v for v in violation_lines(result.stdout) if "BUDGET" in v]
    assert "close" in violation, violation
    assert "over by 50" in violation, violation


def test_the_spawn_leg_extracted_to_a_leaf_still_counts_against_spawn(tmp_path):
    """Constraint 8's other growth path: a component too big for one file sheds a
    LEAF module, not a subpackage — story-017 cut spawn.py's tee loop out to
    scripts/teammate_tee.py. Charging that to misc understates the component it
    was cut from and spends a budget it does not belong to."""
    files = {"scripts/spawn.py": "x = 1\n" * 401, "scripts/teammate_tee.py": "x = 1\n" * 400}
    root = build_plugin_tree(tmp_path, files)
    result = run_ratchet(root)
    rows = dict(ln.split()[:2] for ln in result.stdout.splitlines()[1:5])
    assert rows["spawn"] == "801", result.stdout
    assert rows["misc"] == "0", result.stdout
    assert result.returncode == 0, result.stdout  # 801 fits spawn's cap; 800 blows misc's 750


def test_python_outside_scripts_counts_against_its_component(tmp_path):
    """The budget is the shipped plugin's Python, not one directory of it. The
    Codex adapter and the per-harness hooks land beside scripts/, and a scan
    rooted there printed an unchanged table and exited 0 over 3,400 lines sitting
    in plugins/xp-plugin/adapters/ and plugins/xp-plugin/hooks/ (measured)."""
    files = {
        "scripts/setup.py": "x = 1\n",
        "adapters/codex.py": "x = 1\n" * 800,
        "hooks/codex_hook.py": "x = 1\n" * 1100,
    }
    root = build_plugin_tree(tmp_path, files)
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    violations = "\n".join(violation_lines(result.stdout))
    assert "hooks measured 1100" in violations, violations
    assert "misc measured 801" in violations, violations


def test_fixture_over_spawn_budget_reds_naming_budget_and_overage(tmp_path):
    cap = _budgets().SPAWN
    root = build_plugin_tree(tmp_path, {"scripts/spawn.py": "x = 1\n" * (cap + 100)})
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    (violation,) = [v for v in violation_lines(result.stdout) if "BUDGET" in v]
    assert "spawn" in violation, violation
    assert f"cap {cap}" in violation, violation
    assert "over by 100" in violation, violation


def test_a_test_file_over_the_cap_reds_naming_the_file(tmp_path):
    """Tests are production code (Paul, sprint-004 open): constraint 8's hard cap
    binds tests/ equally — this repo reached 2,059 lines in one test file with no
    counter-pressure, because the ratchet measured only the shipped plugin."""
    root = build_plugin_tree(tmp_path, {"scripts/setup.py": "x = 1\n"})
    (root / "tests").mkdir()
    (root / "tests" / "test_big.py").write_text("x = 1\n" * 600)
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    (violation,) = [v for v in violation_lines(result.stdout) if "FILE CAP" in v]
    assert "test_big.py" in violation, violation
    assert "over by 100" in violation, violation


def test_a_shipped_file_over_the_cap_reds_the_same_way(tmp_path):
    """One rule, both implementations — asymmetric enforcement is the
    rule-fixed-in-one-of-two-copies defect this sprint's bug batch closed twice."""
    root = build_plugin_tree(tmp_path, {"scripts/setup.py": "x = 1\n" * 501})
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    assert any("FILE CAP" in v and "setup.py" in v for v in violation_lines(result.stdout)), (
        result.stdout
    )


def test_a_grandfathered_file_may_only_shrink(tmp_path):
    """The pin is the CURRENT size, not a license: growth past it reds even while
    the file is over the ordinary cap."""
    ratchet = _budgets()
    root = build_plugin_tree(tmp_path, {"scripts/setup.py": "x = 1\n"})
    (root / "tests").mkdir()
    (root / "tests" / "test_big.py").write_text("x = 1\n" * 601)
    old = ratchet.GRANDFATHER
    try:
        ratchet.GRANDFATHER = {"tests/test_big.py": 600}
        _table, violations = ratchet.report(root)
        assert any("FILE CAP" in v and "over by 1" in v for v in violations), violations
        (root / "tests" / "test_big.py").write_text("x = 1\n" * 600)
        _table, violations = ratchet.report(root)
        assert not violations, violations
    finally:
        ratchet.GRANDFATHER = old


def test_a_stale_grandfather_pin_reds_so_it_is_deleted(tmp_path):
    """A pin whose file is back under the cap is dead config that would later
    license regrowth to the pinned size — the ratchet's only-ever-lowers rule,
    applied to its own exceptions."""
    ratchet = _budgets()
    root = build_plugin_tree(tmp_path, {"scripts/setup.py": "x = 1\n"})
    (root / "tests").mkdir()
    (root / "tests" / "test_big.py").write_text("x = 1\n" * 100)
    old = ratchet.GRANDFATHER
    try:
        ratchet.GRANDFATHER = {"tests/test_big.py": 600}
        _table, violations = ratchet.report(root)
        assert any("STALE" in v and "test_big.py" in v for v in violations), violations
    finally:
        ratchet.GRANDFATHER = old


def test_fixture_dense_comments_reds_naming_density_and_file(tmp_path):
    lines = ["# comment line\n"] * 90 + ["x = 1\n"] * 10
    root = build_plugin_tree(tmp_path, {"scripts/chatty.py": "".join(lines)})
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
    root = build_plugin_tree(
        tmp_path,
        {"scripts/chatty.py": "# comment\n" * 9 + "x = 1\n", "scripts/bulk.py": "x = 1\n" * 200},
    )
    result = run_ratchet(root)
    assert result.returncode == 0, result.stdout
    assert "chatty.py" in result.stdout, result.stdout  # still named as worst


def test_empty_scripts_tree_refuses_rather_than_certifying(tmp_path):
    root = build_plugin_tree(tmp_path, {})
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


def test_design_names_the_directory_the_ratchet_scans():
    """DESIGN §9 states the density denominator's scope in prose and ratchet.py
    implements it — c2d7ffdf's drift one level up. Narrowing the scan back to
    scripts/ while §9 still said the whole plugin left 3,400 lines unmeasured."""
    sys.path.insert(0, str(RATCHET.parent))
    try:
        import ratchet

        scanned = ratchet.plugin_dir(REPO_ROOT).relative_to(REPO_ROOT).as_posix()
    finally:
        sys.path.remove(str(RATCHET.parent))
    assert f"`{scanned}/**`" in DESIGN.read_text()


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
