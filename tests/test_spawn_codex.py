"""The codex executor leg: its argv, its sandbox posture, and the shared guards.
Extracted from test_spawn.py at story-026, which took it to 498 of the 500-line
cap — over-cap means extract, not scroll (constraint 8).
Verify: pytest -q tests/test_spawn_codex.py"""

import json
import subprocess
from itertools import pairwise

from session_start_helpers import HOOKS_JSON
from spawn_helpers import in_tree, make_repo, spawn, stub_codex


class TestCodexExecutor:
    """story-021. Every divergence between the two legs is a silent hole in one
    of them, so these assert the codex leg reaches the SAME shared guards."""

    def argv(self, tmp_path, executor="codex/gpt-5.6-terra/medium"):
        repo, env, _g = make_repo(tmp_path, executor=executor)
        stub_codex(tmp_path, network=True)
        r = spawn(repo, env, "story-042", "--dry-run")
        assert r.returncode == 0, r.stderr
        for ln in r.stdout.splitlines():
            if ln.startswith("codex "):
                return ln.split(" ")
        raise AssertionError(f"no codex argv in: {r.stdout[:400]}")

    def test_the_assembled_argv(self, tmp_path):
        argv = self.argv(tmp_path)
        pairs = list(pairwise(argv))
        for pair in [
            ("-m", "gpt-5.6-terra"),
            ("-c", "model_reasoning_effort=medium"),
            ("--sandbox", "workspace-write"),
            ("--add-dir", str(tmp_path / "data")),
            # XP_ROLE (self-close bar — close.py reads an ABSENT value as `lead`)
            # and GIT_AUTHOR_* (the reviewer's signature) reach codex's shell only
            # through shell_environment_policy, and ALL THREE of these keys can
            # strip them: inherit chooses the source set, exclude drops patterns
            # from it, include_only keeps only patterns. Each is a
            # ~/.codex/config.toml key, so a consuming developer's file — not the
            # lead's, which is the only one the story-021 walk measured — decides.
            # All three measured present on 0.147.0 from codex's own error text
            # for a bad value; `[]` is each list key's own default, which is why
            # pinning it is a restoration and not a new policy.
            ("-c", "shell_environment_policy.inherit=all"),
            ("-c", "shell_environment_policy.exclude=[]"),
            ("-c", "shell_environment_policy.include_only=[]"),
            # story-026: the executor is the leg that NESTS a headless plan
            # review, and the workspace-write sandbox blocks DNS (curl EXIT=6,
            # measured 0.149.0) — without this the nested harness dies on first
            # contact. Executor only: see TestCodexReviewerLeg for the other half.
            ("-c", "sandbox_workspace_write.network_access=true"),
        ]:
            assert pair in pairs, f"{pair} missing from {argv}"
        assert "-e" not in argv, "codex has no -e; the effort rides -c (spike-falsified)"
        # asserting `--sandbox workspace-write` PRESENT bounds nothing on its own:
        # 0.147.0 ships a documented override that silently voids it, and it is what
        # a reader reaches for the first time the sandbox denies a write
        assert "--dangerously-bypass-approvals-and-sandbox" not in argv, argv
        # exactly one: note 6193855e probed the git-common-dir widening
        # unnecessary on 0.147.0, and a second --add-dir is that widening returning
        assert argv.count("--add-dir") == 1, argv

    def test_a_two_part_spec_carries_no_effort(self, tmp_path):
        argv = self.argv(tmp_path, executor="codex/gpt-5.6-terra")
        assert not [a for a in argv if a.startswith("model_reasoning_effort")], argv

    def test_the_stub_reds_when_the_flag_comes_back(self, tmp_path, monkeypatch):
        """Constraint 2, polarity flipped with the rule (bug 296c3e4f): a stub that
        cannot red against its target defect certifies. Re-ADD `--disable
        unified_exec` to the REAL builder's output and run the real stub on it —
        the pair is what the spawn ships, and re-disabling it is now the defect."""
        import spawn as spawn_mod

        # monkeypatch, not os.environ[...]: this test runs IN-PROCESS, and a bare
        # assignment leaves every later data_root() in this worker pointed at a
        # tmp_path pytest has already deleted
        monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
        argv = spawn_mod.codex_argv("gpt-5.6-terra", "medium")
        stub_codex(tmp_path)
        mutated = [argv[0], "exec", "--disable", "unified_exec", *argv[2:]]
        r = subprocess.run(
            # cwd matters even on the arm that must die early: with the guard
            # mutated away, the stub reaches its `git commit` and commits wherever
            # it stands — the repo under review, if that is the cwd
            [str(tmp_path / "bin" / "codex"), *mutated[1:]],
            input="",
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert r.returncode != 0 and "unified_exec" in r.stderr, r.stderr
        intact = subprocess.run(
            [str(tmp_path / "bin" / "codex"), *argv[1:]],
            input="",
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert intact.returncode == 0, intact.stderr

    def test_the_stub_reds_in_BOTH_network_directions(self, tmp_path, monkeypatch):
        """Constraint 2: the executor CARRYING the flag and the reviewer NOT
        carrying it are one property with two failure modes, and a stub that
        cannot red on either certifies both. Feed each leg's real argv to the
        stub expecting the other posture — both must die."""
        import spawn as spawn_mod

        monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
        legs = {
            r: spawn_mod.agent_argv("codex", "m", "", "json", r) for r in ("executor", "reviewer")
        }
        net = "sandbox_workspace_write.network_access=true"
        assert net in legs["executor"] and net not in legs["reviewer"]
        for wants_network, argv in ((True, legs["reviewer"]), (False, legs["executor"])):
            stub_codex(tmp_path, commit=False, network=wants_network)
            r = subprocess.run(
                [str(tmp_path / "bin" / "codex"), *argv[1:]],
                input="",
                capture_output=True,
                text=True,
                cwd=tmp_path,
            )
            assert r.returncode != 0 and "network" in r.stderr, (wants_network, r.stderr)

    def test_absent_from_path_refuses_before_any_worktree_is_cut(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        r = spawn(repo, env, "story-042")  # no stub_codex: nothing named codex on PATH
        assert r.returncode == 2
        assert "codex" in r.stderr and "install" in r.stderr.lower(), r.stderr
        assert not (tmp_path / "data" / "worktrees" / "story-042").exists()
        branches = in_tree(repo, env, "branch", "--format=%(refname:short)")
        assert "story-042" not in branches, branches

    def test_dry_run_still_prints_the_argv_with_nothing_installed(self, tmp_path):
        """Reading the argv a harness WOULD take is what a lead does before
        installing it — review.run already exempts its dry run, and one rule with
        two implementations is this repo's most-filed defect class."""
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        r = spawn(repo, env, "story-042", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "--sandbox workspace-write" in r.stdout, r.stdout[:400]
        assert "--disable unified_exec" not in r.stdout, r.stdout[:400]

    def test_the_teammates_shell_keeps_codexs_own_long_process_facility(self, tmp_path):
        """unified_exec is codex's persistent-session exec tool — start a process,
        poll it, write its stdin — and it is what carries a tool call past the bound
        codex puts on one. Disabling it made TEAMMATE.md's mandatory plan review
        unrunnable on the harness that mechanism was written FOR: the bound is
        `timeout_ms` on codex's own shell action, a per-call value THE MODEL supplies
        with no config override, and a model with nothing telling it a review takes
        5-15 minutes guesses low — the field teammate's two attempts died at codex's
        own "timed out after 120008 ms" and "180009 ms" (note 095395d4; the field
        report's "~120s cap" was those two guesses, not a fixed bound — a bare
        `sleep 700` survives, note 97bfbca0).

        The bar it was disabled under is outdated, not wrong-at-the-time (Paul, at
        this fix): DESIGN §3 justified it as protecting `PreToolUse`, and this plugin
        ships no PreToolUse hook at all — the gates that bind a codex leg are
        close.py running Verify and the git-hook wall, which a shell obtained any
        way at all still meets.
        """
        import spawn as spawn_mod

        argv = spawn_mod.codex_argv("gpt-5.6-terra", "medium")
        assert ("--disable", "unified_exec") not in list(pairwise(argv)), (
            "the codex teammate cannot run a command past the shell bound: " + " ".join(argv)
        )

    def test_the_premise_that_reversal_rests_on_reds_when_it_expires(self):
        """Enabling unified_exec is safe only while nothing of OURS runs at
        PreToolUse, and that premise is unbuilt-design, not a decision: DESIGN §7
        item 4 still plans an exit-status-masking PreToolUse block. Nothing else in
        the suite would notice the day it lands, so the hole would reopen silently
        on the harness the reversal was made for."""
        hooks = json.loads(HOOKS_JSON.read_text())["hooks"]
        assert "PreToolUse" not in hooks, (
            "a PreToolUse hook now ships and codex's write_stdin bypasses it — either"
            " re-add `--disable unified_exec` to spawn.codex_argv (DESIGN §3 row 80,"
            " which costs the codex teammate its plan review again) or register the"
            " hook claude-only. Whichever wins, row 80 and DESIGN §7 item 4 must say so"
        )

    def test_every_shipped_harness_has_its_own_argv_and_stream(self):
        """Three registries, two files: HARNESS_INSTALL admits a harness, agent_argv
        builds for it, STREAMS parses it. agent_argv FALLS THROUGH to claude, so a
        third harness admitted without a builder launches the wrong binary silently;
        a missing STREAMS row crashes after the worktree is cut and the card flipped."""
        from spawn import HARNESS_INSTALL, agent_argv
        from teammate_tee import STREAMS

        assert set(STREAMS) == set(HARNESS_INSTALL)
        for harness in HARNESS_INSTALL:
            assert agent_argv(harness, "m", "high", "json")[0] == harness

    def test_a_dirty_codex_teammate_hits_the_shared_completion_guard(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        stub_codex(tmp_path, commit=False, write_file=True)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "uncommitted" in r.stderr, r.stderr

    def test_a_codex_teammate_with_no_commits_hits_the_shared_guard(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        stub_codex(tmp_path, commit=False)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "no commits of its own" in r.stderr, r.stderr
