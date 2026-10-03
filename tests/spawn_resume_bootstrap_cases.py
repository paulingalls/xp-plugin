"""Interrupted-bootstrap takeover cases collected through test_spawn_resume.py."""

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from close_free_card_cases import add_free_card, checkout_free, commit_on_free
from close_helpers import free, free_repo
from spawn_helpers import SPAWN, spawn


class BootstrapLeftTreeCases:
    def test_a_bootstrap_left_tree_is_routed_through_a_successful_takeover(self, tmp_path):
        from test_spawn_resume import stub_takeover

        repo, env, g = free_repo(tmp_path)
        config = repo / ".xp" / "config.yml"
        config.write_text(
            config.read_text().replace("roles:\n", "roles:\n  executor: claude/sonnet/medium\n")
        )
        system = repo / ".xp" / "system.md"
        system.write_text("# System\n- Worktree bootstrap: `exit 9`\n")
        g("add", "-A")
        g("commit", "-qm", "configure executor and bootstrap")
        assert free(repo, env, "fix-typo", "start").returncode == 0
        _branch, key = checkout_free(g)
        add_free_card(env, key)
        commit_on_free(repo, g)
        g("checkout", "-q", "main")
        assert spawn(repo, env, "ready", key).returncode == 0

        failed = spawn(repo, env, key)
        tree = Path(env["XP_DATA"]) / "worktrees" / key
        marker = Path(env["XP_DATA"]) / "plans" / f"{key}.handoff.json"
        assert failed.returncode == 2 and tree.is_dir() and marker.exists(), (
            failed.stdout + failed.stderr
        )
        plain = spawn(repo, env, key)
        free_leg = free(tree, env, "fix-typo", "review")
        assert plain.returncode == free_leg.returncode == 2
        routes = [
            re.findall(r"`([^`]*spawn\.py resume[^`]*)`", result.stderr) for result in (plain,)
        ]
        assert all(len(route) == 1 for route in routes), [result.stderr for result in (plain,)]

        def run_action(command, cwd=repo):
            argv = shlex.split(command)
            if argv[0] == "spawn.py":
                argv[:1] = [sys.executable, str(SPAWN)]
            return subprocess.run(
                argv,
                cwd=cwd,
                env=env | {"XP_SPAWN_TEST": "1"},
                capture_output=True,
                text=True,
            )

        stub_takeover(tmp_path)
        taken = run_action(routes[0][0])
        assert taken.returncode == 0, taken.stderr
        assert tree.is_dir() and json.loads(marker.read_text())["state"] == "FINISHED"
