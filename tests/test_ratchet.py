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
        (scripts_dir / name).write_text(content)
    return tmp_path


def test_real_repo_within_budget_exits_zero_and_prints_table():
    result = run_ratchet()
    assert result.returncode == 0, result.stdout + result.stderr
    for label in ("spawn", "close", "hooks", "misc"):
        assert label in result.stdout.lower(), result.stdout


def test_fixture_over_spawn_budget_reds_naming_budget_and_overage(tmp_path):
    padded = "x = 1\n" * 2100
    root = build_scripts_tree(tmp_path, {"spawn.py": padded})
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    assert "spawn" in result.stdout.lower()
    assert "2000" in result.stdout or "2,000" in result.stdout
    assert "100" in result.stdout  # overage: 2100 - 2000


def test_fixture_dense_comments_reds_naming_density_and_file(tmp_path):
    lines = ["# comment line\n"] * 90 + ["x = 1\n"] * 10
    root = build_scripts_tree(tmp_path, {"chatty.py": "".join(lines)})
    result = run_ratchet(root)
    assert result.returncode != 0, result.stdout
    assert "density" in result.stdout.lower()
    assert "chatty.py" in result.stdout


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


def test_no_budget_number_shape_in_claude_md_or_system_md():
    for path in (CLAUDE_MD, SYSTEM_MD):
        matches = BUDGET_NUMBER_SHAPE.findall(path.read_text())
        assert not matches, f"{path}: {matches}"
