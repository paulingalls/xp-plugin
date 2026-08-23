"""story-007's bootstrap leaf: which Worktree bootstrap values run, which are
prose, and which refuse. Split from test_spawn.py at v0.6.2, when the refusal
half pushed that file past the 500-line cap.
Verify: pytest -q tests/test_spawn_bootstrap.py"""

from spawn_helpers import (
    make_repo,
    set_system_md,
    spawn,
    stub_claude,
)


class TestBootstrap:
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
        set_system_md(repo, "**Stack**: python")
        assert spawn(repo, env, "story-042").returncode == 0

    def test_red_bootstrap_refuses_and_does_not_launch(self, tmp_path):
        """A teammate in a non-working tree is the silent-corrupting failure."""
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        set_system_md(repo, "- Worktree bootstrap: `exit 3`")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "bootstrap" in r.stderr.lower()
        assert not rec.exists()  # nothing launched
