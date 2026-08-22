"""Shared fixtures for the test_spawn family.
Split at sprint-004 open: tests are production code (constraint 8)."""

import subprocess
import sys
from pathlib import Path

SPAWN = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "spawn.py"

CARD = """# plan
## Milestone 1
### Sprint 1
#### story-042 — demo story   [{status}]
Context: demo.
Files: src/thing.py
AC:
- Given X, When Y, Then Z
Verify: true
Executor: {executor}
"""

CONFIG = """release: sprint
sprint_branch: {trunk}

roles:
  lead: claude/opus
  executor: claude/sonnet/medium
  reviewer: claude/opus

tests:
  story: true
"""


def make_repo(tmp_path, status="ready", executor="(default)", trunk="main"):
    """A repo whose HEAD is NOT the integration target, with a divergent commit:
    a spawn that omits the base argument branches off HEAD and the test reds."""
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "data"),
    }
    g = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True
    )
    g("init", "-q", "-b", trunk)
    g("config", "user.email", "ada@example.com")
    g("config", "user.name", "Ada L")
    plan = tmp_path / "data" / "plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(CARD.format(status=status, executor=executor))
    (repo / ".xp" / "config.yml").write_text(CONFIG.format(trunk=trunk))
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    (repo / ".xp" / "system.md").write_text("# System\n- Worktree bootstrap: none needed\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "elsewhere")
    (repo / "drift.txt").write_text("HEAD is not the trunk\n")
    g("add", "-A")
    g("commit", "-qm", "divergent")
    return repo, env, g


def stub_claude(
    tmp_path, commit=True, emit_result=True, write_file=False, add_all=True, break_git=False
):
    """A fake `claude` that records argv, env and stdin, then (by default)
    commits its own "work" and emits a stream-json terminal result object —
    the shape of a clean, successful teammate run. The other three knobs
    produce the shapes TestTeammateCompletion's guard must catch:
    `write_file` alone leaves an UNCOMMITTED file (dirty tree); `commit=False,
    write_file=False` leaves the tree clean but with NO commit of its own —
    the two injections the completion guard's AC calls for.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launch.json"
    body = [
        "#!/usr/bin/env python3",
        "import json, os, subprocess, sys",
        "argv = sys.argv[1:]",
        "stdin = sys.stdin.read()",
        f"json.dump({{'argv': argv, 'env': dict(os.environ), 'stdin': stdin}},"
        f" open({str(rec)!r}, 'w'))",
    ]
    if write_file:
        body.append("open('teammate-left-this-uncommitted.txt', 'w').write('oops')")
    if commit:
        # add -A, not --allow-empty alone: a real teammate's "done" commit
        # picks up whatever it left in the tree, bootstrap byproducts included
        # — except with add_all=False, which is the teammate that stages only
        # its own files and leaves a pre-existing leftover where it found it
        if add_all:
            body.append("subprocess.run(['git', 'add', '-A'])")
        body.append("subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'teammate work'])")
    if break_git:
        body.append("open('.git', 'w').write('not a gitdir pointer')")
    if emit_result:
        body.append(
            "print(json.dumps({'type': 'result', 'num_turns': 3, 'duration_ms': 1200,"
            " 'total_cost_usd': 0.05, 'is_error': False}))"
        )
    (bin_dir / "claude").write_text("\n".join(body) + "\n")
    (bin_dir / "claude").chmod(0o755)
    return rec


def spawn(repo, env, *args):
    return subprocess.run(
        [sys.executable, str(SPAWN), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def trunk_sha(repo, env, trunk="main"):
    return subprocess.run(
        ["git", "rev-parse", f"refs/heads/{trunk}"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    ).stdout.strip()


def in_tree(tree, env, *args):
    return subprocess.run(
        ["git", *args], cwd=tree, env=env, capture_output=True, text=True
    ).stdout.strip()


def block_commits(repo):
    """A red pre-commit in the COMMON dir — worktrees share it, and lefthook
    installs exactly here, so this is the live configuration, not a contrivance."""
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'fast tests red' >&2\nexit 1\n")
    hook.chmod(0o755)


def set_system_md(repo, line):
    (repo / ".xp" / "system.md").write_text(f"# System\n{line}\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "system.md"],
        cwd=repo,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo.parent)},
    )


def stub_claude_requiring_verbose(tmp_path):
    """Mimics the REAL refusal measured at story-017's plan review: the
    installed `claude` binary exits 1 on `--output-format stream-json` without
    `--verbose`. `stub_claude` above accepts any argv, so only a stub shaped
    like this one can catch a regression back to the old, unshippable argv."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / "claude-real-refusal"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "argv = sys.argv[1:]\n"
        "if ('--output-format' in argv and argv[argv.index('--output-format') + 1] =="
        " 'stream-json' and '--verbose' not in argv):\n"
        "    print('error: --output-format stream-json requires --verbose', file=sys.stderr)\n"
        "    sys.exit(1)\n"
        'print(\'{"type": "result", "is_error": false, "num_turns": 1}\')\n'
    )
    path.chmod(0o755)
    return path


def _total(stdout):
    for ln in stdout.splitlines():
        if ln.startswith("profile:"):
            return int(ln.split("total ", 1)[1].split(" ", 1)[0])
    raise AssertionError(f"no profile line in: {stdout[:200]}")
