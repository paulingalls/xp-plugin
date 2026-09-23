"""The reviewer bound (story-012b). Extracted from test_spawn_run.py at the
Sprint 27 close to keep it under the 500-line cap."""

import subprocess

import pytest


class TestAgentWallClock:
    """story-012b bounds the reviewer. cmd_spawn's launch call site has no
    except, so a bound there kills a running story with a traceback and abandons
    its worktree — the two legs must therefore stay bounded and unbounded."""

    def test_the_reviewer_is_bounded(self, monkeypatch, tmp_path):
        import spawn

        monkeypatch.setenv("XP_AGENT_TIMEOUT", "0.01")
        monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))  # else the real root's ledger
        with pytest.raises(subprocess.TimeoutExpired):
            spawn.run_agent(
                ["/bin/sh", "-c", "sleep 1"], tmp_path, "", "reviewer", "claude", "story-042-review"
            )

    def test_the_teammate_launch_is_not(self, monkeypatch, tmp_path):
        """Bounding cmd_spawn's launch call site kills a running story and
        abandons its worktree, so the teammate no longer runs through
        run_agent (that path is reviewer-only) — it runs through
        teammate_tee.run_teammate, which this asserts is unbounded.

        The sleep stays because only outliving the clock can prove the clock is
        absent, and it shrank with it: 0.1s against XP_AGENT_TIMEOUT=0.01 is the
        10x margin `sleep 2` against 1 was, and shell start-up only widens it.
        """
        from teammate_tee import run_teammate

        monkeypatch.setenv("XP_AGENT_TIMEOUT", "0.01")
        rc = run_teammate(
            ["/bin/sh", "-c", 'sleep 0.1; echo \'{"type": "result", "is_error": false}\''],
            tmp_path,
            "",
            "story-042",
            tmp_path / "data",
        )
        assert rc == 0, "a teammate story legitimately outruns any bound"

    @pytest.mark.parametrize("role", ["plan-reviewer", "reviewer"])
    def test_no_reviewer_launch_receives_a_git_credential(self, monkeypatch, tmp_path, role):
        import spawn

        seen = {}
        monkeypatch.setenv("GIT_AUTHOR_NAME", "inherited lead")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "lead@example.com")
        monkeypatch.setattr(
            spawn,
            "run_stream",
            lambda *a, **k: (
                seen.update(argv=a[0], env=a[6], options=k)
                or subprocess.CompletedProcess(a[0], 0, "", "")
            ),
        )
        argv = ["claude", "--dangerously-skip-permissions"]
        spawn.run_agent(argv, tmp_path, "", role, "claude", "review")
        assert not [k for k in seen["env"] if k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))]
        assert seen["env"]["XP_HARNESS"] == "claude"
        assert seen["argv"] == ["claude", "--dangerously-skip-permissions"]
        assert seen["options"]["widen_git"] is False
