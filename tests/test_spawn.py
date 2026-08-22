"""story-007: the spawn CLI — launch contract, worktrees, refusals, bootstrap.
Verify: pytest -q tests/test_spawn.py"""

import json
import subprocess
from itertools import pairwise
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
    trunk_sha,
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


def reset_to_ready(tmp_path):
    """The flip is no longer branch-local, so a second spawn of one story refuses on
    [in-progress] before it ever reaches the worktree and branch guards below."""
    plan = tmp_path / "data" / "plan.md"
    plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))


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
        # the clone gets its OWN plan -- that is the point of a per-clone plan, and
        # the git clone no longer carries one
        plan2 = tmp_path / "data2" / "plan.md"
        plan2.parent.mkdir(parents=True, exist_ok=True)
        # and its own credential: the digest is minted per data root, so a plan
        # copied between clones arrives uncleared rather than pre-approved
        plan2.write_text(
            (tmp_path / "data" / "plan.md").read_text().replace("[in-progress]", "[planned]")
        )
        assert spawn(other, env2, "ready", "story-042").returncode == 0
        assert spawn(other, env2, "story-042").returncode == 0
        second = in_tree(
            tmp_path / "data2" / "worktrees" / "story-042", env2, "branch", "--show-current"
        )
        assert second == "grace/story-042-demo-story"
        assert first != second

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

    def test_cli_override_beats_the_card(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="claude/opus/high")
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042", "claude/haiku").returncode == 0
        argv = json.loads(rec.read_text())["argv"]
        assert argv[argv.index("--model") + 1] == "haiku"
        assert "--effort" not in argv  # two-part spec: reviewer role shape (story-008)


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
        assert "[in-progress]" in (tmp_path / "data" / "plan.md").read_text()
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
        assert "[ready]" in (tmp_path / "data" / "plan.md").read_text()

    def test_existing_branch_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert spawn(repo, env, "story-042", "--in-place").returncode == 0
        subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, env=env)
        reset_to_ready(tmp_path)  # else the [in-progress] guard fires first
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
    """A filed debt (story-009 retires config.yml sprint_branch) rests on spawn
    never reading the key itself — a comment cannot rot loudly, a test can."""
    assert "sprint_branch" not in SPAWN.read_text()


class TestCodexExecutor:
    """story-021. Every divergence between the two legs is a silent hole in one
    of them, so these assert the codex leg reaches the SAME shared guards."""

    def argv(self, tmp_path, executor="codex/gpt-5.6-terra/medium"):
        repo, env, _g = make_repo(tmp_path, executor=executor)
        stub_codex(tmp_path)
        r = spawn(repo, env, "story-042", "--dry-run")
        assert r.returncode == 0, r.stderr
        for ln in r.stdout.splitlines():
            if ln.startswith("codex "):
                return ln.split(" ")
        raise AssertionError(f"no codex argv in: {r.stdout[:400]}")

    def test_the_assembled_argv(self, tmp_path):
        argv = self.argv(tmp_path)
        pairs = list(pairwise(argv))
        for pair in [
            ("-m", "gpt-5.6-terra"),
            ("-c", "model_reasoning_effort=medium"),
            ("--disable", "unified_exec"),
            ("--sandbox", "workspace-write"),
            ("--add-dir", str(tmp_path / "data")),
            # XP_ROLE (self-close bar — close.py reads an ABSENT value as `lead`)
            # and GIT_AUTHOR_* (the reviewer's signature) reach codex's shell only
            # through shell_environment_policy, and ALL THREE of these keys can
            # strip them: inherit chooses the source set, exclude drops patterns
            # from it, include_only keeps only patterns. Each is a
            # ~/.codex/config.toml key, so a consuming developer's file — not the
            # lead's, which is the only one the story-021 walk measured — decides.
            # All three measured present on 0.147.0 from codex's own error text
            # for a bad value; `[]` is each list key's own default, which is why
            # pinning it is a restoration and not a new policy.
            ("-c", "shell_environment_policy.inherit=all"),
            ("-c", "shell_environment_policy.exclude=[]"),
            ("-c", "shell_environment_policy.include_only=[]"),
        ]:
            assert pair in pairs, f"{pair} missing from {argv}"
        assert "-e" not in argv, "codex has no -e; the effort rides -c (spike-falsified)"
        # asserting `--sandbox workspace-write` PRESENT bounds nothing on its own:
        # 0.147.0 ships a documented override that silently voids it, and it is what
        # a reader reaches for the first time the sandbox denies a write
        assert "--dangerously-bypass-approvals-and-sandbox" not in argv, argv
        # exactly one: note 6193855e probed the git-common-dir widening
        # unnecessary on 0.147.0, and a second --add-dir is that widening returning
        assert argv.count("--add-dir") == 1, argv

    def test_a_two_part_spec_carries_no_effort(self, tmp_path):
        argv = self.argv(tmp_path, executor="codex/gpt-5.6-terra")
        assert not [a for a in argv if a.startswith("model_reasoning_effort")], argv

    def test_the_stub_reds_when_the_gate_flag_is_deleted(self, tmp_path, monkeypatch):
        """Constraint 2: a stub that cannot red against its target defect
        certifies. Strip the flag from the REAL builder's output and run the
        real stub on it — the pair is what the spawn ships."""
        import spawn as spawn_mod

        # monkeypatch, not os.environ[...]: this test runs IN-PROCESS, and a bare
        # assignment leaves every later data_root() in this worker pointed at a
        # tmp_path pytest has already deleted
        monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
        argv = spawn_mod.codex_argv("gpt-5.6-terra", "medium")
        stub_codex(tmp_path)
        stripped = [a for a in argv if a not in ("--disable", "unified_exec")]
        r = subprocess.run(
            # cwd matters even on the arm that must die early: with the guard
            # mutated away, the stub reaches its `git commit` and commits wherever
            # it stands — the repo under review, if that is the cwd
            [str(tmp_path / "bin" / "codex"), *stripped[1:]],
            input="",
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert r.returncode != 0 and "unified_exec" in r.stderr, r.stderr
        intact = subprocess.run(
            [str(tmp_path / "bin" / "codex"), *argv[1:]],
            input="",
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert intact.returncode == 0, intact.stderr

    def test_absent_from_path_refuses_before_any_worktree_is_cut(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        r = spawn(repo, env, "story-042")  # no stub_codex: nothing named codex on PATH
        assert r.returncode == 2
        assert "codex" in r.stderr and "install" in r.stderr.lower(), r.stderr
        assert not (tmp_path / "data" / "worktrees" / "story-042").exists()
        branches = in_tree(repo, env, "branch", "--format=%(refname:short)")
        assert "story-042" not in branches, branches

    def test_dry_run_still_prints_the_argv_with_nothing_installed(self, tmp_path):
        """Reading the argv a harness WOULD take is what a lead does before
        installing it — review.run already exempts its dry run, and one rule with
        two implementations is this repo's most-filed defect class."""
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        r = spawn(repo, env, "story-042", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "--disable unified_exec" in r.stdout, r.stdout[:400]

    def test_every_shipped_harness_has_its_own_argv_and_stream(self):
        """Three registries, two files: HARNESS_INSTALL admits a harness, agent_argv
        builds for it, STREAMS parses it. agent_argv FALLS THROUGH to claude, so a
        third harness admitted without a builder launches the wrong binary silently;
        a missing STREAMS row crashes after the worktree is cut and the card flipped."""
        from spawn import HARNESS_INSTALL, agent_argv
        from teammate_tee import STREAMS

        assert set(STREAMS) == set(HARNESS_INSTALL)
        for harness in HARNESS_INSTALL:
            assert agent_argv(harness, "m", "high", "json")[0] == harness

    def test_a_dirty_codex_teammate_hits_the_shared_completion_guard(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        stub_codex(tmp_path, commit=False, write_file=True)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "uncommitted" in r.stderr, r.stderr

    def test_a_codex_teammate_with_no_commits_hits_the_shared_guard(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        stub_codex(tmp_path, commit=False)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "no commits of its own" in r.stderr, r.stderr

    def test_a_clean_codex_teammate_passes(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        rec = stub_codex(tmp_path)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr
        launch = json.loads(rec.read_text())
        assert launch["env"]["XP_ROLE"] == "teammate"
        # the profile is INLINED, which is what makes a codex teammate need no
        # plugin install — codex has no --plugin-dir to carry one
        assert "CONSTRAINT-SENTINEL" in launch["stdin"] and "demo story" in launch["stdin"]
