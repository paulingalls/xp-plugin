"""story-007: spawn.py teammate launch. Verify: pytest -q tests/test_spawn.py"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"))

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
    (repo / ".xp" / "plan.md").write_text(CARD.format(status=status, executor=executor))
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


def stub_claude(tmp_path):
    """A fake `claude` that records argv, env and stdin — the launch contract is
    otherwise unpinned, and a teammate that cannot edit exits 0 with prose."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launch.json"
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'env': dict(os.environ),"
        f" 'stdin': sys.stdin.read()}}, open({str(rec)!r}, 'w'))\n"
    )
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


class TestLaunchContract:
    def test_argv_carries_model_effort_plugin_dir_and_permission_posture(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr
        argv = json.loads(rec.read_text())["argv"]
        assert "-p" in argv
        assert argv[argv.index("--model") + 1] == "sonnet"
        assert argv[argv.index("--effort") + 1] == "medium"
        # without --plugin-dir the teammate loads no hooks, agents or skills:
        # a worktree session applies no project-scoped marketplace enablement
        assert Path(argv[argv.index("--plugin-dir") + 1]).name == "xp-plugin"
        # headless denies tool permission by default -> prose-only teammate, exit 0.
        # bypass specifically: acceptEdits was MEASURED to deny `git add`/`git
        # commit`, so weaker modes lose the teammate's work rather than block it
        assert "--dangerously-skip-permissions" in argv
        # and no allow-list: measured to restrict nothing under bypass, so
        # shipping one would certify a bound that does not exist
        assert "--allowedTools" not in argv
        assert argv[argv.index("--output-format") + 1] == "json"

    def test_prompt_arrives_on_stdin_not_argv(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        launch = json.loads(rec.read_text())
        assert "CONSTRAINT-SENTINEL" in launch["stdin"]
        assert not any("CONSTRAINT-SENTINEL" in a for a in launch["argv"])

    def test_prompt_inlines_the_plugin_shipped_profile_not_paths_to_it(self, tmp_path):
        """AC 1. `_read` degraded to "(missing: ...)" rather than raising, so a
        moved or renamed shipped file yielded a teammate with no VALUES and no
        rules while every other assertion stayed green (constraints.md #2)."""
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        stdin = json.loads(rec.read_text())["stdin"]
        assert "Honesty > Courage > Simplicity" in stdin  # VALUES.md
        assert "never merge, never run" in stdin  # TEAMMATE.md
        assert "demo story" in stdin  # the card
        assert "CONSTRAINT-SENTINEL" in stdin  # constraints
        assert "(missing:" not in stdin  # generic: every shipped-path defect
        assert "{PLUGIN_ROOT}" not in stdin  # the escalation command is resolved

    def test_role_env_exported_so_teammate_does_not_get_the_lead_profile(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        assert json.loads(rec.read_text())["env"].get("XP_ROLE") == "teammate"


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


class TestWorktree:
    def test_worktree_branches_off_the_integration_target_not_head(self, tmp_path):
        """HEAD carries a divergent commit the trunk does not have, so a
        `worktree add` that omits the base argument reds here instead of
        passing because HEAD happened to be the trunk (constraints.md #2)."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        tree = tmp_path / "data" / "worktrees" / "story-042"
        assert tree.is_dir()
        assert not (tree / "drift.txt").exists()  # the divergent commit is absent
        assert trunk_sha(repo, env) in in_tree(tree, env, "log", "--format=%H")

    def test_branch_is_namespaced_per_identity_so_clones_cannot_collide(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        first = in_tree(
            tmp_path / "data" / "worktrees" / "story-042", env, "branch", "--show-current"
        )
        assert first == "ada/story-042-demo-story"

        other = tmp_path / "clone2"
        subprocess.run(["git", "clone", "-q", str(repo), str(other)], env=env, check=True)
        env2 = dict(env, XP_DATA=str(tmp_path / "data2"))
        for k, v in (("user.email", "grace@example.com"), ("user.name", "Grace H")):
            subprocess.run(["git", "config", k, v], cwd=other, env=env2, check=True)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=other, env=env2)
        assert spawn(other, env2, "story-042").returncode == 0
        second = in_tree(
            tmp_path / "data2" / "worktrees" / "story-042", env2, "branch", "--show-current"
        )
        assert second == "grace/story-042-demo-story"
        assert first != second

    def test_status_flip_is_committed_in_the_worktree(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        tree = tmp_path / "data" / "worktrees" / "story-042"
        assert "[in-progress]" in (tree / ".xp" / "plan.md").read_text()
        assert in_tree(tree, env, "status", "--porcelain") == ""
        # the lead's tree still reads [ready]: git is the memory, and the
        # reviewer sees the flip in the cumulative diff
        assert "[ready]" in (repo / ".xp" / "plan.md").read_text()

    def test_dry_run_creates_nothing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        r = spawn(repo, env, "story-042", "--dry-run")
        assert r.returncode == 0 and "--plugin-dir" in r.stdout
        assert not (tmp_path / "data" / "worktrees" / "story-042").exists()
        assert "story-042" not in in_tree(repo, env, "branch", "--list")


def block_commits(repo):
    """A red pre-commit in the COMMON dir — worktrees share it, and lefthook
    installs exactly here, so this is the live configuration, not a contrivance."""
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'fast tests red' >&2\nexit 1\n")
    hook.chmod(0o755)


class TestFlipFailure:
    """The flip commit runs the project's pre-commit wall. Swallowing its failure
    launches a teammate onto a branch whose plan.md still reads [ready], and
    close.py's refusal then lands only after the whole story is written — the
    exact cost flip_to_in_progress exists to avoid."""

    def test_failed_flip_refuses_and_does_not_launch(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        block_commits(repo)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "flip" in r.stderr.lower()
        assert not rec.exists()

    def test_failed_flip_in_place_names_the_recovery(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        block_commits(repo)
        r = spawn(repo, env, "story-042", "--in-place")
        assert r.returncode == 2 and "flip" in r.stderr.lower()
        assert "branch -D" in r.stderr  # cannot unwind: name the way out


class TestRefusals:
    def test_existing_worktree_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "already" in r.stderr

    def test_existing_branch_refused_when_the_worktree_is_gone(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        subprocess.run(
            [
                "git",
                "worktree",
                "remove",
                "--force",
                str(tmp_path / "data" / "worktrees" / "story-042"),
            ],
            cwd=repo,
            env=env,
            check=True,
        )
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "branch" in r.stderr

    def test_non_ready_story_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="done")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "ready" in r.stderr

    def test_codex_harness_refused_naming_sprint_3(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5/high")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "Sprint 3" in r.stderr


class TestExecutorResolution:
    def test_card_executor_beats_config(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="claude/opus/high")
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        argv = json.loads(rec.read_text())["argv"]
        assert argv[argv.index("--model") + 1] == "opus"
        assert argv[argv.index("--effort") + 1] == "high"

    def test_cli_override_beats_the_card(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="claude/opus/high")
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042", "claude/haiku").returncode == 0
        argv = json.loads(rec.read_text())["argv"]
        assert argv[argv.index("--model") + 1] == "haiku"
        assert "--effort" not in argv  # two-part spec: reviewer role shape (story-008)


def set_system_md(repo, line):
    (repo / ".xp" / "system.md").write_text(f"# System\n{line}\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "system.md"],
        cwd=repo,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo.parent)},
    )


class TestBootstrap:
    def test_backticked_command_runs_in_the_worktree(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: `touch bootstrapped`")
        assert spawn(repo, env, "story-042").returncode == 0
        assert (tmp_path / "data" / "worktrees" / "story-042" / "bootstrapped").exists()

    def test_prose_mentioning_a_backticked_path_does_not_execute(self, tmp_path):
        """The whole value must be one backticked command. Otherwise
        `none needed — see `docs/setup.md`` would execute docs/setup.md."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: none needed — see `touch pwned`")
        assert spawn(repo, env, "story-042").returncode == 0
        assert not (tmp_path / "data" / "worktrees" / "story-042" / "pwned").exists()

    def test_red_bootstrap_refuses_and_does_not_launch(self, tmp_path):
        """A teammate in a non-working tree is the silent-corrupting failure."""
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: `exit 3`")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "bootstrap" in r.stderr.lower()
        assert not rec.exists()  # nothing launched


class TestBudget:
    """(i) is a hard cap on prose WE ship. There is deliberately no assertion on
    the composed total: CLAUDE.md, constraints.md and the cards belong to the
    consuming project, and a plugin gate over prose we do not own would red on
    someone else's file."""

    def test_plugin_shipped_profile_within_cap(self):
        from spawn import PLUGIN_SHIPPED_CAP, component_metadata_chars, plugin_shipped_chars

        # inner cap FIRST: a newly added skill or agent must red THIS line, not
        # the total — otherwise the ratchet blames TEAMMATE.md for a defect that
        # is a new component shipping unbudgeted prose into every spawn
        components = component_metadata_chars() // 4
        assert components <= 300, (
            f"always-on component metadata is {components} tokens (cap 300) —"
            " a skill or agent grew; retire prose there, not in TEAMMATE.md"
        )
        shipped = plugin_shipped_chars() // 4
        assert shipped <= PLUGIN_SHIPPED_CAP, (
            f"plugin-shipped profile is {shipped} tokens (cap {PLUGIN_SHIPPED_CAP});"
            f" components account for {components}"
        )

    def test_composed_total_is_computed_not_printed(self, tmp_path):
        """A print-a-constant implementation passes 'it prints a total' forever."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        before = spawn(repo, env, "story-042", "--dry-run").stdout
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text().replace("Context: demo.", "Context: " + "x" * 4000))
        after = spawn(repo, env, "story-042", "--dry-run").stdout
        assert _total(before) != _total(after)
        assert _total(after) > _total(before)

    def test_printed_plugin_shipped_is_the_capped_quantity(self, tmp_path):
        """Two computations shipped under one name: the printed figure omitted
        templates/constraints.md, so a lead read ~300 tokens of headroom where
        the ratchet had 52 — the story-009 note's failure, in the instrument."""
        from spawn import PLUGIN_SHIPPED_CAP, plugin_shipped_chars

        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        out = spawn(repo, env, "story-042", "--dry-run").stdout
        assert f"plugin-shipped {plugin_shipped_chars() // 4}/{PLUGIN_SHIPPED_CAP}" in out

    def test_warning_names_the_largest_project_owned_contributor(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        quiet = spawn(repo, env, "story-042", "--dry-run")
        assert "over the" not in quiet.stderr

        (repo / ".xp" / "constraints.md").write_text("# Constraints\n" + "bloat\n" * 3000)
        loud = spawn(repo, env, "story-042", "--dry-run")
        assert "constraints.md" in loud.stderr and "over the" in loud.stderr
        assert loud.returncode == 0  # reports, never refuses: the project's tradeoff


def _total(stdout):
    for ln in stdout.splitlines():
        if ln.startswith("profile:"):
            return int(ln.split("total ", 1)[1].split(" ", 1)[0])
    raise AssertionError(f"no profile line in: {stdout[:200]}")


class TestInPlace:
    """The lead implementing a story solo (DESIGN §8) had NO branch-creation step:
    spawn made one only on the delegation path, so solo work landed straight on
    the sprint branch. close.py refuses to close from the trunk, but only after
    the whole story is written — and the recovery (branch + reset) is cheap only
    while nothing is pushed. Measured on story-007 itself."""

    def test_creates_the_story_branch_without_launching(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        r = spawn(repo, env, "story-042", "--in-place")
        assert r.returncode == 0, r.stderr
        assert not rec.exists()  # nothing launched: the lead does the work
        assert not (tmp_path / "data" / "worktrees" / "story-042").exists()
        assert in_tree(repo, env, "branch", "--show-current") == "ada/story-042-demo-story"
        assert "[in-progress]" in (repo / ".xp" / "plan.md").read_text()
        assert in_tree(repo, env, "status", "--porcelain") == ""

    def test_dry_run_creates_nothing(self, tmp_path):
        """--in-place dispatched BEFORE the dry-run check, so the one flag whose
        whole contract is "changes nothing" created a branch and a commit."""
        repo, env, _g = make_repo(tmp_path)
        before = in_tree(repo, env, "rev-parse", "HEAD")
        r = spawn(repo, env, "story-042", "--in-place", "--dry-run")
        assert r.returncode == 0 and "would create" in r.stdout
        assert in_tree(repo, env, "branch", "--show-current") == "elsewhere"
        assert in_tree(repo, env, "rev-parse", "HEAD") == before
        assert "[ready]" in (repo / ".xp" / "plan.md").read_text()

    def test_existing_branch_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert spawn(repo, env, "story-042", "--in-place").returncode == 0
        subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, env=env)
        r = spawn(repo, env, "story-042", "--in-place")
        assert r.returncode == 2 and "already exists" in r.stderr
        assert in_tree(repo, env, "branch", "--show-current") == "main"

    def test_dirty_tree_refused(self, tmp_path):
        """git worktree tolerates a dirty tree; switching branches in place does
        not — uncommitted work would ride onto the story branch unreviewed."""
        repo, env, _g = make_repo(tmp_path)
        (repo / "scratch.txt").write_text("uncommitted\n")
        r = spawn(repo, env, "story-042", "--in-place")
        assert r.returncode == 2 and "dirty" in r.stderr.lower()
        assert in_tree(repo, env, "branch", "--show-current") == "elsewhere"


def test_spawn_reaches_the_integration_target_only_through_close():
    """A filed debt (story-009 retires config.yml sprint_branch) rests on spawn
    never reading the key itself — a comment cannot rot loudly, a test can."""
    assert "sprint_branch" not in SPAWN.read_text()


class TestConfigRoleParsing:
    """Found by running close.py's review leg against this repo's real config."""

    def test_a_comment_on_the_roles_line_does_not_hide_every_role(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "roles:   # harness/model[/effort]; lead overrides per story\n"
            "  executor: claude/opus     # codex once the adapter ships\n"
        )
        stub_claude(tmp_path)
        r = spawn(repo, env, "story-042", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "--model opus" in r.stdout, r.stdout
