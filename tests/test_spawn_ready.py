"""story-023's [ready] credential leg. Extracted from test_spawn.py at
story-021: that file stood at 486 of the 500-line cap (constraint 8) and the
codex executor's ACs must land in a file the card's Verify names."""

import json
import re
import subprocess
import sys

import pytest
from spawn_helpers import SPAWN, make_repo, seed_refresh_receipt, spawn, stub_claude


class TestReadyCredential:
    """story-023. [ready] was a bit with a reader and no writer, so a card edited
    after its plan review kept the credential and a teammate was launched on text
    no reviewer saw — measured three times in sprint-003."""

    MARKER = ("data", "markers", "story-042.ready.json")

    def marker(self, tmp_path):
        return tmp_path.joinpath(*self.MARKER)

    def mint(self, repo, env, story="story-042"):
        seed_refresh_receipt(repo, env, story)
        r = spawn(repo, env, "ready", story)
        assert r.returncode == 0, r.stderr
        return r

    def edit_card(self, tmp_path, old, new):
        """CONSTRUCT the drift in the plan the lead actually edits (constraint 11)."""
        plan = tmp_path / "data" / "plan.md"
        text = plan.read_text()
        assert old in text, f"fixture drifted: {old!r} not in the card"
        plan.write_text(text.replace(old, new))

    def test_a_verify_line_with_its_commands_bulleted_below_refuses_at_the_mint(self, tmp_path):
        """Field report (Legacy): seven cards were authored as `Verify:` followed by
        a bulleted list, which is what `AC:` above it looks like — and
        verify_commands reads only the REMAINDER of the line, so it parsed empty.
        The refusal arrived at LAND, after the implementation and the review, saying
        "has no Verify: line" about a card that visibly has one.

        Mint is where it belongs: the credential leg already reads the whole card,
        and refusing here costs a re-edit instead of a spawn, a story and a round.
        """
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text().replace(
                "Verify: true",
                "Verify:\n- `pytest -q tests/test_a.py`\n- `bun test`",
            )
        )
        r = spawn(repo, env, "ready", "story-042")
        assert r.returncode != 0, r.stdout
        assert "Verify:" in r.stderr and "same line" in r.stderr.lower(), r.stderr
        assert not self.marker(tmp_path).exists(), "a refused mint must write nothing"

    @pytest.mark.parametrize(
        ("verify", "reason"),
        [
            ("printf injected > {sentinel}", "shell syntax"),
            ("printf $HOME", "shell syntax"),
            ("printf x | true", "shell syntax"),
            ("true & wait", "shell syntax"),
            ("cat <(printf x)", "shell syntax"),
            ("printf `whoami`", "shell syntax"),
            ("printf $(whoami)", "shell syntax"),
            ("true # an old template comment", "shell syntax"),
            ("true 'unterminated", "not runnable"),
            ("none — prose", "not runnable"),
        ],
    )
    def test_ready_refuses_non_argv_verify_before_minting(self, tmp_path, verify, reason):
        repo, env, _g = make_repo(tmp_path, status="planned")
        sentinel = tmp_path / "shell-ran"
        if "> {sentinel}" in verify:
            shell_line = verify.format(sentinel=sentinel)
            subprocess.run(["/bin/sh", "-c", shell_line], check=True)
            assert sentinel.read_text() == "injected"
            sentinel.unlink()
        self.edit_card(tmp_path, "Verify: true", "Verify: " + verify.format(sentinel=sentinel))

        r = spawn(repo, env, "ready", "story-042")

        assert r.returncode == 2 and "story-042" in r.stderr and reason in r.stderr
        assert not sentinel.exists() and not self.marker(tmp_path).exists()
        assert "[planned]" in (tmp_path / "data" / "plan.md").read_text()

    def test_an_ac_edited_after_the_mint_refuses_and_names_the_drift(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        self.mint(repo, env)
        self.edit_card(tmp_path, "- Given X, When Y, Then Z", "- Given P, When Q, Then R")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2, r.stdout
        assert "Given X, When Y, Then Z" in r.stderr, r.stderr
        assert "Given P, When Q, Then R" in r.stderr, r.stderr
        assert "spawn.py amend story-042" in r.stderr, r.stderr
        # the bracket moved between mint and spawn and the digest forgave it, so
        # a diff that names the heading would be reporting drift that is not drift
        assert "#### story-042" not in r.stderr.replace(" #### story-042", ""), r.stderr
        assert not (tmp_path / "data" / "worktrees").exists(), "launched on unreviewed text"
        assert "[in-progress]" not in (tmp_path / "data" / "plan.md").read_text(), "flipped anyway"

    def test_an_in_progress_card_can_be_amended_with_an_audited_reason(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        self.mint(repo, env)
        assert spawn(repo, env, "story-042").returncode == 0
        marker = self.marker(tmp_path)
        before = json.loads(marker.read_text())
        self.edit_card(tmp_path, "Files: src/thing.py", "Files: src/thing.py, tests/test_a.py")
        self.edit_card(tmp_path, "Verify: true", "Verify: python3 -m pytest -q tests/test_a.py")

        amended = spawn(
            repo, env, "amend", "story-042", "--reason", "the implementation added its test"
        )

        assert amended.returncode == 0, amended.stderr
        assert "-Files: src/thing.py" in amended.stdout
        assert "+Files: src/thing.py, tests/test_a.py" in amended.stdout
        assert "-Verify: true" in amended.stdout
        assert "+Verify: python3 -m pytest -q tests/test_a.py" in amended.stdout
        assert "[in-progress]" in (tmp_path / "data" / "plan.md").read_text()
        after = json.loads(marker.read_text())
        assert after["digest"] != before["digest"] and "tests/test_a.py" in after["card"]
        assert after["amendments"] == [
            {"reason": "the implementation added its test", "card": before["card"]}
        ]

    def test_amend_without_a_reason_refuses_without_moving_either_artifact(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        self.mint(repo, env)
        assert spawn(repo, env, "story-042").returncode == 0
        self.edit_card(tmp_path, "Context: demo.", "Context: measured answer.")
        plan = tmp_path / "data" / "plan.md"
        before = plan.read_text(), self.marker(tmp_path).read_text()

        refused = spawn(repo, env, "amend", "story-042")

        assert refused.returncode == 2 and "amend requires --reason" in refused.stderr
        assert (plan.read_text(), self.marker(tmp_path).read_text()) == before

    def test_a_spawned_card_cannot_use_two_raw_flips_to_erase_its_drift(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        self.mint(repo, env)
        assert spawn(repo, env, "story-042").returncode == 0
        self.edit_card(tmp_path, "Context: demo.", "Context: unreviewed answer.")
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[planned]"))
        before = self.marker(tmp_path).read_text()

        refused = spawn(repo, env, "ready", "story-042")

        assert refused.returncode == 2 and "already spawned" in refused.stderr
        assert "spawn.py amend story-042" in refused.stderr
        assert self.marker(tmp_path).read_text() == before

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
        instead of at the lead's next plan review (constraints 11, 12). The bare
        launch has no subcommand to name, so its walk binds to the POSITIONAL:
        `usage: spawn.py [-h]` alone survives the launch becoming a subcommand,
        which is the rename that would falsify the prose."""
        process = (SPAWN.parent.parent / "PROCESS.md").read_text()
        named = re.search(r"`spawn\.py (\w+) <story-id>`", process)
        assert named, "PROCESS.md no longer names the leg that clears a card"
        r = subprocess.run(
            [sys.executable, str(SPAWN), named[1], "--help"], capture_output=True, text=True
        )
        assert f"usage: spawn.py {named[1]}" in r.stdout, r.stdout + r.stderr
        assert re.search(r"`spawn\.py <story-id>`", process), "the launch is unnamed"
        r = subprocess.run([sys.executable, str(SPAWN), "--help"], capture_output=True, text=True)
        usage = r.stdout.split("\n\n", 1)[0]
        assert usage.startswith("usage: spawn.py [-h]"), r.stdout + r.stderr
        assert " story_id" in usage, f"the bare form is no longer spawn.py's own argv: {usage}"

    def test_minting_one_card_leaves_its_siblings_brackets_alone(self, tmp_path):
        """The flip is story-scoped, and the plan is shared. Rewriting every
        trailing [planned] would hand the whole sprint a bracket no mint stands
        behind — each sibling then refuses at ITS spawn, one lead round each."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        plan = tmp_path / "data" / "plan.md"
        sibling = "\n#### story-043 — sibling   [planned]\nVerify: true\n"
        plan.write_text(plan.read_text() + sibling)
        first = self.mint(repo, env).stdout.splitlines()[-1]
        assert sibling in plan.read_text(), plan.read_text()
        second = self.mint(repo, env, "story-043").stdout.splitlines()[-1]
        assert "spawn.py story-042" in first and "spawn.py story-043" in second
        assert first != second

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

    @pytest.mark.parametrize(
        "broken",
        [None, "{", json.dumps({"card": "old", "digest": "bad", "amendments": [None]})],
    )
    def test_a_spawned_broken_credential_can_be_amended_back_to_a_resumable_state(
        self, tmp_path, broken
    ):
        repo, env, _g = make_repo(tmp_path, status="planned")
        stub_claude(tmp_path)
        self.mint(repo, env)
        assert spawn(repo, env, "story-042").returncode == 0
        marker = self.marker(tmp_path)
        marker.unlink() if broken is None else marker.write_text(broken)

        refused = spawn(repo, env, "resume", "story-042")

        diagnosis = "nothing minted it" if broken is None else "unreadable"
        assert refused.returncode == 2 and diagnosis in refused.stderr
        assert "spawn.py amend story-042" in refused.stderr
        amended = spawn(
            repo, env, "amend", "story-042", "--reason", "repair the spawned credential"
        )
        assert amended.returncode == 0, amended.stderr
        audit = json.loads(marker.read_text())["amendments"][-1]
        prior = broken or "(credential absent)"
        assert audit == {"reason": "repair the spawned credential", "card": prior}
        assert spawn(repo, env, "resume", "story-042").returncode == 0

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
