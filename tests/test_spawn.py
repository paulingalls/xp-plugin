"""story-007: the spawn CLI — launch contract, worktrees, refusals, bootstrap.
Verify: pytest -q tests/test_spawn.py"""

import json
import re
import subprocess
import sys
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


class TestReadyCredential:
    """story-023. [ready] was a bit with a reader and no writer, so a card edited
    after its plan review kept the credential and a teammate was launched on text
    no reviewer saw — measured three times in sprint-003."""

    MARKER = ("data", "markers", "story-042.ready.json")

    def marker(self, tmp_path):
        return tmp_path.joinpath(*self.MARKER)

    def mint(self, repo, env, story="story-042"):
        r = spawn(repo, env, "ready", story)
        assert r.returncode == 0, r.stderr
        return r

    def edit_card(self, tmp_path, old, new):
        """CONSTRUCT the drift in the plan the lead actually edits (constraint 11)."""
        plan = tmp_path / "data" / "plan.md"
        text = plan.read_text()
        assert old in text, f"fixture drifted: {old!r} not in the card"
        plan.write_text(text.replace(old, new))

    def test_an_ac_edited_after_the_mint_refuses_and_names_the_drift(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        self.mint(repo, env)
        self.edit_card(tmp_path, "- Given X, When Y, Then Z", "- Given P, When Q, Then R")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2, r.stdout
        assert "Given X, When Y, Then Z" in r.stderr, r.stderr
        assert "Given P, When Q, Then R" in r.stderr, r.stderr
        # the bracket moved between mint and spawn and the digest forgave it, so
        # a diff that names the heading would be reporting drift that is not drift
        assert "#### story-042" not in r.stderr.replace(" #### story-042", ""), r.stderr
        assert not (tmp_path / "data" / "worktrees").exists(), "launched on unreviewed text"
        assert "[in-progress]" not in (tmp_path / "data" / "plan.md").read_text(), "flipped anyway"

    def test_the_same_card_unedited_spawns(self, tmp_path):
        """The pair AC1 demands: a refusal that also fires on the reviewed card
        is a broken spawn, not a credential."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        self.mint(repo, env)
        assert spawn(repo, env, "story-042").returncode == 0
        assert (tmp_path / "data" / "worktrees" / "story-042").is_dir()

    def test_an_edit_below_an_untouched_heading_refuses(self, tmp_path):
        """AC2: every failure this sprint changed ACs, Files or Context and left
        the heading — the only thing the old credential lived on — byte-identical."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        self.mint(repo, env)
        heading = "#### story-042 — demo story   [ready]"
        self.edit_card(tmp_path, "Files: src/thing.py", "Files: src/thing.py, src/other.py")
        assert heading in (tmp_path / "data" / "plan.md").read_text()
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "src/other.py" in r.stderr, r.stderr

    def test_a_hand_typed_ready_is_refused_because_nothing_minted_it(self, tmp_path):
        """The forgery in its purest form: the bracket typed, no digest behind it.
        Constructed here rather than inherited from make_repo's default, which
        mints — otherwise this test would quietly stop testing anything."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[planned]", "[ready]"))
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2, r.stdout
        assert "ready" in r.stderr and "spawn.py ready story-042" in r.stderr, r.stderr
        # the ABSENT-marker diagnosis, not the unreadable one: without this the two
        # arms are interchangeable (a missing file reads as an OSError downstream),
        # and the lead is sent hunting a corrupt file that was never written
        assert "nothing minted it" in r.stderr, r.stderr
        assert not (tmp_path / "data" / "worktrees").exists()

    def test_ready_mints_the_reviewed_card_and_flips_the_bracket(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="planned")
        out = self.mint(repo, env).stdout
        plan = (tmp_path / "data" / "plan.md").read_text()
        assert "#### story-042 — demo story   [ready]" in plan
        marker = json.loads(self.marker(tmp_path).read_text())
        # the WHOLE block, stored verbatim as read — the bracket it carries is the
        # pre-flip one, which is exactly why the digest ignores brackets
        assert marker["card"] == plan.split("### Sprint 1\n", 1)[1].replace("[ready]", "[planned]")
        assert marker["digest"] in out, "the lead is never shown what was minted"

    def test_ready_refuses_a_card_that_is_not_planned(self, tmp_path):
        """Re-minting is not a lead's typing decision: an already-[ready] card is
        the one whose digest a hand-edit would replace."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        self.mint(repo, env)
        again = spawn(repo, env, "ready", "story-042")
        assert again.returncode == 2, again.stdout
        assert "[planned]" in again.stderr, again.stderr

    def test_ready_refuses_an_unknown_story_without_writing_a_marker(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="planned")
        r = spawn(repo, env, "ready", "story-999")
        assert r.returncode == 2 and "story-999" in r.stderr
        assert not (tmp_path / "data" / "markers").exists()

    def test_a_title_containing_the_status_text_survives_the_mint(self, tmp_path):
        """The flip must rewrite the TRAILING bracket only. A bare str.replace
        rewrites the title too, and then the digest minted before the flip no
        longer matches the card, so the mint's own edit reads as the lead's."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        self.edit_card(tmp_path, "demo story", "what [planned] really means")
        self.mint(repo, env)
        plan = tmp_path / "data" / "plan.md"
        assert "#### story-042 — what [planned] really means   [ready]" in plan.read_text()
        assert spawn(repo, env, "story-042").returncode == 0

    def test_the_leg_PROCESS_md_sends_the_lead_to_exists(self):
        """PROCESS.md is injected into every lead session, so it is what a lead
        believes; nothing bound it to the leg it names. WALKED, not grepped: the
        name is read out of the prose and run, so a renamed subcommand reds here
        instead of at the lead's next plan review (constraints 11, 12)."""
        process = (SPAWN.parent.parent / "PROCESS.md").read_text()
        named = re.search(r"`spawn\.py (\w+) <story-id>`", process)
        assert named, "PROCESS.md no longer names the leg that clears a card"
        r = subprocess.run(
            [sys.executable, str(SPAWN), named[1], "--help"], capture_output=True, text=True
        )
        assert f"usage: spawn.py {named[1]}" in r.stdout, r.stdout + r.stderr

    def test_minting_one_card_leaves_its_siblings_brackets_alone(self, tmp_path):
        """The flip is story-scoped, and the plan is shared. Rewriting every
        trailing [planned] would hand the whole sprint a bracket no mint stands
        behind — each sibling then refuses at ITS spawn, one lead round each."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        plan = tmp_path / "data" / "plan.md"
        sibling = "\n#### story-043 — sibling   [planned]\nVerify: true\n"
        plan.write_text(plan.read_text() + sibling)
        self.mint(repo, env)
        assert sibling in plan.read_text(), plan.read_text()

    def test_an_unreadable_marker_refuses_instead_of_crashing(self, tmp_path):
        """A torn write leaves half a marker; json.loads on it is a traceback, and
        a traceback names no next action."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        self.mint(repo, env)
        marker = self.marker(tmp_path)
        marker.write_text(marker.read_text()[:40])
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2, r.stdout
        assert "Traceback" not in r.stderr, r.stderr
        assert "spawn.py ready story-042" in r.stderr, r.stderr
        assert "unreadable" in r.stderr, r.stderr
        assert not (tmp_path / "data" / "worktrees").exists()
        # and the shape a torn write cannot make but a stray overwrite can: valid
        # JSON that is not the object, which subscripts to TypeError, not ValueError
        marker.write_text("null")
        assert "Traceback" not in spawn(repo, env, "story-042").stderr

    def test_a_planned_card_is_told_which_leg_clears_it(self, tmp_path):
        """The one refusal a lead meets holding an unreviewed card. Before the
        digest the plan review cleared it; now only this leg does."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "spawn.py ready story-042" in r.stderr, r.stderr

    def test_a_ready_card_minted_by_no_one_is_told_the_whole_route(self, tmp_path):
        """Every card already [ready] when this lands, and every forged bracket.
        The route is WALKED here (constraint 12): naming `spawn.py ready` alone
        sends the lead to a leg that refuses a card which is not [planned]."""
        repo, env, _g = make_repo(tmp_path, status="ready")
        stub_claude(tmp_path)
        self.marker(tmp_path).unlink()
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2, r.stdout
        assert "[planned]" in r.stderr and "spawn.py ready story-042" in r.stderr, r.stderr
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[ready]", "[planned]"))
        self.mint(repo, env)
        assert spawn(repo, env, "story-042").returncode == 0
