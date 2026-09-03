"""Shipped prose matches the mechanism. Split from test_close.py at sprint-004 open."""

import re
import subprocess
import sys
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
    launches,
    make_repo,
    marker,
    marker_file,
    prose,
    stub_reviewer,
)


class TestShippedProseMatchesTheMechanism:
    """The prose is what a consuming project believes. story-012a AC 11/12."""

    def test_sprint_salvage_is_a_walkable_help_route(self):
        r = subprocess.run(
            [sys.executable, str(CLOSE), "sprint", "walk", "salvage", "--help"],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0 and "salvage" in r.stdout, r.stderr

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

    def test_each_shared_rule_has_one_complete_copy_in_shipped_markdown(self):
        """The corpus is every Markdown file under the shipped plugin root, including
        templates/constraints.md. docs/DESIGN.md is project documentation, not shipped
        plugin prose, and carries the intentionally separate lifecycle authority table."""
        corpus = sorted(PLUGIN.rglob("*.md"))
        assert PLUGIN / "templates" / "constraints.md" in corpus
        rules = {
            "comment rubric": (
                "restates the code → delete",
                "explains WHAT → rename",
                "a checkable claim → write the test",
                "narrates history → delete",
                "Keep only the why",
            ),
            "record shapes and polarity": (
                "**bug** — claim + red falsifier",
                "**debt** — claim + green falsifier",
                "**resolve** — substitutes a green falsifier",
                "**coverage** — optional",
                "**note** — value tradeoff or discovery",
                "**Polarity**",
            ),
            "hook and red contract": ("Hooks are the wall", "Never bypass", "fake a red"),
            "finding bar": (
                "silent or corrupting",
                "false green, corrupted record, unreviewed merge",
                "loud does not",
            ),
        }
        for name, signatures in rules.items():
            matches = [
                p.relative_to(PLUGIN) for p in corpus if all(s in prose(p) for s in signatures)
            ]
            assert len(matches) == 1, f"{name} has {len(matches)} complete copies: {matches}"

    def test_both_shipped_copies_name_the_two_reviews_and_who_owns_the_plan(self):
        """The lead drafted the executor's implementation plan twice in one week
        (bug 898ad9e1, note c3d8e2a7): one word covered two artifacts and no
        lead-facing sentence said whose each was. Pinned in both copies rather
        than read-and-judged because TEAMMATE.md shares an enforced profile cap
        (`spawn.PLUGIN_SHIPPED_CAP`, 1442/1500 today) — the next component that
        lands forces a cut there, and the newest sentence is the one that looks
        least load-bearing. "sprint review" is excluded by name: `close.py sprint
        <id> review` already holds that phrase.
        """
        for path in (PLUGIN / "PROCESS.md", PLUGIN / "TEAMMATE.md"):
            text = prose(path).lower()
            assert "slate review" in text, f"{path.name}: the lead's review is unnamed"
            assert "execution plan review" in text, f"{path.name}: executor review unnamed"
            assert "the lead never" in text, f"{path.name}: the plan's owner is unnamed"
            assert "sprint review" not in text, f"{path.name}: close.py owns that phrase"

    def test_a_mandatory_step_failing_twice_routes_to_escalation(self):
        teammate = " ".join(prose(PLUGIN / "TEAMMATE.md").lower().split())
        assert "mandatory step fails twice for infrastructure reasons" in teammate
        assert "stop rather than proceed" in teammate
        assert "scripts/work.py note" in teammate

    def test_the_story_bundle_carries_JUDGMENT_but_not_PROCESS(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        bundle = launches(tmp_path)[0]["stdin"]
        assert "## JUDGMENT\n\n" in bundle and "Polarity" in bundle
        assert "## PROCESS\n\n" not in bundle and "(missing" not in bundle

    def test_the_plan_review_bundle_carries_JUDGMENT(self, tmp_path):
        from plan_review import build_bundle

        bundle = build_bundle("charter", "plan", "card", tmp_path / "plan", tmp_path / "out")
        assert "## JUDGMENT\n\n" in bundle and "Polarity" in bundle

    def test_every_stopping_rule_copy_states_the_split_arithmetic(self):
        """PROCESS spends its one-page loop on routing. The story-close skill and
        DESIGN retain the complete stopping rule: pin both because a prior negative
        grep missed DESIGN, and "confirming round" alone passed before the rule was
        split between reviewer and lead fixes (story-012b)."""
        for path in (
            PLUGIN / "skills" / "story-close" / "SKILL.md",
            Path(__file__).parent.parent / "docs" / "DESIGN.md",
        ):
            text = prose(path)
            assert "confirming round" in text, f"{path.name} still promises"
            assert "inside the round that found" in text, f"{path.name}: reviewer half"
            assert "past what the review covered" in text, f"{path.name}: lead half"

    def test_DESIGN_assigns_each_merge_reader_once(self):
        """Sprint integration names a clean overlap to its lead; every other
        unsafe overlap keeps its refusal."""
        design = prose(Path(__file__).parent.parent / "docs" / "DESIGN.md")
        for claim in (
            "trial-merges",
            "sprint integration branch",
            "NAMED to the lead at land on stdout",
            "Gate-file overlap still refuses",
            "conflicts refuse",
            "Free and story releases still refuse",
        ):
            assert claim in design, f"DESIGN §6 no longer states: {claim}"
        assert "story-scoped path list" not in design
        assert "every sprint-review stage reads" not in design

    def test_the_sprint_close_skill_runs_the_reviews_rather_than_composing_them(self):
        """Step 2 used to tell a human to do a broad review and a security review.
        Both prompts were then hand-composed at sprint-002's close, and when four
        fix-commits needed re-checking there were no prior findings to bound the
        pass — an unbounded re-review (note bae0b87b)."""
        skill = prose(PLUGIN / "skills" / "sprint-close" / "SKILL.md")
        assert "close.py sprint <id> review" in skill, "the review is still hand-composed"

    def test_the_sprint_close_skill_states_the_confirming_round_shape(self):
        skill = prose(PLUGIN / "skills" / "sprint-close" / "SKILL.md")
        assert "cost a confirming round, except any land names as exempt" in skill
        assert "re-run `close.py sprint <id> review`" in skill
        assert "one story-shaped reviewer over the delta, not another fanout" in skill

    def test_sprint_opening_has_no_tracked_branch_ritual(self):
        skill = prose(PLUGIN / "skills" / "sprint-close" / "SKILL.md")
        assert "sprint_branch" not in skill and "retire" not in skill

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

    def test_the_loop_states_carded_execution_once_and_does_not_grow(self):
        """Constraint 1. The cap is the LIVE size, never a historical one: left at
        5,454 for a file that had shrunk to 2,928, it passed with 2,277 characters
        of padding spliced in — a ratchet with slack certifies instead of checking.
        Re-measure and lower it whenever this file legitimately shrinks."""
        raw = (PLUGIN / "PROCESS.md").read_text()
        assert len(raw) <= 1600, "the execution rule stopped paying for itself"
        process = " ".join(raw.split())
        story = process.split("2. **Story", 1)[1].split("3. **Story close", 1)[0]
        assert "free work" in story and "worktree" in story
        assert "never in the lead's checkout" in story
        assert "practice, not a wall" in story and "data root proves spawn" in story
        assert process.count("worktree") == 1

    def test_system_context_names_every_shipped_prose_document(self):
        """This line rides into every reviewer bundle, so a short list tells a
        reviewer the shipped set is smaller than it is. ENUMERATED from the plugin
        root, never a hand-list: the hand-list went short the day JUDGMENT.md
        shipped and would again for the next document."""
        system = (Path(__file__).parent.parent / ".xp" / "system.md").read_text()
        line = next(line for line in system.splitlines() if line.startswith("- shipped prose"))
        shipped = sorted(doc.name for doc in PLUGIN.glob("*.md"))
        assert shipped, "no shipped prose found — the enumeration itself broke"
        missing = [name for name in shipped if name not in line]
        assert not missing, f"the reviewer is told the shipped set omits: {missing}"

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
        for skill, cap in (
            ("story-close", 330),
            ("sprint-close", 290),
            ("free-close", 85),
            ("create-sprint", 190),
        ):
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

    def test_the_charter_names_the_report_path(self):
        assert "REPORT_PATH" in (PLUGIN / "agents" / "story-reviewer.md").read_text()

    def test_the_plan_reviewer_charter_asks_for_a_file(self):
        assert (
            "write your findings to a file"
            in (PLUGIN / "agents" / "plan-reviewer.md").read_text().lower()
        )

    def test_the_plan_reviewer_charter_has_five_checks(self):
        """A structural count, not a token grep — it certifies the count only,
        not that the duty is followed. The sprint-cap clause is NOT one of the
        five: capacity is the lead's slate review, and the charter says so in its
        own paragraph (story-052). Restoring it here would keep this green."""
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

    def test_every_shared_rule_pointer_names_JUDGMENT(self):
        bar = "silent or corrupting (false green, corrupted record, unreviewed merge)"
        assert bar in prose(PLUGIN / "JUDGMENT.md")
        for name in ("story-reviewer", "sprint-reviewer"):
            charter = prose(PLUGIN / "agents" / f"{name}.md")
            assert bar not in charter, f"{name} still ships a second copy of the bar"
            assert "JUDGMENT" in charter, f"{name} dropped the copy without pointing"
            assert "PROCESS" not in charter, f"{name} kept a stale pointer"
        pointers = {
            PLUGIN / "skills" / "story-close" / "SKILL.md": "file noted ones per JUDGMENT.md",
            PLUGIN / "skills" / "sprint-close" / "SKILL.md": (
                "JUDGMENT.md carries the polarity contract"
            ),
            PLUGIN / "scripts" / "bookkeep.py": "file these per JUDGMENT.md",
        }
        for path, pointer in pointers.items():
            assert pointer in prose(path), f"stale rule pointer in {path}"
