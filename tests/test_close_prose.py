"""Shipped prose matches the mechanism. Split from test_close.py at sprint-004 open."""

import re
from pathlib import Path

from close_helpers import (  # noqa: F401
    CARD,
    CLOSE,
    CONFIG,
    PLUGIN,
    REVIEWER_NAME,
    WORK,
    close,
    close_bare,
    free,
    free_repo,
    launches,
    make_repo,
    marker,
    marker_file,
    prose,
    stub_reviewer,
)


class TestShippedProseMatchesTheMechanism:
    """The prose is what a consuming project believes. story-012a AC 11/12."""

    def test_no_verdict_token_survives_in_the_shipped_prose(self):
        for path in (
            PLUGIN / "skills" / "story-close" / "SKILL.md",
            PLUGIN / "PROCESS.md",
            PLUGIN / "scripts" / "close.py",  # --help is the first surface a lead reads
        ):
            head = path.read_text().split("import argparse")[0]
            assert "VERDICT" not in head, f"{path.name} still ships the deleted gate"

    def test_the_record_lifecycle_row_is_not_corrupted(self):
        """A string-replace deletion left a stray backtick and a truncated clause
        in the authority row for what the sprint-close batch runs. A PARITY check
        on the row, not a grep for the mangled text: a different corruption still
        reds, a reworded but balanced row still greens (bug 166285e6)."""
        design = (PLUGIN.parent.parent / "docs" / "DESIGN.md").read_text()
        row = next(ln for ln in design.splitlines() if ln.startswith("| **resolved** |"))
        assert row.count("**") % 2 == 0, f"unbalanced bold span: {row}"
        assert row.count("`") % 2 == 0, f"unbalanced backtick span: {row}"

    def test_the_comment_rubric_is_identical_in_every_shipped_copy(self):
        """TWO copies now, not three. The reviewer's copy existed for one stated
        reason — "build_bundle never sends PROCESS.md" — which was one line of
        Python, not a fact, so story-014 sent it and the charter POINTS.

        TEAMMATE.md keeps its copy: spawn inlines it into a fresh session with no
        bundle, so for THAT reader the premise still holds.
        """
        rubric = (
            "Comments: restates the code → delete · explains WHAT → rename it ·"
            " a checkable claim → write the test · narrates history → delete, git"
            " holds it. Keep only the why, an external constraint, a rejected design."
        )
        for path in (PLUGIN / "PROCESS.md", PLUGIN / "TEAMMATE.md"):
            assert rubric in prose(path), f"{path.name} has drifted from the rubric"

    def test_the_story_bundle_carries_PROCESS_md(self, tmp_path):
        """What replaces the two pins. Both charters point at PROCESS.md now, so a
        bundle without it hands the reviewer a pointer to nothing."""
        repo, env, _g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        bundle = launches(tmp_path)[0]["stdin"]
        assert "Polarity" in bundle and "(missing" not in bundle

    def test_every_stopping_rule_copy_states_the_split_arithmetic(self):
        """land refuses unless the last round covers HEAD, so "close without
        re-review" cannot be kept. Asserted POSITIVELY and in every copy: a
        negative grep for one file's old wording passed vacuously on the file
        that never used that spelling, and missed DESIGN.md entirely.

        story-012b SPLIT the rule — a REVIEWER fix costs no confirming round, a
        LEAD fix still does — and `"confirming round" in text` was already true of
        all three files BEFORE the split, so it certified the undifferentiated
        sentence AC 10 exists to replace. Both halves, or neither is guarded.
        """
        for path in (
            PLUGIN / "PROCESS.md",
            PLUGIN / "skills" / "story-close" / "SKILL.md",
            Path(__file__).parent.parent / "docs" / "DESIGN.md",
        ):
            text = prose(path)
            assert "confirming round" in text, f"{path.name} still promises"
            assert "inside the round that found" in text, f"{path.name}: reviewer half"
            assert "past what the review covered" in text, f"{path.name}: lead half"

    def test_DESIGN_states_overlap_not_motion_and_report_not_refuse(self):
        """story-018 AC 7. Positive and BOTH halves, in the style of the stopping-rule
        pin above: the doc moves with the code or they disagree, and a doc that kept
        only the half that reads like the old rule is the drift this catches."""
        design = prose(Path(__file__).parent.parent / "docs" / "DESIGN.md")
        for claim in (
            "overlap, not motion",
            "intersect the files the story changed",
            "trial-merges",
            "report, not refuse",
        ):
            assert claim in design, f"DESIGN §6 no longer states: {claim}"

    def test_the_sprint_close_skill_runs_the_reviews_rather_than_composing_them(self):
        """Step 2 used to tell a human to do a broad review and a security review.
        Both prompts were then hand-composed at sprint-002's close, and when four
        fix-commits needed re-checking there were no prior findings to bound the
        pass — an unbounded re-review (note bae0b87b)."""
        skill = prose(PLUGIN / "skills" / "sprint-close" / "SKILL.md")
        assert "close.py sprint <id> review" in skill, "the review is still hand-composed"

    def test_the_sprint_close_skill_orders_the_retro_BEFORE_the_reviews(self):
        """Measured against the last real close: sprint-002's retro commit touched
        CHANGELOG.md, docs/DESIGN.md, PROCESS.md and story-close/SKILL.md — five of
        six paths outside .xp/, so land's exemption does not cover it. Retro last
        means reviewing again, which invalidates the retro just written. The order
        is the fix, and it also puts the retro diff under the review DESIGN §6
        already says it deserves."""
        skill = prose(PLUGIN / "skills" / "sprint-close" / "SKILL.md")
        assert skill.index("Note triage") < skill.index("close.py sprint <id> review")
        assert "BEFORE the review" in skill

    def test_release_artifacts_are_project_owned_and_timed_without_enumeration(self):
        skill = prose(PLUGIN / "skills" / "sprint-close" / "SKILL.md")
        step = skill.split("5. **", 1)[1]
        assert "Your release artifacts are yours" in step
        assert "before" in step.lower() and "review" in step.lower()
        assert "bump" not in step.lower() and "changelog" not in step.lower()

    def test_free_start_names_release_timing_without_telling_the_lead_to_commit(self, tmp_path):
        outputs = []
        for name, slug in (("one", "fix-one"), ("two", "fix-two")):
            repo, env, _g = free_repo(tmp_path / name)
            result = free(repo, env, slug, "start")
            assert result.returncode == 0, result.stderr
            outputs.append(result.stdout)
            assert result.stdout.index("release artifacts") < result.stdout.index("review")
            assert "Commit, then" not in result.stdout
        assert outputs[0] != outputs[1]

    def test_the_loop_names_free_execution_and_does_not_grow(self):
        process = (PLUGIN / "PROCESS.md").read_text()
        assert len(process) <= 5454
        free_entry = process.split("5. **Free", 1)[1].split("## Records", 1)[0]
        assert "spawn.py" in free_entry
        assert "worktree" in free_entry and "data root" in free_entry
        assert "authorship cannot" in free_entry.lower()

    def test_a_script_driving_skill_does_not_restate_the_mechanism(self):
        """Measured drift, three times in two sprints, caught by a READER every
        time and by no test: sprint-close's step count went stale when the
        pipeline absorbed two reviews, and story-close described `-d` ordering
        and a branch precondition that the land fix reversed. Prose describing a
        mechanism is a second copy of it. The refusals name their own remediation,
        so the enumerations were duplicating text the lead is handed anyway.
        Pinned as a WORD BUDGET, not a token grep: a count reds when the
        enumerations grow back under any wording, which is the failure mode.
        """
        for skill, cap in (("story-close", 330), ("sprint-close", 330)):
            body = prose(PLUGIN / "skills" / skill / "SKILL.md")
            assert len(body.split()) <= cap, f"{skill} regrew to {len(body.split())} words"

    def test_the_skills_keep_the_negative_space_that_earns_its_words(self):
        """The counterweight to the cut: what deliberately does NOT exist cannot be
        read off the code an agent has not read, so it is the one description that
        stays. Without this pin the word budget above is satisfiable by deleting
        exactly the sentences that stop an agent hunting for a flag."""
        story = prose(PLUGIN / "skills" / "story-close" / "SKILL.md")
        assert "DOES NOT EXIST" in story, "the lead will hunt for a delta review"
        assert "never spawns" in story, "land's one hard guarantee"

    def test_every_shipped_script_is_reachable_from_the_plugin(self):
        """ratchet.py sat in scripts/ for a sprint measuring OUR budgets against
        OUR module names: nothing in the plugin invoked it, the shipped lefthook
        template never ran it, and in a consuming repo it could only exit 2
        ("MEASURED NOTHING"). Dev tooling shipped to every install.

        IMPORT-OR-INVOKE, not a mention: ratchet was named once inside the plugin,
        in a spawn.py comment, so a grep for the word would have certified it.
        """
        scripts = sorted((PLUGIN / "scripts").glob("*.py"))
        assert len(scripts) > 5, "glob found nothing — a green here would certify"
        corpus = {
            p: p.read_text()
            for p in PLUGIN.rglob("*")
            if p.is_file() and p.suffix in (".py", ".md", ".json", ".yml", ".sh")
        }
        for script in scripts:
            name = script.stem
            forms = (f"import {name}", f"from {name} import", f"scripts/{name}.py")
            reachable = any(
                any(f in text for f in forms) for path, text in corpus.items() if path != script
            )
            assert reachable, (
                f"{name}.py is shipped but nothing in the plugin imports or invokes it —"
                " dev tooling belongs in tests/scripts/, not in every consumer's install"
            )

    def test_a_verify_line_that_is_not_runnable_is_refused_before_the_review(self, tmp_path):
        """Bug 3e2ad94b. verify_commands returns everything after "Verify:", so a
        line with rationale appended reached /bin/sh at LAND — after a reviewer had
        been spent — and died on an unbalanced quote. story-016's card cleared TWO
        plan-review rounds that way. The refusal belongs in _preflight, which both
        legs call, so it costs a refusal instead of a review: assert NOTHING was
        spawned, which is the half that makes it cheaper rather than merely louder.

        BOUND, stated: shlex catches an UNBALANCED QUOTE — the apostrophe in
        "story-010's" is what actually killed /bin/sh. Prose whose quotes happen to
        balance still parses and still runs garbage. This closes the measured
        failure, not the general class."""
        repo, env, _g = make_repo(
            tmp_path, verify="pytest -q -k x — `-k prose` selected story-010's test"
        )
        r = close(repo, env, "review")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "Verify" in r.stderr, r.stderr
        assert launches(tmp_path) == [], "spent a reviewer on an unrunnable Verify"

    def test_the_charter_names_the_report_path(self):
        assert "REPORT_PATH" in (PLUGIN / "agents" / "story-reviewer.md").read_text()

    def test_the_plan_reviewer_charter_asks_for_a_file(self):
        assert (
            "write your findings to a file"
            in (PLUGIN / "agents" / "plan-reviewer.md").read_text().lower()
        )

    def test_the_plan_reviewer_charter_has_five_checks(self):
        """story-016: check 4 absorbs the CUT duty (moved out of Output's
        standing-to-cut sentence) and the old check 5's "really three stories"
        clause; check 5's sprint-cap clause folds into check 1. A structural
        count, not a token grep — it certifies the count only, not that the
        duty is followed."""
        charter = (PLUGIN / "agents" / "plan-reviewer.md").read_text()
        section = charter.split("## Checks, in order of payoff")[1]
        section = section.split("## Close-review depth")[0]
        numbered = [line for line in section.splitlines() if re.match(r"\d+\. ", line)]
        assert len(numbered) == 5, f"expected 5 checks, found {len(numbered)}"

    def test_the_walk_fixture_names_no_cut_and_no_control(self):
        """Bug 271de3bd, whose falsifier selects this test BY NAME. This header IS
        the prompt both walk arms receive, so the arms are comparable only while
        it is byte-identical between them — and it
        once named 013 and 015 as the cuts and 010 as the negative control, which
        let either arm answer by reading. A list of banned phrases could not hold
        that: "two of these three were dropped by planning; the last was kept as
        carded" is a complete answer key and passes every one of them. Pinning the
        literal makes any edit to the experiment's prompt deliberate. The cards
        below it are NOT pinned — they legitimately quote planning history."""
        fixture = (Path(__file__).parent / "fixtures" / "overdesigned_plan.md").read_text()
        assert fixture.split("#### ")[0] == (
            "# Plan slice under review — three candidate stories\n"
            "\n"
            "Review these three story cards as a plan reviewer would: the sprint they belong\n"
            "to has a cap of 6 and currently holds three other stories. The project is a\n"
            "lightweight XP process plugin for coding agents; its constraints and system\n"
            "context are in the files handed to you alongside this one.\n"
            "\n"
        )

    def test_the_plan_review_location_is_pinned_in_both_copies(self):
        """AC5: "say where" let two reviewers pick two different places this
        sprint — a session scratchpad under /private/tmp for one, `.xp/reviews/`
        for another. One location, asserted in both places it lives so neither can
        drift without reding — the pattern
        test_every_stopping_rule_copy_states_the_split_arithmetic already uses.

        The ROUND clause is pinned with it because one name for a file written
        once per round destroys the earlier round on write, and plan review does
        run in rounds: story-014's two rounds are both on disk, and story-016's
        own card credits its round-2 review. review.py already round-scopes the
        story reviewer's report; nothing did the same here. Both copies are held
        to the same LITERAL: "round-scoped" alone greened here off DESIGN's
        unrelated sentence about that report (fault-injected, constraint 2).
        """
        location = "<data-root>/plans/<story-id>.md"
        charter = (PLUGIN / "agents" / "plan-reviewer.md").read_text()
        design = (Path(__file__).parent.parent / "docs" / "DESIGN.md").read_text()
        assert location in charter, "plan-reviewer.md dropped the location"
        assert location in design, "DESIGN.md dropped the location"
        rounds = "<story-id>.round-N.md"
        assert rounds in charter, "the charter lost the round rule"
        assert rounds in design, "DESIGN.md lost the round rule"


class TestCharterBar:
    def test_the_charter_states_the_three_buckets(self):
        charter = (PLUGIN / "agents" / "story-reviewer.md").read_text().lower()
        # the bucket NAMES as the charter writes them: "fix it" matched the
        # blocking bullet's "could NOT fix it", so the `fixed` bucket the whole
        # story turns on was the one token this loop never actually required.
        for token in ("`fixed`", "`blocking`", "`noted`"):
            assert token in charter
        assert "heredoc" not in charter, "Write is allowed now; the heredoc route is stale"

    def test_both_charters_point_at_the_finding_bar_rather_than_copying_it(self):
        """Replaces the byte-identical pin story-014 deleted. That pin existed
        because "build_bundle never sends PROCESS.md" — one line of Python, not a
        fact. Asserting the bar appears ONCE in PROCESS.md would be false as
        written: PROCESS.md states it twice, at story close and at sprint close.
        """
        bar = "silent or corrupting (false green, corrupted record, unreviewed merge)"
        # Whitespace-normalised: the pin is the WORDS, not their wrapping. Matching
        # raw text made a reflow of PROCESS.md read as a dropped bar — a false
        # negative that says nothing about whether the charters copy it.
        assert bar in prose(PLUGIN / "PROCESS.md")
        for name in ("story-reviewer", "sprint-reviewer"):
            charter = prose(PLUGIN / "agents" / f"{name}.md")
            assert bar not in charter, f"{name} still ships a second copy of the bar"
            assert "PROCESS" in charter, f"{name} dropped the copy without pointing"


def test_every_shipped_skill_is_named_by_shipped_prose():
    """A skill nothing points at is reachable only by someone who already knows it
    exists, which is the opposite of what a skill is for. Measured: /sprint-close
    and /xp-setup shipped for six sprints named by no prose, and the lead ran the
    scripts they wrap for seven story closes and one sprint close — skipping, both
    times, the judgment step the skill reserves and the script cannot enforce.

    Enumerated from the directory, never a hand-list: a skill added later is
    covered without editing this test (bug 6d384ef9).
    """
    process = (PLUGIN / "PROCESS.md").read_text()
    shipped = sorted(d.name for d in (PLUGIN / "skills").iterdir() if d.is_dir())
    assert shipped, "no skills found — the enumeration itself broke"
    missing = [s for s in shipped if s not in process]
    assert not missing, f"shipped but named by no prose: {', '.join(missing)}"
