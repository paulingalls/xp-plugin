"""Dogfood-vs-shipped drift: our .xp/ was hand-built at Sprint 0 and we never run
xp-setup on ourselves, so what we dogfood can diverge from what we ship and nothing
would say so. Extracted from test_setup.py at v0.6.2, when that file passed the
500-line cap — constraint 8 says shed a cohesive leaf, never delete tests to fit.

These pin the SHAPE the code parses, never the content: a project's tiers,
constraints and stories are legitimately its own.
"""

import re
from pathlib import Path


class TestDogfoodMatchesTheScaffold:
    """The stale-marketplace-build bug is this class: we tested what we were not
    running."""

    REPO = Path(__file__).parent.parent
    OURS = REPO / ".xp"
    SHIPPED = REPO / "plugins" / "xp-plugin" / "templates"

    def keys(self, path):
        return {ln.split(":")[0] for ln in path.read_text().splitlines() if re.match(r"^\w+:", ln)}

    def test_our_config_carries_every_key_the_scaffold_ships(self):
        from session_start import missing_template_keys

        missing = missing_template_keys(
            (self.SHIPPED / "config.yml").read_text(), (self.OURS / "config.yml").read_text()
        )
        assert not missing, f"we never exercise the shipped keys: {missing}"

    def test_the_scaffold_ships_no_key_we_invented_without_seeding(self):
        """The reverse drift: a key we rely on that a scaffolded repo never gets.
        sprint_branch is seeded COMMENTED, so it counts as shipped."""
        shipped = self.SHIPPED / "config.yml"
        text = shipped.read_text()
        extra = {k for k in self.keys(self.OURS / "config.yml") - self.keys(shipped)}
        for key in sorted(extra):
            assert f"# {key}:" in text, f"we use {key!r} and the scaffold never mentions it"

    def test_the_shipped_plan_templates_card_passes_the_gate_that_reads_it(self):
        """b4c3ef33's practice, applied to the third template we parse: the card
        this project HANDS a new user is fed to the credential leg's own check,
        not to a fixture restating it.

        The template taught `Verify: EDIT-ME  # the command(s) ...` — plural, with
        nothing saying the line is load-bearing — and a consuming project wrote its
        commands as bullets below the label, which parses EMPTY (bug abc052f2).
        """
        from close import story_card, verify_refusal

        card = story_card((self.SHIPPED / "plan.md").read_text(), "story-000")[0]
        assert verify_refusal("story-000", card) == "", card

    def test_the_shipped_system_md_label_is_one_spawn_can_read(self):
        """The drift this class exists for, in the file it had no arm for. Every
        bootstrap test writes its OWN unbolded line, so the form the TEMPLATE
        teaches was never once fed to the parser — and it was unreadable: the
        template bolds the label like all its other fields, which put `**`
        between label and colon. Silent, because an unread line and an absent
        one returned the same empty string.

        Takes the template's own label verbatim and gives it a value that must
        run, so a future reformat of that line reds here rather than in a
        consuming project's unprepared worktree.
        """
        from spawn import bootstrap_command

        label = next(
            ln.split(":", 1)[0]
            for ln in (self.SHIPPED / "system.md").read_text().splitlines()
            if "Worktree bootstrap" in ln
        )
        assert bootstrap_command(f"{label}: `echo ok`")[0] == "echo ok", (
            f"spawn cannot read the label the template teaches: {label!r}"
        )

    def test_an_unedited_bootstrap_placeholder_refuses_rather_than_skipping(self):
        """Same discipline as tests.fast: EDIT-ME reddening the wall — a scaffold
        ships a placeholder, and a placeholder that silently means "no bootstrap"
        is the defect, not the default. Pinned so it stays a decision."""
        from spawn import bootstrap_command

        command, problem = bootstrap_command((self.SHIPPED / "system.md").read_text())
        assert not command and problem, "the unedited placeholder read as a valid no-op"

    def test_the_shipped_plan_parses_with_the_parser_sprint_close_uses(self):
        """Was a PAIR: it also read THIS repo's .xp/plan.md, so our live plan and
        the template could not drift apart unnoticed. story-019 moved our plan to
        the state root, which is machine-dependent and ambient — reading it here
        would be the observed state constraint 11 forbids — so the drift alarm is
        gone, not moved. AC7's migration walk re-asserts the parse where the live
        plan is present by construction."""
        from sprint_close import sprint_stories

        assert sprint_stories((self.SHIPPED / "plan.md").read_text(), "1"), (
            "a scaffolded repo cannot run a sprint close: the seeded plan has no"
            " `### Sprint N` section for sprint_stories to find"
        )
