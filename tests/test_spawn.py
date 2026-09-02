"""story-007: the spawn CLI — launch contract, worktrees, refusals, bootstrap.
Verify: pytest -q tests/test_spawn.py"""

import json
import subprocess
from pathlib import Path

from spawn_helpers import (  # noqa: F401
    CARD,
    CONFIG,
    SPAWN,
    _total,
    block_commits,
    in_tree,
    make_repo,
    set_system_md,
    spawn,
    stub_claude,
    stub_claude_requiring_verbose,
    stub_codex,
)
from test_spawn_escalation import ESCALATION, stub_escalating


class TestLaunchContract:
    def test_argv_carries_model_effort_plugin_dir_and_permission_posture(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        config = repo / ".xp" / "config.yml"
        config.write_text(config.read_text() + "codex_sandbox: workspace-write\n")
        g("add", "-A")
        g("commit", "-qm", "codex-only posture")
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
        assert "--sandbox" not in argv
        assert "codex sandbox:" not in r.stdout + r.stderr
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

    def test_codex_executor_launch_carries_the_shipped_posture(self, tmp_path):
        """AC2's other half: the EXECUTOR's launched argv, from the real spawn.
        Paired with the reviewer leg's own call-site assertion — the two must not
        drift apart again, and neither can be checked at the builder now that
        nothing about the launch turns on the role."""
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/high")
        rec = stub_codex(tmp_path, sandbox="danger-full-access")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr
        argv = json.loads(rec.read_text())["argv"]
        assert argv[argv.index("--sandbox") + 1] == "danger-full-access", argv

    def test_plan_reviewer_role_is_bounded_too(self, tmp_path, monkeypatch):
        from spawn import run_agent

        monkeypatch.setenv("XP_AGENT_TIMEOUT", "0.01")
        try:
            run_agent(
                ["/bin/sh", "-c", "sleep 1"],
                tmp_path,
                "",
                role="plan-reviewer",
                harness="claude",
                log_id="story-042-review",
            )
        except subprocess.TimeoutExpired:
            return
        raise AssertionError("the plan-reviewer role ran unbounded")

    def test_a_respawn_inherits_the_stopped_teammates_artifacts_only(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        rec = stub_escalating(tmp_path, artifacts=True)
        assert spawn(repo, env, "story-042").returncode == 3
        first = json.loads(rec.read_text())["stdin"]
        tree = Path(env["XP_DATA"]) / "worktrees" / "story-042"
        g("worktree", "remove", "--force", str(tree))
        g("branch", "-D", "ada/story-042-demo-story")
        reset_to_ready(tmp_path)
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        inherited = json.loads(rec.read_text())["stdin"]
        assert inherited.startswith(first)
        for mark in ("DRAFT-SENTINEL", "FINDING-ONE", "FINDING-TWO", ESCALATION):
            assert mark in inherited


def reset_to_ready(tmp_path):
    """The flip is no longer branch-local, so a second spawn of one story refuses on
    [in-progress] before it ever reaches the worktree and branch guards below."""
    plan = tmp_path / "data" / "plan.md"
    plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))


class TestWorktree:
    def test_each_clone_spawns_from_its_own_recorded_branch(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("branch", "sprint-one", "main")
        g("checkout", "-q", "sprint-one")
        (repo / "base-one.txt").write_text("one\n")
        g("add", "-A")
        g("commit", "-qm", "first sprint base")
        g("checkout", "-q", "elsewhere")
        (tmp_path / "data" / "sprint_branch").write_text("sprint-one\n")
        stub_claude(tmp_path)
        first_run = spawn(repo, env, "story-042")
        assert first_run.returncode == 0
        first_tree = tmp_path / "data" / "worktrees" / "story-042"
        first = in_tree(first_tree, env, "branch", "--show-current")
        assert first == "ada/story-042-demo-story"

        other = tmp_path / "clone2"
        subprocess.run(["git", "clone", "-q", str(repo), str(other)], env=env, check=True)
        env2 = dict(env, XP_DATA=str(tmp_path / "data2"))
        for k, v in (("user.email", "grace@example.com"), ("user.name", "Grace H")):
            subprocess.run(["git", "config", k, v], cwd=other, env=env2, check=True)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=other, env=env2)
        subprocess.run(["git", "checkout", "-qb", "sprint-two"], cwd=other, env=env2)
        (other / "base-two.txt").write_text("two\n")
        subprocess.run(["git", "add", "-A"], cwd=other, env=env2, check=True)
        subprocess.run(["git", "commit", "-qm", "second sprint base"], cwd=other, env=env2)
        plan2 = tmp_path / "data2" / "plan.md"
        plan2.parent.mkdir(parents=True, exist_ok=True)
        (plan2.parent / "sprint_branch").write_text("sprint-two\n")
        plan2.write_text(
            (tmp_path / "data" / "plan.md").read_text().replace("[in-progress]", "[planned]")
        )
        assert spawn(other, env2, "ready", "story-042").returncode == 0
        second_run = spawn(other, env2, "story-042")
        assert second_run.returncode == 0
        second_tree = tmp_path / "data2" / "worktrees" / "story-042"
        second = in_tree(second_tree, env2, "branch", "--show-current")
        assert second == "grace/story-042-demo-story"
        assert first != second
        assert (first_tree / "base-one.txt").exists() and not (first_tree / "base-two.txt").exists()
        assert (second_tree / "base-two.txt").exists() and not (
            second_tree / "base-one.txt"
        ).exists()
        handoffs = [run.stdout.splitlines()[-1] for run in (first_run, second_run)]
        for line, tree, run_env in zip(
            handoffs, (first_tree, second_tree), (env, env2), strict=True
        ):
            assert str(tree) in line and in_tree(tree, run_env, "rev-parse", "HEAD") in line
            assert line.endswith("Read it, then run `/story-close`.")
        assert handoffs[0] != handoffs[1]

    def test_the_flip_lands_in_the_clones_plan_and_commits_nothing(self, tmp_path):
        """Was "the flip is committed in the worktree", where the lead's tree kept
        reading [ready] until the merge. The plan is per-clone now: the flip is not
        a commit at all, the lead sees [in-progress] at once, and the story branch
        starts EMPTY — which is what unclean_teammate_result's head==flip_head
        check depends on."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        tree = tmp_path / "data" / "worktrees" / "story-042"
        assert "[in-progress]" in (tmp_path / "data" / "plan.md").read_text()
        assert in_tree(tree, env, "status", "--porcelain") == ""
        assert "in-progress" not in in_tree(tree, env, "log", "--format=%s", "main..HEAD")

    def test_dry_run_creates_nothing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        r = spawn(repo, env, "story-042", "--dry-run")
        assert r.returncode == 0 and "--plugin-dir" in r.stdout
        assert not (tmp_path / "data" / "worktrees" / "story-042").exists()
        assert "story-042" not in in_tree(repo, env, "branch", "--list")


class TestRefusals:
    def test_existing_worktree_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        reset_to_ready(tmp_path)  # else the [in-progress] guard fires first
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
        reset_to_ready(tmp_path)  # else the [in-progress] guard fires first
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "branch" in r.stderr

    def test_non_ready_story_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="done")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "ready" in r.stderr

    def test_unknown_harness_refused_naming_what_we_ship(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="gemini/pro/high")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2
        assert "claude" in r.stderr and "codex" in r.stderr, r.stderr


class TestExecutorResolution:
    def test_card_executor_beats_config(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="claude/opus/high")
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        argv = json.loads(rec.read_text())["argv"]
        assert argv[argv.index("--model") + 1] == "opus"
        assert argv[argv.index("--effort") + 1] == "high"

    def test_each_role_reads_its_OWN_card_line(self):
        """story-026: one card expresses "author codex, review claude" only if the
        line label follows the role. Before this, resolve_role read `Executor:`
        whatever role it was asked for, so the close leg's card lookup would have
        launched the AUTHOR's harness as the reviewer."""
        from spawn import resolve_role

        card = "Verify: true\nExecutor: codex/gpt-5.6-terra/high\nReviewer: claude/opus\n"
        assert resolve_role("executor", card) == ("codex", "gpt-5.6-terra", "high")
        assert resolve_role("reviewer", card) == ("claude", "opus", "")

    def test_a_role_with_no_card_line_falls_through_to_config(self, tmp_path, monkeypatch):
        """The no-`Reviewer:` case, which every existing close test rides on."""
        from spawn import resolve_role

        repo, _env, _g = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        assert resolve_role("reviewer", "Executor: codex/gpt-5.6-terra/high\n") == (
            "claude",
            "opus",
            "",
        )

    def test_an_absent_config_role_names_the_stale_key_and_line(
        self, tmp_path, monkeypatch, capsys
    ):
        from spawn import resolve_role

        repo, _env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text("roles:\n  executor: claude/sonnet\n")
        monkeypatch.chdir(repo)
        try:
            resolve_role("plan-reviewer")
        except SystemExit as error:
            assert error.code == 2
        message = capsys.readouterr().err
        assert "roles.plan-reviewer" in message and ".xp/config.yml" in message
        assert "`  plan-reviewer: claude/opus`" in message and "predates" in message

    def test_a_malformed_config_role_names_the_bad_value_not_age(
        self, tmp_path, monkeypatch, capsys
    ):
        from spawn import resolve_role

        repo, _env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text("roles:\n  plan-reviewer: claude\n")
        monkeypatch.chdir(repo)
        for card in ("", "Plan-reviewer: claude\n"):
            try:
                resolve_role("plan-reviewer", card)
            except SystemExit as error:
                assert error.code == 2
        config_message, card_message = capsys.readouterr().err.splitlines()
        assert "roles.plan-reviewer" in config_message and ".xp/config.yml" in config_message
        assert "`  plan-reviewer: claude/opus`" in config_message
        assert "predates" not in config_message
        assert "cannot resolve plan-reviewer from 'claude'" in card_message

    def test_a_config_that_is_absent_entirely_is_not_called_stale(
        self, tmp_path, monkeypatch, capsys
    ):
        """An absent FILE and an absent KEY are different repairs — scaffold the
        repo, or add one line — so they cannot share a sentence. sprint_close.py
        already owns the wording for the first."""
        from spawn import resolve_role

        repo, _env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").unlink()
        monkeypatch.chdir(repo)
        try:
            resolve_role("executor")
        except SystemExit as error:
            assert error.code == 2
        message = capsys.readouterr().err
        assert "no .xp/config.yml" in message, message
        assert "predates" not in message and "under `roles:`" not in message

    def test_cli_override_beats_the_card(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="claude/opus/high")
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042", "claude/haiku").returncode == 0
        argv = json.loads(rec.read_text())["argv"]
        assert argv[argv.index("--model") + 1] == "haiku"
        assert "--effort" not in argv  # two-part spec: reviewer role shape (story-008)


class TestRetiredInPlace:
    def test_the_retired_flag_refuses_with_the_worktree_route(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        refused = spawn(repo, env, "story-042", "--in-place")
        help_text = spawn(repo, env, "--help")
        assert refused.returncode == 2
        assert "spawn.py story-042" in refused.stderr and "worktree" in refused.stderr
        assert help_text.returncode == 0 and "--in-place" not in help_text.stdout
        # Above the subcommand dispatch the tombstone swallows every leg, and the
        # story_id it echoes is the subcommand: "run `spawn.py resume` to launch".
        stale = spawn(repo, env, "resume", "story-042", "--in-place")
        assert stale.returncode == 2 and "was removed; run" not in stale.stderr


def test_a_repo_without_dot_xp_routes_to_setup(tmp_path):
    repo, env, _g = make_repo(tmp_path, executor="claude/haiku")
    stub_claude(tmp_path)
    (repo / ".xp").rename(repo / "held-xp")
    refused = spawn(repo, env, "story-042")
    assert refused.returncode == 2
    assert "/xp-setup" in refused.stderr


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


def test_spawn_reaches_the_integration_target_only_through_close():
    """One resolver owns the clone-local record, its fallback, and its refusals."""
    assert "sprint_branch" not in SPAWN.read_text()


class TestCommonDirWidening:
    """Bug 0c31ac94, measured at the first live codex fixing review: a linked
    worktree's index lives at <main>/.git/worktrees/<id>/, OUTSIDE the
    workspace, so the reviewer fixed four files and could not commit one. The
    021 probe that read the widening as unnecessary ran its scratch repo under
    /tmp — writable by default in the codex sandbox — a confound, not a fact.
    The widening is cwd-keyed: a MAIN checkout's .git is inside the workspace
    and stays unwidened, the narrowest posture that still commits."""

    def _repo_with_worktree(self, tmp_path):
        import subprocess

        main = tmp_path / "main"
        main.mkdir()
        run = lambda *a, cwd=main: subprocess.run(  # noqa: E731
            a, cwd=cwd, check=True, capture_output=True
        )
        run("git", "init", "-q")
        run(
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "seed",
        )
        run("git", "worktree", "add", "-q", str(tmp_path / "wt"))
        return main, tmp_path / "wt"

    def test_a_linked_worktree_widens_to_the_git_common_dir(self, tmp_path):
        from spawn import common_dir_widening

        main, wt = self._repo_with_worktree(tmp_path)
        widening = common_dir_widening(wt)
        assert widening[:1] == ["--add-dir"]
        assert (main / ".git").resolve() == __import__("pathlib").Path(widening[1]).resolve()

    def test_run_agent_keeps_the_git_common_dir_from_reviewers(self, tmp_path, monkeypatch):
        from spawn import agent_argv, run_agent

        main, wt = self._repo_with_worktree(tmp_path)
        rec = stub_codex(tmp_path, commit=False)
        monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
        monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
        argv = agent_argv("codex", "m", "", "json", "danger-full-access")
        proc = run_agent(argv, wt, "", "plan-reviewer", "codex", "story-042-review")
        assert proc.returncode == 0, proc.stderr
        launched = json.loads(rec.read_text())["argv"]
        adds = [launched[i + 1] for i, arg in enumerate(launched) if arg == "--add-dir"]
        assert adds == [str(tmp_path / "data")], launched
        assert str((main / ".git").resolve()) not in adds

    def test_the_TEAMMATE_launch_applies_it_too(self, tmp_path, monkeypatch):
        """ONE rule, one launch path. It had two: while the widening lived in
        run_agent alone, a codex teammate in a linked worktree could not commit —
        measured on this story's own author, which hand-committed instead."""
        from spawn import agent_argv
        from teammate_tee import run_teammate

        main, wt = self._repo_with_worktree(tmp_path)
        rec = stub_codex(tmp_path, commit=False)
        monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
        monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
        argv = agent_argv("codex", "m", "", "json", "danger-full-access")
        assert run_teammate(argv, wt, "", "story-042", tmp_path / "data", "codex") == 0
        launched = json.loads(rec.read_text())["argv"]
        adds = [launched[i + 1] for i, arg in enumerate(launched) if arg == "--add-dir"]
        assert str((main / ".git").resolve()) in adds, launched

    def test_a_main_checkout_stays_unwidened(self, tmp_path):
        from spawn import common_dir_widening

        main, _wt = self._repo_with_worktree(tmp_path)
        assert common_dir_widening(main) == []

    def test_a_non_repo_cwd_stays_unwidened(self, tmp_path):
        from spawn import common_dir_widening

        assert common_dir_widening(tmp_path) == []


def test_the_brief_states_the_commit_the_handback_guard_requires(tmp_path, monkeypatch):
    """handback.py:76 refuses when HEAD equals the flip head, so committing is a
    precondition of finishing that only the refusal states. Two independent reports
    on 2026-09-02 of executors handing back a correct, verified, UNCOMMITTED tree;
    one had done both suite baselines and two fault injections, and the resumed
    teammate rightly refused to inherit evidence it could not see.
    A bare `"commit" in brief` is VACUOUS and was measured passing before the fix:
    JUDGMENT.md already says "no-red commits say why". The instruction is what is
    missing, so the instruction is what this asserts."""
    import spawn

    monkeypatch.setenv("XP_DATA", str(tmp_path))
    sections = spawn.teammate_sections("card", "story-x", "", spawn.PLUGIN_ROOT)
    brief = " ".join(b for _, b in sections)
    told = ("commit your", "small commits", "your own commits")
    assert any(p in brief.lower() for p in told), "the brief never tells the executor to commit"
