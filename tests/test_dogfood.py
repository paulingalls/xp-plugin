"""Dogfood-vs-shipped drift: our .xp/ was hand-built at Sprint 0 and we never run
xp-setup on ourselves, so what we dogfood can diverge from what we ship and nothing
would say so. Extracted from test_setup.py at v0.6.2, when that file passed the
500-line cap — constraint 8 says shed a cohesive leaf, never delete tests to fit.

These pin the SHAPE the code parses, never the content: a project's tiers,
constraints and stories are legitimately its own.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

# LC_ALL=C ALONE PROVES NOTHING: PEP 538 silently coerces a C locale to C.UTF-8, so
# the character count came out right for a reason the wall did not own. Disabling
# coercion and UTF-8 mode is what makes the locale test able to red.
C_LOCALE = {"LC_ALL": "C", "LANG": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}


class TestDogfoodMatchesTheScaffold:
    """The stale-marketplace-build bug is this class: we tested what we were not
    running."""

    REPO = Path(__file__).parent.parent
    OURS = REPO / ".xp"
    SHIPPED = REPO / "plugins" / "xp-plugin" / "templates"

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

        missing = missing_template_keys(
            (self.SHIPPED / "config.yml").read_text(), (self.OURS / "config.yml").read_text()
        )
        assert not missing, f"we never exercise the shipped keys: {missing}"

    def test_shipped_coverage_guidance_names_no_test_runner_or_selection_syntax(self):
        plugin = self.REPO / "plugins/xp-plugin"
        # Every file rather than a suffix whitelist: the two githooks-* templates carry
        # no extension, and a shell hook is exactly where a runner name would land.
        shipped = {
            path: path.read_text(errors="replace")
            for path in plugin.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        assert len(shipped) > 40, "scanned nothing — a green here would certify (constraint 2)"
        forbidden = ("pytest", "py.test", "bun test", "node id", "::")
        named = [
            f"{path.relative_to(plugin)} names {term!r}"
            for path, text in shipped.items()
            for term in forbidden
            if term in text.lower()
        ]
        assert not named, named

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

    def cap_value(self, path):
        line = next(
            ln for ln in path.read_text().splitlines() if ln.startswith("constraints_chars_cap:")
        )
        return int(line.split(":", 1)[1].split("#", 1)[0])

    def test_constraints_character_cap_is_the_same_in_both_configs(self):
        ours = self.cap_value(self.OURS / "config.yml")
        assert ours == self.cap_value(self.SHIPPED / "config.yml") == 4_500

    def run_constraints_wall(
        self, tmp_path, cap, size, character="x", tier="fast", path=None, write=True
    ):
        xp = tmp_path / ".xp"
        xp.mkdir(exist_ok=True)
        setting = "" if cap is None else f"constraints_chars_cap: {cap}\n"
        tiers = "".join(f"  {name}: true\n" for name in ("fast", "story", "full"))
        (xp / "config.yml").write_text(f"{setting}tests:\n{tiers}")
        if write:
            (xp / "constraints.md").write_text(character * size, encoding="utf-8")
        hook_lib = self.SHIPPED / "hook-lib.sh"
        env = dict(os.environ) | {"HOOK_LIB": str(hook_lib)} | C_LOCALE
        if path is not None:
            env["PATH"] = path
        return subprocess.run(
            ["sh", "-c", f'. "$HOOK_LIB"; run_tier {tier}'],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_the_wall_refuses_when_the_MEASUREMENT_itself_fails(self, tmp_path):
        """A gate that reports green having run nothing is worse than no gate —
        hook-lib.sh opens with that rule and constraints_size used to break it: an
        empty `count` makes `[ "" -gt N ]` error, which reads as under-cap. One
        injection per guard: no python3 on PATH, and a constraints.md the reader
        cannot open. The first matches the STANZA'S OWN SENTENCE rather than the
        bare word `python3`, because the shell prints `python3: command not found`
        itself — measured: with the `command -v` guard deleted the looser match
        still saw `python3` and `nothing measured`, so it pinned nothing.
        """
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for tool in ("sed", "head", "sh", "cat"):
            found = shutil.which(tool)
            if found:
                (bin_dir / tool).symlink_to(found)
        blind = self.run_constraints_wall(tmp_path, 4_500, 10, path=str(bin_dir))
        assert blind.returncode != 0, blind.stdout
        assert "python3 not installed" in blind.stderr, blind.stderr
        assert "nothing measured" in blind.stderr and "then retry" in blind.stderr, blind.stderr

        (tmp_path / ".xp" / "constraints.md").chmod(0o000)
        try:
            unreadable = self.run_constraints_wall(tmp_path, 4_500, 10, write=False)
        finally:
            (tmp_path / ".xp" / "constraints.md").chmod(0o644)
        assert unreadable.returncode != 0, unreadable.stdout
        assert "could not measure" in unreadable.stderr, unreadable.stderr
        assert "then retry" in unreadable.stderr, unreadable.stderr

    def test_scaffolded_wall_refuses_constraints_over_the_character_cap(self, tmp_path):
        red = self.run_constraints_wall(tmp_path, 4_500, 4_501)
        assert red.returncode != 0
        for claim in ("constraints.md", "4501", "4500", "retire", "shorten"):
            assert claim in red.stderr, red.stderr

        green = self.run_constraints_wall(tmp_path, 4_502, 4_501)
        assert green.returncode == 0, green.stderr

    def test_constraints_wall_distinguishes_missing_and_invalid_caps(self, tmp_path):
        missing = self.run_constraints_wall(tmp_path, None, 1)
        assert missing.returncode != 0 and "missing" in missing.stderr
        default = self.cap_value(self.SHIPPED / "config.yml")
        assert f"add `constraints_chars_cap: {default}`" in missing.stderr.lower()
        assert ".xp/config.yml" in missing.stderr
        added = self.run_constraints_wall(tmp_path, default, 1)
        assert added.returncode == 0, added.stderr
        invalid = self.run_constraints_wall(tmp_path, "many", 1)
        assert invalid.returncode != 0 and "invalid" in invalid.stderr

    def test_constraints_wall_counts_unicode_characters_independent_of_locale(self, tmp_path):
        red = self.run_constraints_wall(tmp_path, 4_500, 4_501, "\N{GRINNING FACE}")
        assert red.returncode != 0 and "4501 characters" in red.stderr, red.stderr
        under = self.run_constraints_wall(tmp_path, 4_500, 4_499, "\N{GRINNING FACE}")
        assert under.returncode == 0, under.stderr  # 17,996 BYTES, and still under cap

    def test_every_tier_re_checks_the_character_cap(self, tmp_path):
        """pre-commit is not the only gate that runs it: a scaffolded pre-push runs
        `run_tier story`, and `git merge` fires no pre-commit at all. Wired to fast
        alone, story and full both exited 0 over a cap they were meant to hold."""
        for tier in ("fast", "story", "full"):
            red = self.run_constraints_wall(tmp_path, 4_500, 4_501, tier=tier)
            assert red.returncode != 0, f"run_tier {tier} passed an over-cap constraints.md"
            assert "4500" in red.stderr, red.stderr

    def test_ascii_constraints_at_the_full_cap_fit_the_byte_profile(self, tmp_path):
        from session_start import OUTPUT_CAP
        from session_start_helpers import run_hook

        repo = tmp_path / "repo"
        xp = repo / ".xp"
        xp.mkdir(parents=True)
        (xp / "config.yml").write_text((self.SHIPPED / "config.yml").read_text())
        cap = self.cap_value(self.SHIPPED / "config.yml")  # never a literal: the
        seed = (self.SHIPPED / "constraints.md").read_text()  # cap is what moves
        constraints = seed + "x" * (cap - len(seed))
        assert len(constraints) == cap
        (xp / "constraints.md").write_text(constraints)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        out = run_hook(repo, tmp_path).stdout
        assert len(out.encode()) <= OUTPUT_CAP
        assert constraints in out, "the full ASCII character ceiling does not reach the lead"

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
