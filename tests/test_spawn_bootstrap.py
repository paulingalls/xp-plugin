"""story-007's bootstrap leaf: which Worktree bootstrap values run, which are
prose, and which refuse. Split from test_spawn.py at v0.6.2, when the refusal
half pushed that file past the 500-line cap.
Verify: pytest -q tests/test_spawn_bootstrap.py"""

import re
import shutil
import subprocess

import pytest
from spawn_helpers import (
    make_repo,
    set_system_md,
    spawn,
    stub_claude,
)


class TestBootstrap:
    def test_missing_system_refuses_before_the_worktree_and_repairs_the_file(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_claude(tmp_path)
        (repo / ".xp" / "system.md").unlink()
        g("add", "-A")
        g("commit", "-qm", "drop system.md")

        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and ".xp/system.md" in r.stderr
        assert not (tmp_path / "data" / "worktrees" / "story-042").exists()
        command = re.search(r"`([^`]+)`", r.stderr).group(1)
        assert subprocess.run(command, shell=True, cwd=repo).returncode == 0
        again = spawn(repo, env, "story-042")
        assert again.returncode == 2 and "bootstrap line" in again.stderr
        assert "is missing" not in again.stderr

    def test_missing_xp_remediation_creates_the_directory(self, tmp_path):
        repo, env, g = make_repo(tmp_path, executor="claude/sonnet/medium")
        stub_claude(tmp_path)
        shutil.rmtree(repo / ".xp")
        g("add", "-A")
        g("commit", "-qm", "drop xp directory")

        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and ".xp/system.md" in r.stderr
        command = re.search(r"`([^`]+)`", r.stderr).group(1)
        assert subprocess.run(command, shell=True, cwd=repo).returncode == 0
        again = spawn(repo, env, "story-042")
        assert again.returncode == 2 and "bootstrap line" in again.stderr

    def test_backticked_command_runs_in_the_worktree(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: `touch bootstrapped`")
        assert spawn(repo, env, "story-042").returncode == 0
        assert (tmp_path / "data" / "worktrees" / "story-042" / "bootstrapped").exists()

    def test_prose_mentioning_a_backticked_path_does_not_execute(self, tmp_path):
        """The whole value must be one backticked command, or the path in
        "none needed — see `docs/setup.md`" would execute. The no-execute half is
        unchanged; what changed is that this now REFUSES instead of proceeding
        silently — an ambiguous line is one the author must disambiguate, and a
        teammate launched past it gets an unprepared tree either way."""
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: none needed — see `touch pwned`")
        r = spawn(repo, env, "story-042")
        assert not (tmp_path / "data" / "worktrees" / "story-042" / "pwned").exists()
        assert r.returncode == 2 and "bootstrap" in r.stderr.lower()
        assert not rec.exists()  # nothing launched

    def test_two_backticked_spans_are_prose_not_a_command(self, tmp_path):
        """`(.+)` was greedy, so the template's own example wording — "`npm ci`
        or `uv sync`" — fullmatched and ran verbatim under a shell, where the
        inner backticks are command substitution."""
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: `touch a` or `touch b`")
        assert spawn(repo, env, "story-042").returncode == 2
        assert not rec.exists()

    def test_an_explicit_none_is_a_legitimate_no_op(self, tmp_path):
        """Not every project needs a bootstrap. `none` must stay silent, or the
        refusal below would block every project that correctly has nothing to run."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: none needed")
        assert spawn(repo, env, "story-042").returncode == 0

    def test_the_bolded_label_the_template_teaches_is_read(self, tmp_path):
        """The reported defect. Every other field in templates/system.md is
        bolded, so an author following it bolds this one — and the `**` sat
        between label and colon, so the substring scan missed, returned empty,
        and spawn's walrus skipped the block. No bootstrap, no warning, no
        nonzero exit: a teammate launched into a tree nothing prepared."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_system_md(repo, "**Worktree bootstrap**: `touch bootstrapped`")
        assert spawn(repo, env, "story-042").returncode == 0
        assert (tmp_path / "data" / "worktrees" / "story-042" / "bootstrapped").exists()

    def test_a_present_but_unreadable_line_refuses_rather_than_skipping(self, tmp_path):
        """The half that makes the defect above LOUD rather than silent: empty
        conflated "no line" (legitimate) with "a line I could not read" (a
        defect). Only the second refuses, and it names the line."""
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: run bun install first")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "bootstrap" in r.stderr.lower()
        assert not rec.exists()

    def test_an_unreadable_line_refuses_before_the_worktree_exists(self, tmp_path):
        """Reading the line needs no tree, and a refusal that costs one is a
        refusal the corrected retry cannot get past: it hits "already spawned"
        and names the wrong problem."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: run bun install first")
        assert spawn(repo, env, "story-042").returncode == 2
        assert not (tmp_path / "data" / "worktrees" / "story-042").exists()
        set_system_md(repo, "- Worktree bootstrap: `touch bootstrapped`")
        assert spawn(repo, env, "story-042").returncode == 0

    def test_no_line_at_all_stays_silent(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_system_md(repo, "**Stack**: `touch not-a-bootstrap`")
        assert spawn(repo, env, "story-042").returncode == 0
        tree = tmp_path / "data" / "worktrees" / "story-042"
        assert not (tree / "not-a-bootstrap").exists()

    @pytest.mark.parametrize("action", ["bootstrap", "teardown"])
    @pytest.mark.parametrize("prefix", ["", "- ", "* "])
    @pytest.mark.parametrize("bold", [False, True])
    @pytest.mark.parametrize("padding", ["", "  "])
    def test_the_label_grammar_matches_its_optional_parts(self, action, prefix, bold, padding):
        from bookkeep import worktree_command

        wanted = f"Worktree {action}"
        label = f"**{wanted}**" if bold else wanted
        line = f"{padding}{prefix}{label}{padding}: `echo ok`"
        assert worktree_command(line, action) == ("echo ok", "")

    def test_a_mixed_shape_duplicate_still_refuses(self):
        from bookkeep import worktree_command

        system = "- **Worktree bootstrap**: `make dev`\n#### Worktree bootstrap: `npm ci`"
        command, problem = worktree_command(system, "bootstrap")
        assert not command and "appears more than once" in problem

    def test_an_untaught_label_shape_refuses_without_running(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        set_system_md(repo, "#### Worktree bootstrap: `touch not-accepted`")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "Worktree bootstrap label" in r.stderr
        assert "optionally prefixed with '- ' or '* ' and optionally bolded" in r.stderr
        tree = tmp_path / "data" / "worktrees" / "story-042"
        assert not (tree / "not-accepted").exists()

    def test_red_bootstrap_refuses_and_does_not_launch(self, tmp_path):
        """A teammate in a non-working tree is the silent-corrupting failure."""
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: `exit 3`")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "bootstrap" in r.stderr.lower()
        assert not rec.exists()  # nothing launched
