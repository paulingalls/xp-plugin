"""Dogfood-vs-shipped drift: our .xp/ was hand-built at Sprint 0 and we never run
xp-setup on ourselves, so what we dogfood can diverge from what we ship and nothing
would say so. Extracted from test_setup.py at v0.6.2, when that file passed the
500-line cap — constraint 8 says shed a cohesive leaf, never delete tests to fit.

These pin the SHAPE the code parses, never the content: a project's tiers,
constraints and stories are legitimately its own.
"""

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from constraints_wall_cases import ConstraintsWallCases


class TestDogfoodMatchesTheScaffold(ConstraintsWallCases):
    """The stale-marketplace-build bug is this class: we tested what we were not
    running."""

    REPO = Path(__file__).parent.parent
    OURS = REPO / ".xp"
    SHIPPED = REPO / "plugins" / "xp-plugin" / "templates"

    def test_secret_hook_routes_match(self):
        def hook(text, name):
            lines = text.splitlines()
            start = lines.index(f"{name}:")
            end = next(
                (i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()),
                len(lines),
            )
            return "\n".join(lines[start:end])

        expected = {
            "pre-commit": "secrets_scan_index",
            "pre-merge-commit": "secrets_scan_index",
            "pre-push": "secrets_scan_push",
        }
        for path in (self.SHIPPED / "lefthook.yml", self.REPO / "lefthook.yml"):
            text = path.read_text()
            for hook_name, helper in expected.items():
                route = hook(text, hook_name)
                assert route.count(helper) == 1, f"{path}: {hook_name} does not route {helper}"
                other = {value for value in expected.values() if value != helper}
                assert not any(value in route for value in other)
            route = hook(text, "pre-push")
            scanner = route.split("secrets_scan_push", 1)[1].split("\n", 2)[1]
            assert scanner == "      use_stdin: true"
            # lefthook orders UNPRIORITISED commands alphabetically, so dropping this
            # runs the scan behind the whole tier instead of ahead of it
            assert route.split("    secrets:\n", 1)[1].startswith("      priority: 1\n")

    def keys(self, path):
        lines = path.read_text().splitlines()
        candidates = {}
        for index, line in enumerate(lines):
            if line and not line[0].isspace() and not line.startswith("#") and ":" in line:
                candidates.setdefault(line.split(":", 1)[0], index)

        from close import config_flat

        found = set()
        sentinel = "__dogfood_key_probe__"
        for key, index in candidates.items():
            probe = lines.copy()
            probe[index] = f"{key}: {sentinel}"
            with patch("close.Path") as path_type:
                config = path_type.return_value
                config.exists.return_value = True
                config.read_text.return_value = "\n".join(probe)
                if config_flat(key) == sentinel:
                    found.add(key)
        return found

    def test_our_config_carries_every_key_the_scaffold_ships(self):
        from session_start import missing_template_keys
        from spawn import HARNESS_INSTALL

        shipped_text = (self.SHIPPED / "config.yml").read_text()
        dogfood_text = (self.OURS / "config.yml").read_text()
        missing = missing_template_keys(shipped_text, dogfood_text)
        role_specs = {
            label: {
                key: line.split(":", 1)[1].split("#", 1)[0].strip()
                for key, line in missing_template_keys(text, "")
                if key.startswith("roles.")
            }
            for label, text in (("shipped", shipped_text), ("dogfood", dogfood_text))
        }
        required = {"roles.planner", "roles.slate-reviewer", "roles.card-refresher"}
        redundant = {"roles.story-reviewer", "roles.sprint-reviewer"}
        invalid = {
            (label, key, spec)
            for label, roles in role_specs.items()
            for key, spec in roles.items()
            if len(parts := spec.split("/")) not in (2, 3)
            or not all(parts)
            or parts[0] not in HARNESS_INSTALL
        }
        problems = {
            "missing": missing,
            "required": {label: required - roles.keys() for label, roles in role_specs.items()},
            "parity": role_specs["shipped"].keys() ^ role_specs["dogfood"].keys(),
            "redundant": {label: redundant & roles.keys() for label, roles in role_specs.items()},
            "invalid": invalid,
        }
        assert (
            not missing
            and not any(problems["required"].values())
            and not problems["parity"]
            and not any(problems["redundant"].values())
            and not invalid
        ), problems

    def test_shipped_tree_names_no_repository_relative_plugin_layout(self):
        plugin = self.REPO / "plugins" / "xp-plugin"
        shipped = [
            path for path in plugin.rglob("*") if path.is_file() and "__pycache__" not in path.parts
        ]
        assert len(shipped) > 40, "scanned nothing — a green here would certify"
        leaked = [
            path.relative_to(plugin)
            for path in shipped
            if "plugins/xp-plugin" in path.read_text(errors="replace")
        ]
        assert not leaked, leaked

    def test_shipped_markdown_names_no_unshipped_document(self):
        """Reject uppercase document references the plugin does not itself ship.

        Allowed is the WHOLE shipped tree, not its root: `SKILL.md` ships eight
        times and a root-only enumeration red on prose naming it — a false red
        against a file every adopter has, which teaches the next author to weaken
        the guard. This scans Markdown only, so it says nothing about shipped
        Python strings or ordinary repository vocabulary such as "cap move".
        It deliberately rejects a consuming project's titled document too; use
        a project-neutral phrase.

        AN INITIAL CAPITAL IS REQUIRED and that is not laziness: `plan.md`,
        `work.md`, `system.md` and `round-N.md` are state-root artifacts the
        plugin creates and does not ship, and shipped prose names all four
        legitimately. A case-insensitive pattern reds on every one of them, so
        an all-lowercase leak (`design.md`) passes here by design — the third
        arm below pins that, so a later widening has to face it deliberately."""
        plugin = self.REPO / "plugins" / "xp-plugin"
        corpus = sorted(plugin.rglob("*.md"))
        texts = {str(path.relative_to(plugin)): path.read_text() for path in corpus}
        assert texts, "document discovery found nothing — a green would certify"
        allowed = {path.name for path in corpus}
        leaked = self.unshipped_documents(texts, allowed)
        assert not leaked, f"shipped Markdown names unshipped documents: {leaked}"
        # constraint 2, against the two leaks this guard was written for and the
        # one it is not: DESIGN.md is ours alone, SKILL.md ships eight times.
        assert self.unshipped_documents({"p": "see DESIGN.md"}, allowed)
        assert not self.unshipped_documents({"p": "see SKILL.md"}, allowed)
        assert not self.unshipped_documents({"p": "see design.md"}, allowed)

    @staticmethod
    def unshipped_documents(texts, allowed):
        document = re.compile(r"(?<![A-Za-z0-9_.-])([A-Z][A-Za-z0-9_-]*\.md)\b")
        return [
            (name, doc)
            for name, text in texts.items()
            for doc in document.findall(text)
            if doc not in allowed
        ]

    def test_the_scaffold_ships_no_key_we_invented_without_seeding(self):
        """The reverse drift: a key we rely on that a scaffolded repo never gets."""
        shipped = self.SHIPPED / "config.yml"
        text = shipped.read_text()
        extra = self.keys(self.OURS / "config.yml") - self.keys(shipped)
        for key in sorted(extra):
            assert f"# {key}:" in text, f"we use {key!r} and the scaffold never mentions it"

    def test_a_hyphenated_dogfood_key_is_not_invisible_to_the_drift_alarm(self, tmp_path):
        ours = tmp_path / "config.yml"
        ours.write_text((self.OURS / "config.yml").read_text() + "dogfood-only-key: yes\n")

        extra = self.keys(ours) - self.keys(self.SHIPPED / "config.yml")
        assert "dogfood-only-key" in extra, extra

    def test_the_shipped_plan_templates_card_refuses_its_unedited_placeholder(self):
        """b4c3ef33's practice, applied to the third template we parse: the card
        this project HANDS a new user is fed to the credential leg's own check,
        not to a fixture restating it.

        The template taught `Verify: EDIT-ME  # the command(s) ...` — plural, with
        nothing saying the line is load-bearing — and a consuming project wrote its
        commands as bullets below the label, which parses EMPTY (bug abc052f2).
        """
        from close import story_card, verify_commands

        card = story_card((self.SHIPPED / "plan.md").read_text(), "story-000")[0]
        with pytest.raises(ValueError, match="EDIT-ME"):
            verify_commands("story-000", card)

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

    def test_our_system_md_label_is_one_spawn_can_read(self):
        from spawn import bootstrap_command

        label = next(
            ln.split(":", 1)[0]
            for ln in (self.OURS / "system.md").read_text().splitlines()
            if "Worktree bootstrap" in ln
        )
        assert bootstrap_command(f"{label}: `echo ok`")[0] == "echo ok", label

    def test_an_unedited_bootstrap_placeholder_refuses_rather_than_skipping(self):
        """Same discipline as tests.fast: EDIT-ME reddening the wall — a scaffold
        ships a placeholder, and a placeholder that silently means "no bootstrap"
        is the defect, not the default. Pinned so it stays a decision."""
        from spawn import bootstrap_command

        command, problem = bootstrap_command((self.SHIPPED / "system.md").read_text())
        assert not command and problem, "the unedited placeholder read as a valid no-op"

    def test_the_shipped_teardown_value_is_a_readable_no_op(self):
        from bookkeep import worktree_command

        line = next(
            ln
            for ln in (self.SHIPPED / "system.md").read_text().splitlines()
            if "Worktree teardown" in ln
        )
        assert worktree_command(line, "teardown") == ("", "")

    def test_the_shipped_teardown_timeout_default_is_the_one_the_code_uses(self):
        from bookkeep import TEARDOWN_TIMEOUT

        line = next(
            ln
            for ln in (self.SHIPPED / "config.yml").read_text().splitlines()
            if "teardown_timeout" in ln
        )
        assert f"teardown_timeout: {TEARDOWN_TIMEOUT}" in line, line

    def test_the_digest_bound_the_skill_states_is_the_one_the_hook_enforces(self):
        """Two copies of one number, and only one of them is runnable: the SKILL
        is what a lead reads at the moment of writing the digest, and
        session_start is what refuses over it. Bug c2d7ffdf was exactly this
        drift between two prose copies nobody could run — here the prose copy is
        pinned to the code's, so it reds instead of drifting."""
        from session_start import DIGEST_CAP

        skill = (self.REPO / "plugins/xp-plugin/skills/story-close/SKILL.md").read_text()
        assert f"≤{DIGEST_CAP} lines" in skill, (
            f"the SKILL does not state the {DIGEST_CAP}-line bound the hook enforces"
        )

    def test_setup_offers_the_install_commands_the_spawn_refusal_names(self):
        """Three copies of one identity: the manifests key the marketplace, harness.py
        prints it when a spawn finds a bare harness, and the SKILL offers it at setup.
        Only the code's copy is runnable, so both others pin to it — asserting the
        identity alone left either harness's whole bullet deletable while green."""
        from harness import PLUGIN_INSTALL

        marketplace = json.loads((self.REPO / ".claude-plugin/marketplace.json").read_text())
        manifest = json.loads(
            (self.REPO / "plugins/xp-plugin/.claude-plugin/plugin.json").read_text()
        )
        identity = f"{manifest['name']}@{marketplace['name']}"
        skill = (self.REPO / "plugins/xp-plugin/skills/xp-setup/SKILL.md").read_text()
        for name, command in PLUGIN_INSTALL.items():
            assert identity in command, f"{name}'s install command does not name {identity}"
            assert command in skill, f"setup does not offer {name}: `{command}`"

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
