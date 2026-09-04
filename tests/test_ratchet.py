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

# Matches the budget SHAPE: some label, then <= a number — e.g. "close ≤1,100",
# "Python ≤5,000 lines", "skill prose ≤3,000 words". Must NOT match
# "Python 3.11+" (no ≤), so a stray version string never trips this.
BUDGET_NUMBER_SHAPE = re.compile(r"[A-Za-z][A-Za-z+/ ]*≤\s*[\d,]+")
SHRINK_CONSEQUENCE = (
    "a broken glob silently shrinks coverage while every component still reports under guideline"
)


def run_ratchet(root=None):
    args = [sys.executable, str(RATCHET)]
    if root is not None:
        args += ["--root", str(root)]
    return subprocess.run(args, capture_output=True, text=True)


def build_plugin_tree(tmp_path, files, tests=True, plugin_floor=True, test_floor=True):
    """Keys are relative to the plugin root, not to scripts/ — the report covers
    every directory of the shipped plugin and the fixtures have to be able to
    say so. `tests=False` builds the tree the ratchet must REFUSE to measure."""
    plugin_dir = tmp_path / "plugins" / "xp-plugin"
    plugin_dir.mkdir(parents=True)
    for name, content in files.items():
        path = plugin_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    ratchet = _ratchet()
    if plugin_floor:
        count = len(list(plugin_dir.rglob("*.py")))
        add_empty_files(plugin_dir / "scripts", ratchet.PLUGIN_FILE_FLOOR - count, "floor")
    if tests:
        (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
        (tmp_path / "tests" / "test_seed.py").write_text("def test_seed():\n    assert True\n")
        if test_floor:
            add_empty_files(tmp_path / "tests", ratchet.TEST_FILE_FLOOR - 1, "test_floor")
    return tmp_path


def add_empty_files(directory, count, stem, suffix=".py"):
    directory.mkdir(parents=True, exist_ok=True)
    for number in range(count):
        (directory / f"{stem}_{number}{suffix}").write_text("")


def _chunks(total):
    return [500] * (total // 500) + ([total % 500] if total % 500 else [])


def violation_lines(stdout):
    """Only the structural EXCEEDED lines, excluding advisory table rows."""
    return [ln for ln in stdout.splitlines() if "EXCEEDED" in ln]


def test_real_repo_exits_zero_and_prints_table():
    """The four printed numbers must ACCOUNT for every shipped line — asserting
    only that the labels appear passes against a table of guidelines, zeros, or
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


def _ratchet():
    sys.path.insert(0, str(RATCHET.parent))
    try:
        import ratchet

        return ratchet
    finally:
        sys.path.remove(str(RATCHET.parent))


def test_every_named_component_member_reports_to_its_component():
    ratchet = _ratchet()
    expected = {
        "spawn": {"spawn", "teammate_tee"},
        "close": {"close", "review", "bookkeep", "sprint_close"},
        "hooks": {"hooks", "session_start", "stop_gate", "bash_status"},
    }
    for component, names in expected.items():
        for name in names:
            assert ratchet.component_for(Path("scripts") / f"{name}.py") == component


def test_extracted_subpackage_counts_against_its_component(tmp_path):
    """Constraint 8 hard-caps a file at 500 lines, so a component's growth path is
    close.py -> close/. Scanning one directory level certified a tree with 3,000
    lines of close sitting one directory down (measured: exit 0)."""
    guideline = _ratchet().CLOSE_GUIDELINE
    measured = guideline + 50
    files = {"scripts/setup.py": "x = 1\n"}
    files.update(
        {f"scripts/close/part_{i}.py": "x = 1\n" * n for i, n in enumerate(_chunks(measured))}
    )
    root = build_plugin_tree(tmp_path, files)  # setup.py so the empty-tree refusal cannot mask it
    result = run_ratchet(root)
    assert result.returncode == 0, result.stdout
    assert re.search(rf"^close\s+{measured}\s+{guideline}$", result.stdout, re.M)


def test_the_spawn_leg_extracted_to_a_leaf_still_counts_against_spawn(tmp_path):
    """Constraint 8's other growth path: a component too big for one file sheds a
    LEAF module, not a subpackage — story-017 cut spawn.py's tee loop out to
    scripts/teammate_tee.py. Charging that to misc understates the component it
    was cut from and misreports that component."""
    files = {"scripts/spawn.py": "x = 1\n" * 401, "scripts/teammate_tee.py": "x = 1\n" * 400}
    root = build_plugin_tree(tmp_path, files)
    result = run_ratchet(root)
    rows = dict(ln.split()[:2] for ln in result.stdout.splitlines()[1:5])
    assert rows["spawn"] == "801", result.stdout
    assert rows["misc"] == "0", result.stdout
    assert result.returncode == 0, result.stdout


def test_python_outside_scripts_counts_against_its_component(tmp_path):
    """The report covers the shipped plugin's Python, not one directory of it. The
    Codex adapter and the per-harness hooks land beside scripts/, and a scan
    rooted there printed an unchanged table and exited 0 over 3,400 lines sitting
    in plugins/xp-plugin/adapters/ and plugins/xp-plugin/hooks/ (measured)."""
    guidelines = _ratchet()
    misc_lines = guidelines.MISC_GUIDELINE + 50
    hook_lines = guidelines.HOOKS_GUIDELINE + 100
    files = {"scripts/setup.py": "x = 1\n"}
    files.update(
        {f"adapters/part_{i}.py": "x = 1\n" * n for i, n in enumerate(_chunks(misc_lines))}
    )
    files.update({f"hooks/part_{i}.py": "x = 1\n" * n for i, n in enumerate(_chunks(hook_lines))})
    root = build_plugin_tree(tmp_path, files)
    result = run_ratchet(root)
    assert result.returncode == 0, result.stdout
    assert re.search(rf"^hooks\s+{hook_lines}\s+{guidelines.HOOKS_GUIDELINE}$", result.stdout, re.M)
    assert re.search(
        rf"^misc\s+{misc_lines + 1}\s+{guidelines.MISC_GUIDELINE}$", result.stdout, re.M
    )


def test_fixture_over_spawn_guideline_reports_and_exits_zero(tmp_path):
    guideline = _ratchet().SPAWN_GUIDELINE
    measured = guideline + 100
    files = {
        f"scripts/spawn/part_{i}.py": "x = 1\n" * lines for i, lines in enumerate(_chunks(measured))
    }
    root = build_plugin_tree(tmp_path, files)
    result = run_ratchet(root)
    assert result.returncode == 0, result.stdout
    assert re.search(rf"^spawn\s+{measured}\s+{guideline}$", result.stdout, re.M)


def test_a_test_file_over_the_cap_reds_naming_the_file(tmp_path):
    """Tests are production code (Paul, sprint-004 open): constraint 8's hard cap
    binds tests/ equally — this repo reached 2,059 lines in one test file with no
    counter-pressure, because the ratchet measured only the shipped plugin."""
    root = build_plugin_tree(tmp_path, {"scripts/setup.py": "x = 1\n"})
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
    ratchet = _ratchet()
    root = build_plugin_tree(tmp_path, {"scripts/setup.py": "x = 1\n"})
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
    ratchet = _ratchet()
    root = build_plugin_tree(tmp_path, {"scripts/setup.py": "x = 1\n"})
    (root / "tests" / "test_big.py").write_text("x = 1\n" * 100)
    old = ratchet.GRANDFATHER
    try:
        ratchet.GRANDFATHER = {"tests/test_big.py": 600}
        _table, violations = ratchet.report(root)
        assert any("STALE" in v and "test_big.py" in v for v in violations), violations
    finally:
        ratchet.GRANDFATHER = old


def test_fixture_dense_comments_reports_and_exits_zero(tmp_path):
    guideline = f"{_ratchet().DENSITY_GUIDELINE:.2%}"  # derived: moving it is the lead's
    lines = ["# comment line\n"] * 90 + ["x = 1\n"] * 10
    root = build_plugin_tree(tmp_path, {"scripts/chatty.py": "".join(lines)})
    result = run_ratchet(root)
    assert result.returncode == 0, result.stdout
    assert re.search(rf"^density\s+90\.00%\s+{re.escape(guideline)}", result.stdout, re.M)
    assert "chatty.py" in result.stdout


def test_density_is_the_aggregate_not_the_worst_file(tmp_path):
    """One chatty small file does not breach a repo that is overwhelmingly code.
    THE PRINTED RATIO is what carries the claim now that density only reports:
    exit 0 no longer separates the two implementations, and a per-file ratchet
    still names chatty.py as worst — measured, `density = worst[0]` left every
    other arm in this file green."""
    comments, code, bulk = 9, 1, 200
    root = build_plugin_tree(
        tmp_path,
        {
            "scripts/chatty.py": "# comment\n" * comments + "x = 1\n" * code,
            "scripts/bulk.py": "x = 1\n" * bulk,
        },
    )
    result = run_ratchet(root)
    assert result.returncode == 0, result.stdout
    aggregate = f"{comments / (comments + code + bulk):.2%}"  # 90.00% per-file
    assert re.search(rf"^density\s+{re.escape(aggregate)}\s", result.stdout, re.M), result.stdout
    assert "chatty.py" in result.stdout, result.stdout  # still named as worst


def test_empty_scripts_tree_refuses_rather_than_certifying(tmp_path):
    root = build_plugin_tree(tmp_path, {}, plugin_floor=False)
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    assert "MEASURED NOTHING" in result.stdout, result.stdout


def sized_tree(tmp_path, plugin_py, test_py):
    """A tree whose two populations are set INDEPENDENTLY, so each floor test
    holds the other arm at its floor and only its own arm can be what refused."""
    root = build_plugin_tree(
        tmp_path, {"scripts/setup.py": "x = 1\n"}, plugin_floor=False, test_floor=False
    )
    add_empty_files(root / "plugins" / "xp-plugin" / "scripts", plugin_py - 1, "measured")
    add_empty_files(root / "tests", test_py - 1, "test_measured")  # test_seed.py is the first
    return root


def test_a_plugin_population_one_below_its_reviewed_floor_refuses(tmp_path):
    """The decoys are the point of AC3: a floor counting what merely EXISTS in
    the directory rather than what the walk consumes clears them and never
    fires — Legacy shipped exactly that, and it was decoration."""
    ratchet = _ratchet()
    root = sized_tree(tmp_path, ratchet.PLUGIN_FILE_FLOOR - 1, ratchet.TEST_FILE_FLOOR)
    add_empty_files(root / "plugins" / "xp-plugin" / "scripts", 30, "ignored", ".txt")
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    assert SHRINK_CONSEQUENCE in result.stdout, result.stdout
    assert "PLUGIN_FILE_FLOOR" in result.stdout, result.stdout


def test_a_test_population_one_below_its_reviewed_floor_refuses(tmp_path):
    ratchet = _ratchet()
    root = sized_tree(tmp_path, ratchet.PLUGIN_FILE_FLOOR, ratchet.TEST_FILE_FLOOR - 1)
    add_empty_files(root / "tests", 50, "ignored", ".txt")
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    assert SHRINK_CONSEQUENCE in result.stdout, result.stdout
    assert "TEST_FILE_FLOOR" in result.stdout, result.stdout


def test_a_tree_with_no_TESTS_refuses_rather_than_certifying(tmp_path):
    """Its twin, and the reason the plugin arm alone was not enough: constraint 8
    was amended to bind tests/ too, and the test side fell back to an empty list
    when the directory was absent — so the 500-line cap was enforced over ZERO
    files, in silence, while the table printed and the wall exited 0. The plugin
    side raises for exactly this reason ("a measurement of nothing must not read
    as a pass"); one rule, and it was fixed in one of its two implementations."""
    root = build_plugin_tree(tmp_path, {"scripts/setup.py": "x = 1\n"}, tests=False)
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    assert "MEASURED NOTHING" in result.stdout, result.stdout
    assert "tests" in result.stdout, result.stdout


def test_an_EMPTY_tests_directory_refuses_too(tmp_path):
    """A directory check greens here; only counting the files reds. The dir
    exists in every checkout, so `is_dir()` is the guard that never fires."""
    root = build_plugin_tree(tmp_path, {"scripts/setup.py": "x = 1\n"}, tests=False)
    (root / "tests").mkdir()
    assert run_ratchet(root).returncode != 0


def test_lefthook_pre_push_runs_story_tier_without_ratchet():
    text = LEFTHOOK.read_text()
    pre_push = text.split("pre-push:", 1)[1]
    full_tests = pre_push.split("    full-tests:\n", 1)[1].split("\n    ", 1)[0]
    assert "run_tier story" in full_tests
    assert "ratchet.py" not in pre_push


def test_no_budget_number_shape_in_the_injected_prose():
    for path in (CLAUDE_MD, SYSTEM_MD, README):
        matches = BUDGET_NUMBER_SHAPE.findall(path.read_text())
        assert not matches, f"{path}: {matches}"


def test_file_cap_violation_names_extraction(tmp_path):
    files = {"scripts/setup.py": "x = 1\n" * 501}
    out = run_ratchet(build_plugin_tree(tmp_path, files)).stdout
    assert "extract" in out, "the file-cap refusal never names constraint 8's move"
