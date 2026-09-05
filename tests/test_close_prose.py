"""Shipped prose matches the mechanism. Split from test_close.py at sprint-004 open."""

import json
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


def killed_review(tmp_path, g, head=None):
    """The disk a killed reviewer leaves — the tree it was launched against and a
    readable report — without paying for a spawn to produce it."""
    data = tmp_path / "data"
    at = {
        "head": head or g("rev-parse", "HEAD").stdout.strip(),
        "digest": "",
        "base": g("merge-base", "main", "HEAD").stdout.strip(),
        "card": "####" + (data / "plan.md").read_text().split("####", 1)[1],
        "noun": "story story-042",
    }
    (data / "markers" / "story-042.review-launch").write_text(json.dumps(at))
    report = data / "reports" / "story-042.round-1.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"fixed": [], "blocking": [], "noted": []}))


class TestShippedProseMatchesTheMechanism:
    """The prose is what a consuming project believes. story-012a AC 11/12."""

    def test_sprint_salvage_is_a_walkable_help_route(self):
        r = subprocess.run(
            [sys.executable, str(CLOSE), "sprint", "walk", "salvage", "--help"],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0 and "salvage" in r.stdout, r.stderr

    def test_review_and_salvage_give_distinct_dirty_tree_advice(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        killed_review(tmp_path, g)
        dirt = repo / "uninspected.txt"
        dirt.write_text("dead reviewer work\n")

        ordinary = close(repo, env, "review")
        recovery = close(repo, env, "salvage")

        assert ordinary.returncode == recovery.returncode == 2
        assert "commit or stash first" in ordinary.stderr, ordinary.stderr
        assert "dead reviewer's uninspected work" in recovery.stderr, recovery.stderr
        assert "read it before committing or discarding it" in recovery.stderr, recovery.stderr
        assert ordinary.stderr != recovery.stderr
        assert "git reset --hard" not in ordinary.stderr + recovery.stderr
        assert dirt.read_text() == "dead reviewer work\n"

    def test_a_moved_head_does_not_order_a_reset_over_the_lines_it_says_to_read(self, tmp_path):
        """Both hazards at once. HEAD moving still has to be disclosed by sha — a
        salvage that moved it silently is the worse defect — but `git reset --hard`
        must not be the unconditional offer there: it discards the uninspected work
        this same refusal sends the lead to read, which is the tree story-093 kept."""
        repo, env, g = make_repo(tmp_path)
        launched = g("rev-parse", "HEAD").stdout.strip()
        (repo / "lead.py").write_text("committed after the kill\n")
        g("add", "-A")
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "the lead moved HEAD")
        killed_review(tmp_path, g, launched)
        dirt = repo / "uninspected.txt"
        dirt.write_text("dead reviewer work\n")

        recovery = close(repo, env, "salvage")

        assert recovery.returncode == 2 and launched[:8] in recovery.stderr, recovery.stderr
        assert "yours to keep or undo" not in recovery.stderr, recovery.stderr
        assert "only after reading the uncommitted lines" in recovery.stderr, recovery.stderr
        assert dirt.read_text() == "dead reviewer work\n"

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
        lead-facing sentence said whose each was. The executable pin holds both
        copies directly — ownership in the LEAD's, where that bug was written, and
        the handoff in the executor's — so a later edit cannot silently remove the
        newest, least-obvious sentence. "sprint review" is
        excluded by name: `close.py sprint <id> review` already holds it.
        """
        process = prose(PLUGIN / "PROCESS.md").lower()
        executor = prose(PLUGIN / "EXECUTOR.md").lower()
        for name, text in (("PROCESS.md", process), ("EXECUTOR.md", executor)):
            assert "slate review" in text, f"{name}: the lead's review is unnamed"
            assert "execution plan review" in text, f"{name}: plan review unnamed"
            assert "sprint review" not in text, f"{name}: close.py owns that phrase"
        assert "the planner writes the plan" in process, "PROCESS.md: the plan's owner is unnamed"
        assert "re-read the reviewed plan" in executor, "EXECUTOR.md drops the handoff"

    def test_a_mandatory_step_failing_twice_routes_to_escalation(self):
        teammate = " ".join(prose(PLUGIN / "EXECUTOR.md").lower().split())
        assert "mandatory step fails twice for infrastructure reasons" in teammate
        assert "scripts/work.py note" in teammate
        assert "commit the coherent in-flight change and hand back" in teammate

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

    def test_the_loop_states_carded_execution_once(self):
        raw = (PLUGIN / "PROCESS.md").read_text()
        process = " ".join(raw.split())
        story = process.split("2. **Story", 1)[1].split("3. **Story close", 1)[0]
        assert "free work" in story and "worktree" in story
        assert "never in the lead's checkout" in story
        assert "practice, not a wall" in story and "data root proves spawn" in story
        assert process.count("worktree") == 1

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
        # WHICH file is logical round one is pinned separately: story-114 moved round
        # one to its own number, and `location` survived that move as the legacy name,
        # so the two literals above green while the copies disagree about today.
        numbered = "<story-id>.round-1.md"
        assert numbered in charter, "the charter stopped naming round one's own artifact"
        assert numbered in design, "DESIGN.md stopped naming round one's own artifact"
