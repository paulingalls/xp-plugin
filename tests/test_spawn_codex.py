"""The codex executor leg: its argv, its sandbox posture, and the shared guards.
Extracted from test_spawn.py at story-026, which took it to 498 of the 500-line
cap — over-cap means extract, not scroll (constraint 8).
Verify: pytest -q tests/test_spawn_codex.py"""

import json
import os
import subprocess
from itertools import pairwise

import pytest
from session_start import missing_template_keys
from session_start_helpers import HOOKS_JSON
from spawn_helpers import SPAWN, in_tree, make_repo, spawn, stub_codex


class TestCodexExecutor:
    """story-021. Every divergence between the two legs is a silent hole in one
    of them, so these assert the codex leg reaches the SAME shared guards."""

    def argv(self, tmp_path, executor="codex/gpt-5.6-terra/medium"):
        repo, env, _g = make_repo(tmp_path, executor=executor)
        stub_codex(tmp_path, sandbox="danger-full-access")
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
            # story-035, carried by free-2026-08-24-codex-and-digest: ONE string
            # lifts docker, loopback and codex-in-codex together, and it is the
            # posture the claude leg has always had (no sandbox flag at all).
            ("--sandbox", "danger-full-access"),
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
        ]:
            assert pair in pairs, f"{pair} missing from {argv}"
        assert "-e" not in argv, "codex has no -e; the effort rides -c (spike-falsified)"
        # every `sandbox_workspace_write.*` key is a sub-key of a posture we no
        # longer take: one left behind is a second posture-shaped string that
        # decides nothing, and the next reader cannot tell which one governs
        assert not [a for a in argv if a.startswith("sandbox_workspace_write.")], argv
        # still banned, and not for the sandbox half: it also routes approvals
        # through an automatic model review, which is judgment where a gate belongs
        assert "--dangerously-bypass-approvals-and-sandbox" not in argv, argv
        # exactly one: note 6193855e probed the git-common-dir widening
        # unnecessary on 0.147.0, and a second --add-dir is that widening returning
        assert argv.count("--add-dir") == 1, argv

    def test_no_config_key_keeps_the_v071_argv_byte_for_byte(self, tmp_path):
        assert self.argv(tmp_path) == [
            "codex",
            "exec",
            "--json",
            "-c",
            "shell_environment_policy.inherit=all",
            "-c",
            "shell_environment_policy.exclude=[]",
            "-c",
            "shell_environment_policy.include_only=[]",
            "--sandbox",
            "danger-full-access",
            "--add-dir",
            str(tmp_path / "data"),
            "-m",
            "gpt-5.6-terra",
            "-c",
            "model_reasoning_effort=medium",
            "-",
        ]

    def test_the_commented_template_key_does_not_pin_a_posture(self):
        template = (SPAWN.parents[1] / "templates" / "config.yml").read_text()
        seeds = [line for line in template.splitlines() if "codex_sandbox:" in line]
        assert len(seeds) == 1
        assert missing_template_keys(seeds[0], "") == []
        active = seeds[0].removeprefix("# ")
        assert missing_template_keys(active, "") == [
            ("codex_sandbox", "codex_sandbox: danger-full-access")
        ]

    def test_this_repo_sets_the_key_its_template_only_seeds(self, monkeypatch):
        """Constraint 12, and nothing else guards it: the template seeds the key
        COMMENTED, so test_dogfood is green whether we set it or not — deleting
        our line leaves the whole suite green while we stop executing the surface
        we ship. Compared to the RESOLVED value, so an absent key (which resolves
        to the default) is not mistaken for a chosen one."""
        import spawn
        from close import config_flat

        monkeypatch.chdir(SPAWN.parents[3])
        configured = config_flat("codex_sandbox")
        assert spawn.resolve_codex_sandbox("codex", configured) == (configured, "")

    @pytest.mark.parametrize("posture", ["workspace-write", "danger-full-access"])
    def test_each_configured_posture_is_launched_and_reported(self, tmp_path, posture):
        repo, env, g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        config = repo / ".xp" / "config.yml"
        config.write_text(config.read_text() + f"codex_sandbox: {posture}\n")
        g("add", "-A")
        g("commit", "-qm", "choose codex posture")
        rec = stub_codex(tmp_path, sandbox=posture)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr
        argv = json.loads(rec.read_text())["argv"]
        expected = {
            "workspace-write": (
                "codex sandbox: workspace-write — no outbound network — DNS, loopback,"
                " docker and a nested harness are all denied, so TEAMMATE.md's mandatory"
                " plan_review.py cannot reach an API from a teammate's shell;"
                " danger-full-access lifts them"
            ),
            "danger-full-access": (
                "codex sandbox: danger-full-access — no OS confinement — network, docker"
                " and nested codex all reachable"
            ),
        }
        assert argv[argv.index("--sandbox") + 1] == posture
        assert expected[posture] in r.stderr.splitlines(), r.stderr

    @pytest.mark.parametrize("posture", ["unknown-posture", "read-only"])
    def test_invalid_posture_refuses_before_cutting_a_worktree(self, tmp_path, posture):
        repo, env, g = make_repo(tmp_path, executor="codex/gpt-5.6-terra/medium")
        config = repo / ".xp" / "config.yml"
        config.write_text(config.read_text() + f"codex_sandbox: {posture}\n")
        g("add", "-A")
        g("commit", "-qm", "bad codex posture")
        stub_codex(tmp_path, sandbox=posture)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2
        if posture == "read-only":
            assert "every role" in r.stderr and "deliverable" in r.stderr
            assert "unrecognised" not in r.stderr
        else:
            assert "workspace-write" in r.stderr and "danger-full-access" in r.stderr
        assert not (tmp_path / "data" / "worktrees" / "story-042").exists()
        assert "story-042" not in in_tree(repo, env, "branch", "--format=%(refname:short)")

    def test_a_two_part_spec_carries_no_effort(self, tmp_path):
        argv = self.argv(tmp_path, executor="codex/gpt-5.6-terra")
        assert not [a for a in argv if a.startswith("model_reasoning_effort")], argv

    def test_the_stub_reds_when_the_flag_comes_back(self, tmp_path, monkeypatch):
        """Constraint 2, polarity flipped with the rule (bug 296c3e4f): a stub that
        cannot red against its target defect certifies. Re-ADD `--disable
        unified_exec` to the REAL builder's output and run the real stub on it —
        the pair is what the spawn ships, and re-disabling it is now the defect."""
        from harness import codex_argv

        # monkeypatch, not os.environ[...]: this test runs IN-PROCESS, and a bare
        # assignment leaves every later data_root() in this worker pointed at a
        # tmp_path pytest has already deleted
        monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
        argv = codex_argv("gpt-5.6-terra", "medium", "danger-full-access")
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

    def test_the_stub_reds_when_a_confining_posture_returns(self, tmp_path, monkeypatch):
        """Constraint 2: the posture assertions above are worth what this stub can
        red against. Feed the REAL argv to a stub demanding the posture we left
        behind — it must die — and to one demanding the posture we ship, where it
        must live. A stub that accepts both certifies whichever is passed."""
        import spawn as spawn_mod

        monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
        argv = spawn_mod.agent_argv("codex", "m", "", "json", "danger-full-access")
        for want, dies in (("workspace-write", True), ("danger-full-access", False)):
            stub_codex(tmp_path, commit=False, sandbox=want)
            r = subprocess.run(
                [str(tmp_path / "bin" / "codex"), *argv[1:]],
                input="",
                capture_output=True,
                text=True,
                cwd=tmp_path,
            )
            assert (r.returncode != 0) is dies, (want, r.returncode, r.stderr)
            if dies:
                assert "sandbox" in r.stderr, r.stderr

    def test_the_launch_prints_the_posture_it_actually_took(self, tmp_path, monkeypatch, capsys):
        """AC1: an invisible relaxation is the same defect as the invisible
        restriction that produced this card. Printed from `run_stream`, so the
        REVIEWER legs print it too — a reviewer's posture going unprinted is the
        specific defect here, and it went unprinted for two sprints while the
        lead believed it the other way round.

        Fault-injected by launching a posture we do NOT ship: a line composed
        from the decision instead of read off the argv reports the shipped value
        on both arms and could never red.
        """
        import spawn as spawn_mod
        from teammate_tee import run_stream

        monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
        shipped = spawn_mod.agent_argv("codex", "m", "", "json", "danger-full-access")
        confined = [a if a != "danger-full-access" else "workspace-write" for a in shipped]
        for argv, posture in ((shipped, "danger-full-access"), (confined, "workspace-write")):
            stub_codex(tmp_path, commit=False, sandbox=posture)
            run_stream(
                [str(tmp_path / "bin" / "codex"), *argv[1:]],
                tmp_path,
                "",
                "posture-probe",
                tmp_path / "data",
                "codex",
                dict(os.environ),
            )
            assert f"codex sandbox: {posture}" in capsys.readouterr().err

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
        assert "--sandbox danger-full-access" in r.stdout, r.stdout[:400]
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
        from harness import codex_argv

        argv = codex_argv("gpt-5.6-terra", "medium", "danger-full-access")
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
            " re-add `--disable unified_exec` to harness.codex_argv (DESIGN §3 row 80,"
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
            assert agent_argv(harness, "m", "high", "json", "danger-full-access")[0] == harness

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
