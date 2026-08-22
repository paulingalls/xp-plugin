"""Shared fixtures for the test_sprint_close family.
Split at sprint-004 open: tests are production code (constraint 8)."""

import json
import subprocess
import sys
from pathlib import Path

from close_helpers import launches, stub_reviewer  # noqa: F401

CLOSE = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "close.py"

WORK = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "work.py"

PLUGIN = Path(__file__).parent.parent / "plugins" / "xp-plugin"

PLAN = """# plan
## Milestone 1
### Sprint 2 — the one under test
#### story-042 — done thing   [done]
Verify: true
#### story-043 — also done   [done]
Verify: true

### Sprint 3
#### story-099 — not this sprint   [ready]
Verify: true
"""

CONFIG = (
    "release: sprint\nsprint_branch: sprint-002\n"
    "roles:\n  reviewer: claude/opus\ntests:\n  full: true\n"
)

WORK_SECTION = "work.md entries filed during the sprint"


def make_repo(tmp_path, plan=PLAN, config=CONFIG):
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{stub_reviewer(tmp_path)}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "data"),
    }
    g = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True
    )
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    state_plan = tmp_path / "data" / "plan.md"
    state_plan.parent.mkdir(parents=True, exist_ok=True)
    state_plan.write_text(plan)
    (repo / ".xp" / "config.yml").write_text(config)
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    (repo / ".xp" / "system.md").write_text("# System\nSYSTEM-SENTINEL\n")
    (repo / "src.py").write_text("A = 1\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "sprint-002")
    # the sprint's own work, absent from the default branch: under `release:
    # sprint` an integration_target() diff would not carry it
    (repo / "src.py").write_text("A = 1\nB = 'SPRINT-ONLY-SENTINEL'\n")
    g("add", "-A")
    g("commit", "-qm", "story work on the sprint branch")
    return repo, env, g


def sprint(repo, env, *args, sprint_id="2"):
    return subprocess.run(
        [sys.executable, str(CLOSE), "sprint", sprint_id, *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def head(repo, env):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
    ).stdout.strip()


def marker_path(tmp_path, lens, sprint_id="2"):
    return tmp_path / "data" / "markers" / "sprint" / f"{sprint_id}.{lens}.json"


def record_reviews(tmp_path, repo, env, blocking=(), lenses=("broad", "security")):
    """CONSTRUCT the state a real review leaves, so land's guard is exercised
    against markers rather than against the absence of them."""
    for lens in lenses:
        path = marker_path(tmp_path, lens)
        path.parent.mkdir(parents=True, exist_ok=True)
        round_ = {"fixed": [], "blocking": list(blocking), "noted": []}
        path.write_text(json.dumps({"rounds": [round_], "shown_sha": head(repo, env)}))


def work(repo, env, *args):
    return subprocess.run(
        [sys.executable, str(WORK), *args], cwd=repo, env=env, capture_output=True, text=True
    )


def snapshot(root: Path):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def section(bundle, title, until):
    """A named section's body. Sliced between two titles rather than split on a
    blank-line-plus-`## ` boundary, because the raw work.md section carries
    `## note` headings of its own and would cut itself in half."""
    head = f"## {title}\n\n"
    start = bundle.index(head) + len(head)
    return bundle[start : bundle.index(f"## {until}\n\n", start)]


def committing_stub(tmp_path, body):
    """A stub that writes a valid report and then moves the tree. A stub that
    never moves it certifies nothing (constraint 2)."""
    bin_dir = stub_reviewer(tmp_path)
    claude = bin_dir / "claude"
    claude.write_text(claude.read_text().replace("sys.stdout.write(", body + "\nsys.stdout.write("))
    claude.chmod(0o755)
    return bin_dir
