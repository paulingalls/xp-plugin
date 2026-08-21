"""story-007: spawn.py teammate launch. Verify: pytest -q tests/test_spawn.py"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

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
        # stream-json (not json) so the lead can see it live; the installed
        # binary REQUIRES --verbose alongside stream-json or it refuses to launch
        assert argv[argv.index("--output-format") + 1] == "stream-json"
        assert "--verbose" in argv

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


class TestAgentWallClock:
    """story-012b bounds the reviewer. cmd_spawn's launch call site has no
    except, so a bound there kills a running story with a traceback and abandons
    its worktree — the two legs must therefore stay bounded and unbounded."""

    def test_the_reviewer_is_bounded(self, monkeypatch, tmp_path):
        import spawn

        monkeypatch.setenv("XP_AGENT_TIMEOUT", "1")
        with pytest.raises(subprocess.TimeoutExpired):
            spawn.run_agent(
                ["/bin/sh", "-c", "sleep 5"], tmp_path, "", role="reviewer", capture=True
            )

    def test_the_teammate_launch_is_not(self, monkeypatch, tmp_path):
        """Bounding cmd_spawn's launch call site kills a running story and
        abandons its worktree, so the teammate no longer runs through
        run_agent (that path is reviewer-only) — it runs through
        teammate_tee.run_teammate, which this asserts is unbounded."""
        from teammate_tee import run_teammate

        monkeypatch.setenv("XP_AGENT_TIMEOUT", "1")
        rc = run_teammate(
            ["/bin/sh", "-c", 'sleep 3; echo \'{"type": "result", "is_error": false}\''],
            tmp_path,
            "",
            "story-042",
            tmp_path / "data",
        )
        assert rc == 0, "a teammate story legitimately outruns any wall clock"


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


class TestLiveTee:
    """teammate_tee.tee_stream is a pure function — no subprocess involved —
    so the pipe-blocking / deadlock behaviour it must have is trivial to
    fault-inject (constraints.md #2)."""

    def test_every_line_is_logged_verbatim(self):
        from teammate_tee import tee_stream

        lines = [
            '{"type": "system", "subtype": "init"}\n',
            "not json at all\n",
            '{"type": "result", "is_error": false, "num_turns": 1}\n',
        ]
        logged = []
        result = tee_stream(lines, logged.append, lambda _l: None)
        assert logged == lines
        assert result == {"type": "result", "is_error": False, "num_turns": 1}

    def test_unparseable_lines_are_skipped_not_erroring(self):
        from teammate_tee import tee_stream

        lines = ["garbage\n", '{"type": "result", "is_error": false}\n']
        result = tee_stream(lines, lambda _l: None, lambda _l: None)
        assert result == {"type": "result", "is_error": False}

    def test_a_stream_with_no_terminal_result_returns_none(self):
        """The ONLY error condition: everything else in this file is tolerated."""
        from teammate_tee import tee_stream

        result = tee_stream(['{"type": "system"}\n'], lambda _l: None, lambda _l: None)
        assert result is None

    def test_a_failed_run_is_not_reported_as_ok(self):
        """`is_error` is one of the four things the card asks the closing line to
        carry, and it is the only one a lead ACTS on. Gutting both renderings to
        a constant "ok" left the whole suite green — a teammate that failed was
        announced as a teammate that succeeded."""
        from teammate_tee import closing_line, summarize_event

        failed = {"type": "result", "is_error": True, "num_turns": 2}
        assert "ERROR" in closing_line("story-042", failed)
        assert "error" in summarize_event(failed)
        assert "ERROR" not in closing_line("story-042", dict(failed, is_error=False))
        assert "error" not in summarize_event(dict(failed, is_error=False))

    def test_a_log_write_failure_warns_but_does_not_stop_draining(self):
        """Fault-inject: a writer that reds on its second call. Every line must
        still reach it and the run must complete — ceasing to drain deadlocks a
        healthy child writing to a full pipe."""
        from teammate_tee import tee_stream

        lines = [f'{{"type": "system", "subtype": "{i}"}}\n' for i in range(4)]
        seen = []

        def flaky_write(line):
            seen.append(line)
            if len(seen) == 2:
                raise OSError("disk full")

        out = []
        result = tee_stream(lines, flaky_write, out.append)
        assert seen == lines  # every line still reached the writer
        assert any("warning" in o for o in out)  # the loop warned
        assert sum(o.startswith("[system]") for o in out) == 4  # the run completed
        assert result is None  # no result object in this fixture — consistent, not asserted-away


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


class TestStreamJsonRequiresVerbose:
    def test_stream_json_without_verbose_reds_against_the_real_refusal(self, tmp_path):
        claude = stub_claude_requiring_verbose(tmp_path)
        r = subprocess.run(
            [str(claude), "--output-format", "stream-json"], capture_output=True, text=True
        )
        assert r.returncode == 1 and "verbose" in r.stderr

    def test_the_teammates_actual_argv_greens_against_the_same_stub(self, tmp_path):
        from spawn import claude_argv

        claude = stub_claude_requiring_verbose(tmp_path)
        argv = claude_argv("sonnet", "medium", "stream-json")[1:]  # drop the "claude" argv[0]
        r = subprocess.run([str(claude), *argv], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_review_py_still_passes_json_untouched(self):
        """review.py's own argv is explicit ("json"), so this story must not
        have touched it into carrying --verbose it never asked for."""
        from spawn import claude_argv

        assert "--verbose" not in claude_argv("opus", "", "json")


class TestLiveLogDuringARun:
    def test_the_log_is_readable_while_the_teammate_is_still_running(self, tmp_path):
        """LIVE, the property the mid-stream-kill case below cannot reach: that
        one reads the log only after run_teammate returns, by which point the
        `with open(...)` has closed and flushed it — it greens with the per-line
        flush deleted. This one reads the log from a second thread while the
        child is still alive and blocked, so only a flushed write can satisfy it.
        """
        import threading
        import time

        from teammate_tee import log_path, run_teammate

        script = tmp_path / "slow.py"
        sentinel = tmp_path / "go"
        script.write_text(
            "import json, sys, time, pathlib\n"
            "print(json.dumps({'type': 'system', 'subtype': 'init'}))\n"
            "sys.stdout.flush()\n"
            f"while not pathlib.Path({str(sentinel)!r}).exists(): time.sleep(0.01)\n"
            "print(json.dumps({'type': 'result', 'is_error': False, 'num_turns': 1}))\n"
        )
        run = threading.Thread(
            target=run_teammate,
            args=([sys.executable, str(script)], tmp_path, "", "story-live", tmp_path / "data"),
            kwargs={"out": lambda _l: None},
        )
        run.start()
        log = log_path(tmp_path / "data", "story-live")
        mid = ""
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and '"subtype": "init"' not in mid:
            mid = log.read_text() if log.exists() else ""
            time.sleep(0.02)
        sentinel.write_text("go")
        run.join(30)
        assert '"subtype": "init"' in mid, (
            "the teammate's first line was not on disk while it was still running"
            f" — the log is not live. Log held: {mid!r}"
        )

    def test_a_child_that_dies_before_reading_the_prompt_reports_only_the_diagnosis(
        self, tmp_path, monkeypatch
    ):
        """`subprocess.run(input=...)` swallowed the broken pipe; the hand-rolled
        feeder thread this story replaced it with does not, and an unhandled
        exception in a thread prints a twelve-line traceback the lead reads
        BEFORE the one line that says what went wrong. Constructed with a prompt
        past the pipe buffer so the EPIPE is certain rather than a race — the
        real 4k prompt hits the same write whenever the child loses it."""
        import threading

        from teammate_tee import run_teammate

        died = []
        monkeypatch.setattr(threading, "excepthook", lambda arg: died.append(arg.exc_type))
        script = tmp_path / "refuse.py"
        script.write_text("import sys\nsys.exit(1)\n")  # never reads stdin
        rc = run_teammate(
            [sys.executable, str(script)],
            tmp_path,
            "x" * (1 << 20),
            "story-epipe",
            tmp_path / "data",
            out=lambda _l: None,
        )
        assert rc == 1
        assert died == [], f"the feeder thread died unhandled: {died}"

    def test_the_log_holds_lines_emitted_before_a_mid_stream_kill(self, tmp_path):
        from teammate_tee import log_path, run_teammate

        script = tmp_path / "flaky.py"
        script.write_text(
            "import json, os, signal, sys, time\n"
            "print(json.dumps({'type': 'system', 'subtype': 'init'}))\n"
            "sys.stdout.flush()\n"
            "time.sleep(0.1)\n"
            "os.kill(os.getpid(), signal.SIGKILL)\n"
        )
        rc = run_teammate(
            [sys.executable, str(script)], tmp_path, "", "story-kill", tmp_path / "data"
        )
        assert rc != 0  # killed mid-stream: no terminal result object survived
        log = log_path(tmp_path / "data", "story-kill").read_text()
        assert '"subtype": "init"' in log  # what it emitted before dying is on disk


class TestTeammateCompletion:
    """Given a completed teammate, spawn refuses unless the worktree is CLEAN
    and carries at least one commit of its own — a process exiting 0 is not
    the same claim as a story being done."""

    def test_a_dirty_tree_is_refused_naming_both_recoveries(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path, commit=False, write_file=True)  # leaves a stray, uncommitted file
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2
        assert "dirty" in r.stderr.lower() or "uncommitted" in r.stderr.lower()
        assert "commit" in r.stderr.lower() and "worktree remove" in r.stderr

    def test_no_commits_of_its_own_is_refused_naming_both_recoveries(self, tmp_path):
        """Also the flip-commit case: the tree here holds exactly one commit,
        the [in-progress] flip, so `trunk..HEAD` counts 1 and the vacuous
        spelling constraints.md #11 forbids greens. Only comparing against
        HEAD-after-the-flip lets this red."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path, commit=False)  # clean tree, but nothing committed
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2
        assert "no commits" in r.stderr.lower()
        assert "commit" in r.stderr.lower() and "worktree remove" in r.stderr

    def test_a_crashed_teammate_that_left_work_behind_still_names_it(self, tmp_path):
        """The likeliest way a run "ends with a dirty tree" is that it never
        ended: a crash, a kill, a launch the binary refused. Returning the
        child's code straight from the stream loop skips the completion guard
        on exactly that path, so the lead is told the stream had no result
        object and never told about the file left uncommitted underneath it."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path, commit=False, write_file=True, emit_result=False)
        r = spawn(repo, env, "story-042")
        assert r.returncode != 0
        assert "teammate-left-this-uncommitted.txt" in r.stderr
        assert "worktree remove" in r.stderr

    def test_a_leftover_from_the_bootstrap_is_not_blamed_on_the_teammate(self, tmp_path):
        """`Worktree bootstrap:` runs BEFORE the teammate and can leave the tree
        dirty by itself — `npm install` rewriting a lockfile is the ordinary
        case. Reading the raw porcelain accuses the teammate of it and tells the
        lead to commit it by hand; the baseline is the tree as the teammate
        RECEIVED it, which is why both halves of the guard compare against the
        post-flip state and not against ambient state (constraints.md #11)."""
        repo, env, _g = make_repo(tmp_path)
        (repo / ".xp" / "system.md").write_text(
            "# System\n- Worktree bootstrap: `touch vendored-by-bootstrap.txt`\n"
        )
        subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True)
        subprocess.run(["git", "commit", "-qm", "bootstrap"], cwd=repo, env=env, check=True)
        stub_claude(tmp_path, add_all=False)  # commits its own work, stages nothing else
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr
        assert (
            tmp_path / "data" / "worktrees" / "story-042" / "vendored-by-bootstrap.txt"
        ).exists()

    def test_a_tree_git_cannot_read_is_refused_rather_than_certified(self, tmp_path):
        """Reading only stdout makes a FAILED git indistinguishable from a clean
        one: empty porcelain reads as "nothing uncommitted" and an empty HEAD
        never equals the flip's, so both halves pass and the spawn reports a
        finished story it never actually looked at."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path, break_git=True)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2, r.stdout
        assert "worktree remove" in r.stderr

    def test_a_clean_committed_run_is_accepted(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)  # default: commits and emits a result
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr


class TestClosingLineAndLog:
    def test_the_closing_line_is_printed_from_the_result_object(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr
        assert "3 turns" in r.stdout and "$0.05" in r.stdout and "1.2s" in r.stdout

    def test_the_log_is_project_scoped_and_appends_under_a_header_on_respawn(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        log = tmp_path / "data" / "logs" / "story-042.log"
        assert log.exists()
        first = log.read_text()
        assert "===== spawn story-042 " in first

        # a re-spawn after removing the first worktree appends, not truncates
        tree = tmp_path / "data" / "worktrees" / "story-042"
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(tree)],
            cwd=repo,
            env=env,
            check=True,
        )
        subprocess.run(["git", "branch", "-D", "ada/story-042-demo-story"], cwd=repo, env=env)
        assert spawn(repo, env, "story-042").returncode == 0
        second = log.read_text()
        assert second.startswith(first)
        assert second.count("===== spawn story-042 ") == 2


class TestFirstSpawnInAScaffoldedRepo:
    """Broad review B3: the worktree path is the DEFAULT and the one the plugin
    exists for, and it had no dirty-tree guard — so the literal shipped sequence
    (xp-setup, fill in the plan, spawn) tracebacked and orphaned git state."""

    def test_an_uncommitted_scaffold_refuses_instead_of_tracebacking(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_claude(tmp_path)
        g("checkout", "-q", "main")
        # the literal shipped sequence: scaffold, edit the plan, spawn — uncommitted
        (repo / ".xp" / "plan.md").write_text(
            (repo / ".xp" / "plan.md").read_text()
            + "\n#### story-777 — fresh   [ready]\nVerify: true\n"
        )
        r = spawn(repo, env, "story-777")
        assert r.returncode == 2, r.stdout
        assert "Traceback" not in r.stderr
        assert "commit" in r.stderr.lower(), "the refusal must name the fix"
        assert not (tmp_path / "data" / "worktrees").exists(), "orphaned worktree"
