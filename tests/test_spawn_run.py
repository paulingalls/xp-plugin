"""story-017: the teammate run — tee, wall clock, completion.
Split from test_spawn.py at sprint-004 open."""

import subprocess
import sys

import pytest
from spawn_helpers import (  # noqa: F401
    CARD,
    CONFIG,
    SPAWN,
    _total,
    block_commits,
    in_tree,
    make_repo,
    set_system_md,
    spawn,
    stub_claude,
    stub_claude_requiring_verbose,
    trunk_sha,
)


class TestAgentWallClock:
    """story-012b bounds the reviewer. cmd_spawn's launch call site has no
    except, so a bound there kills a running story with a traceback and abandons
    its worktree — the two legs must therefore stay bounded and unbounded."""

    def test_the_reviewer_is_bounded(self, monkeypatch, tmp_path):
        import spawn

        monkeypatch.setenv("XP_AGENT_TIMEOUT", "1")
        with pytest.raises(subprocess.TimeoutExpired):
            spawn.run_agent(
                ["/bin/sh", "-c", "sleep 5"], tmp_path, "", "reviewer", "claude", "story-042-review"
            )

    def test_the_teammate_launch_is_not(self, monkeypatch, tmp_path):
        """Bounding cmd_spawn's launch call site kills a running story and
        abandons its worktree, so the teammate no longer runs through
        run_agent (that path is reviewer-only) — it runs through
        teammate_tee.run_teammate, which this asserts is unbounded."""
        from teammate_tee import run_teammate

        monkeypatch.setenv("XP_AGENT_TIMEOUT", "1")
        rc = run_teammate(
            # 2 against XP_AGENT_TIMEOUT=1 proves unbounded as well as 3 did, and
            # this is the suite's one literal sleep (debt 15aec3fc named it).
            ["/bin/sh", "-c", 'sleep 2; echo \'{"type": "result", "is_error": false}\''],
            tmp_path,
            "",
            "story-042",
            tmp_path / "data",
        )
        assert rc == 0, "a teammate story legitimately outruns any wall clock"

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
        assert seen["argv"] == ["claude", "--dangerously-skip-permissions"]
        assert seen["options"]["widen_git"] is False


class TestLiveTee:
    """teammate_tee.tee_stream is a pure function — no subprocess involved —
    so the pipe-blocking / deadlock behaviour it must have is trivial to
    fault-inject (constraints.md #2)."""

    def test_every_line_is_logged_verbatim(self):
        from teammate_tee import tee_stream

        lines = [
            '{"type": "system", "subtype": "init"}\n',
            "not json at all\n",
            '{"type": "result", "is_error": false, "num_turns": 1}\n',
        ]
        logged = []
        result = tee_stream(lines, logged.append, lambda _l: None)
        assert logged == lines
        assert result == {"type": "result", "is_error": False, "num_turns": 1}

    def test_unparseable_lines_are_skipped_not_erroring(self):
        from teammate_tee import tee_stream

        lines = ["garbage\n", '{"type": "result", "is_error": false}\n']
        result = tee_stream(lines, lambda _l: None, lambda _l: None)
        assert result == {"type": "result", "is_error": False}

    def test_a_stream_with_no_terminal_result_returns_none(self):
        """The ONLY error condition: everything else in this file is tolerated."""
        from teammate_tee import tee_stream

        result = tee_stream(['{"type": "system"}\n'], lambda _l: None, lambda _l: None)
        assert result is None

    def test_a_failed_run_is_not_reported_as_ok(self):
        """`is_error` is one of the four things the card asks the closing line to
        carry, and it is the only one a lead ACTS on. Gutting both renderings to
        a constant "ok" left the whole suite green — a teammate that failed was
        announced as a teammate that succeeded."""
        from teammate_tee import closing_line, summarize_event

        failed = {"type": "result", "is_error": True, "num_turns": 2}
        assert "ERROR" in closing_line("story-042", failed)
        assert "error" in summarize_event(failed)
        assert "ERROR" not in closing_line("story-042", dict(failed, is_error=False))
        assert "error" not in summarize_event(dict(failed, is_error=False))

    def test_a_log_write_failure_warns_but_does_not_stop_draining(self):
        """Fault-inject: a writer that reds on its second call. Every line must
        still reach it and the run must complete — ceasing to drain deadlocks a
        healthy child writing to a full pipe."""
        from teammate_tee import tee_stream

        lines = [f'{{"type": "system", "subtype": "{i}"}}\n' for i in range(4)]
        seen = []

        def flaky_write(line):
            seen.append(line)
            if len(seen) == 2:
                raise OSError("disk full")

        out = []
        result = tee_stream(lines, flaky_write, out.append)
        assert seen == lines  # every line still reached the writer
        assert any("warning" in o for o in out)  # the loop warned
        assert sum(o.startswith("[system]") for o in out) == 4  # the run completed
        assert result is None  # no result object in this fixture — consistent, not asserted-away


class TestStreamJsonRequiresVerbose:
    def test_stream_json_without_verbose_reds_against_the_real_refusal(self, tmp_path):
        claude = stub_claude_requiring_verbose(tmp_path)
        r = subprocess.run(
            [str(claude), "--output-format", "stream-json"], capture_output=True, text=True
        )
        assert r.returncode == 1 and "verbose" in r.stderr

    def test_the_teammates_actual_argv_greens_against_the_same_stub(self, tmp_path):
        from spawn import claude_argv

        claude = stub_claude_requiring_verbose(tmp_path)
        argv = claude_argv("sonnet", "medium", "stream-json")[1:]  # drop the "claude" argv[0]
        assert "--dangerously-skip-permissions" in argv
        r = subprocess.run([str(claude), *argv], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_review_py_still_passes_json_untouched(self):
        """review.py's own argv is explicit ("json"), so this story must not
        have touched it into carrying --verbose it never asked for."""
        from spawn import claude_argv

        assert "--verbose" not in claude_argv("opus", "", "json")


class TestLiveLogDuringARun:
    def test_the_log_is_readable_while_the_teammate_is_still_running(self, tmp_path):
        """LIVE, the property the mid-stream-kill case below cannot reach: that
        one reads the log only after run_teammate returns, by which point the
        `with open(...)` has closed and flushed it — it greens with the per-line
        flush deleted. This one reads the log from a second thread while the
        child is still alive and blocked, so only a flushed write can satisfy it.
        """
        import threading
        import time

        from teammate_tee import log_path, run_teammate

        script = tmp_path / "slow.py"
        sentinel = tmp_path / "go"
        script.write_text(
            "import json, sys, time, pathlib\n"
            "print(json.dumps({'type': 'system', 'subtype': 'init'}))\n"
            "sys.stdout.flush()\n"
            f"while not pathlib.Path({str(sentinel)!r}).exists(): time.sleep(0.01)\n"
            "print(json.dumps({'type': 'result', 'is_error': False, 'num_turns': 1}))\n"
        )
        run = threading.Thread(
            target=run_teammate,
            args=([sys.executable, str(script)], tmp_path, "", "story-live", tmp_path / "data"),
            kwargs={"out": lambda _l: None},
        )
        run.start()
        log = log_path(tmp_path / "data", "story-live")
        mid = ""
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and '"subtype": "init"' not in mid:
            mid = log.read_text() if log.exists() else ""
            time.sleep(0.02)
        sentinel.write_text("go")
        run.join(30)
        assert '"subtype": "init"' in mid, (
            "the teammate's first line was not on disk while it was still running"
            f" — the log is not live. Log held: {mid!r}"
        )

    def test_a_child_that_dies_before_reading_the_prompt_reports_only_the_diagnosis(
        self, tmp_path, monkeypatch
    ):
        """`subprocess.run(input=...)` swallowed the broken pipe; the hand-rolled
        feeder thread this story replaced it with does not, and an unhandled
        exception in a thread prints a twelve-line traceback the lead reads
        BEFORE the one line that says what went wrong. Constructed with a prompt
        past the pipe buffer so the EPIPE is certain rather than a race — the
        real 4k prompt hits the same write whenever the child loses it."""
        import threading

        from teammate_tee import run_teammate

        died = []
        monkeypatch.setattr(threading, "excepthook", lambda arg: died.append(arg.exc_type))
        script = tmp_path / "refuse.py"
        script.write_text("import sys\nsys.exit(1)\n")  # never reads stdin
        rc = run_teammate(
            [sys.executable, str(script)],
            tmp_path,
            "x" * (1 << 20),
            "story-epipe",
            tmp_path / "data",
            out=lambda _l: None,
        )
        assert rc == 1
        assert died == [], f"the feeder thread died unhandled: {died}"

    def test_the_log_holds_lines_emitted_before_a_mid_stream_kill(self, tmp_path):
        from teammate_tee import log_path, run_teammate

        script = tmp_path / "flaky.py"
        script.write_text(
            "import json, os, signal, sys, time\n"
            "print(json.dumps({'type': 'system', 'subtype': 'init'}))\n"
            "sys.stdout.flush()\n"
            "time.sleep(0.1)\n"
            "os.kill(os.getpid(), signal.SIGKILL)\n"
        )
        rc = run_teammate(
            [sys.executable, str(script)], tmp_path, "", "story-kill", tmp_path / "data"
        )
        assert rc != 0  # killed mid-stream: no terminal result object survived
        log = log_path(tmp_path / "data", "story-kill").read_text()
        assert '"subtype": "init"' in log  # what it emitted before dying is on disk


class TestTeammateCompletion:
    """Given a completed teammate, spawn refuses unless the worktree is CLEAN
    and carries at least one commit of its own — a process exiting 0 is not
    the same claim as a story being done."""

    def test_a_dirty_tree_is_refused_naming_both_recoveries(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path, commit=False, write_file=True)  # leaves a stray, uncommitted file
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2
        assert "dirty" in r.stderr.lower() or "uncommitted" in r.stderr.lower()
        assert "commit" in r.stderr.lower() and "worktree remove" in r.stderr

    def test_no_commits_of_its_own_is_refused_naming_both_recoveries(self, tmp_path):
        """`trunk..HEAD` is still the vacuous spelling constraints.md #11 forbids,
        for a second reason since story-019: the flip is no longer a commit, so
        that range counts the teammate's own work and greens on the very run this
        must red. Only HEAD-after-the-flip lets it red."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path, commit=False)  # clean tree, but nothing committed
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2
        assert "no commits" in r.stderr.lower()
        assert "commit" in r.stderr.lower() and "worktree remove" in r.stderr

    def test_the_printed_recovery_actually_lets_the_story_be_re_spawned(self, tmp_path):
        """A guard whose remediation does not work is a wall. Before story-019 the
        [in-progress] flip was a commit on the story branch, so `git branch -D`
        undid it and "re-spawning" worked as printed. The flip now lives in the
        clone's shared plan, which the branch delete does not touch — so the
        printed recovery dead-ends on spawn's own [in-progress] refusal, and BOTH
        refusals have to name the flip-back for the lead to get out.

        The middle arm is the point: it executes the old prescription exactly and
        shows it is not enough, so this cannot pass by re-spawning for free."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path, commit=False)
        plan = tmp_path / "data" / "plan.md"
        refused = spawn(repo, env, "story-042")
        assert refused.returncode == 2
        assert str(plan) in refused.stderr and "[ready]" in refused.stderr

        tree = tmp_path / "data" / "worktrees" / "story-042"
        remove = ["worktree", "remove", "--force", str(tree)]
        for args in (remove, ["branch", "-D", "ada/story-042-demo-story"]):
            subprocess.run(["git", *args], cwd=repo, env=env, check=True)
        blocked = spawn(repo, env, "story-042")
        assert blocked.returncode == 2 and "[in-progress]" in blocked.stderr
        assert str(plan) in blocked.stderr and "[ready]" in blocked.stderr

        plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))
        stub_claude(tmp_path)  # this time the teammate commits
        assert spawn(repo, env, "story-042").returncode == 0

    def test_a_crashed_teammate_that_left_work_behind_still_names_it(self, tmp_path):
        """The likeliest way a run "ends with a dirty tree" is that it never
        ended: a crash, a kill, a launch the binary refused. Returning the
        child's code straight from the stream loop skips the completion guard
        on exactly that path, so the lead is told the stream had no result
        object and never told about the file left uncommitted underneath it."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path, commit=False, write_file=True, emit_result=False)
        r = spawn(repo, env, "story-042")
        assert r.returncode != 0
        assert "teammate-left-this-uncommitted.txt" in r.stderr
        assert "worktree remove" in r.stderr

    def test_a_leftover_from_the_bootstrap_is_not_blamed_on_the_teammate(self, tmp_path):
        """`Worktree bootstrap:` runs BEFORE the teammate and can leave the tree
        dirty by itself — `npm install` rewriting a lockfile is the ordinary
        case. Reading the raw porcelain accuses the teammate of it and tells the
        lead to commit it by hand; the baseline is the tree as the teammate
        RECEIVED it, which is why both halves of the guard compare against the
        post-flip state and not against ambient state (constraints.md #11)."""
        repo, env, _g = make_repo(tmp_path)
        (repo / ".xp" / "system.md").write_text(
            "# System\n- Worktree bootstrap: `touch vendored-by-bootstrap.txt`\n"
        )
        subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True)
        subprocess.run(["git", "commit", "-qm", "bootstrap"], cwd=repo, env=env, check=True)
        stub_claude(tmp_path, add_all=False)  # commits its own work, stages nothing else
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr
        assert (
            tmp_path / "data" / "worktrees" / "story-042" / "vendored-by-bootstrap.txt"
        ).exists()

    def test_a_tree_git_cannot_read_is_refused_rather_than_certified(self, tmp_path):
        """Reading only stdout makes a FAILED git indistinguishable from a clean
        one: empty porcelain reads as "nothing uncommitted" and an empty HEAD
        never equals the flip's, so both halves pass and the spawn reports a
        finished story it never actually looked at."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path, break_git=True)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2, r.stdout
        assert "worktree remove" in r.stderr

    def test_a_clean_committed_run_is_accepted(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)  # default: commits and emits a result
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr


class TestClosingLineAndLog:
    def test_the_closing_line_is_printed_from_the_result_object(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr
        assert "3 turns" in r.stdout and "$0.05" in r.stdout and "1.2s" in r.stdout

    def test_the_log_is_project_scoped_and_appends_under_a_header_on_respawn(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        log = tmp_path / "data" / "logs" / "story-042.log"
        assert log.exists()
        first = log.read_text()
        assert "===== spawn story-042 " in first

        # a re-spawn after removing the first worktree appends, not truncates
        tree = tmp_path / "data" / "worktrees" / "story-042"
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(tree)],
            cwd=repo,
            env=env,
            check=True,
        )
        subprocess.run(["git", "branch", "-D", "ada/story-042-demo-story"], cwd=repo, env=env)
        plan = tmp_path / "data" / "plan.md"  # the flip is shared now, not branch-local
        plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))
        assert spawn(repo, env, "story-042").returncode == 0
        second = log.read_text()
        assert second.startswith(first)
        assert second.count("===== spawn story-042 ") == 2


class TestFirstSpawnInAScaffoldedRepo:
    """Broad review B3: the worktree path is the DEFAULT and the one the plugin
    exists for, and it had no dirty-tree guard — so the literal shipped sequence
    (xp-setup, fill in the plan, spawn) tracebacked and orphaned git state."""

    def test_an_uncommitted_scaffold_refuses_instead_of_tracebacking(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_claude(tmp_path)
        g("checkout", "-q", "main")
        # The literal shipped sequence: xp-setup, fill in the plan, spawn. Since
        # story-019 the plan edit is OUT of the repo and dirties nothing — the
        # uncommitted artifact is the scaffold itself, which is what setup leaves.
        (repo / ".xp" / "system.md").write_text("# System\n- freshly scaffolded\n")
        (tmp_path / "data" / "plan.md").write_text(
            (tmp_path / "data" / "plan.md").read_text()
            + "\n#### story-777 — fresh   [planned]\nVerify: true\n"
        )
        # cleared through the leg, so the guard under test is still the one that
        # fires: a hand-typed [ready] refuses at the credential and never reaches it
        assert spawn(repo, env, "ready", "story-777").returncode == 0
        r = spawn(repo, env, "story-777")
        assert r.returncode == 2, r.stdout
        assert "Traceback" not in r.stderr
        assert "commit" in r.stderr.lower(), "the refusal must name the fix"
        assert not (tmp_path / "data" / "worktrees").exists(), "orphaned worktree"


class TestCodexTee:
    """story-021: the codex teammate rides teammate_tee, not a second copy. Its
    stream is `codex exec --json`, measured on 0.149.0 at story-028 — the two legs
    diverge in the per-line parse and nowhere else."""

    def test_codex_native_stream_requires_a_terminal_agent_message(self, tmp_path):
        from teammate_tee import run_teammate

        out = []
        line = '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}'
        rc = run_teammate(
            ["/bin/sh", "-c", f"echo '{line}'"],
            tmp_path,
            "",
            "story-042",
            tmp_path / "data",
            harness="codex",
            out=out.append,
        )
        assert rc == 0
        assert "[item.completed] agent_message" in out, "the tail names the item, not the event"

    def test_the_same_append_only_log_contract(self, tmp_path):
        from teammate_tee import run_teammate

        for _ in range(2):
            run_teammate(
                ["/bin/sh", "-c", "echo one-line"],
                tmp_path,
                "",
                "story-042",
                tmp_path / "data",
                harness="codex",
                out=lambda _l: None,
            )
        log = (tmp_path / "data" / "logs" / "story-042.log").read_text()
        assert log.count("===== spawn story-042 ") == 2, log
        assert log.count("one-line") == 2, log

    def test_a_log_write_failure_still_drains_the_codex_stream(self):
        """Same fault injection as the claude leg, through the shared drain."""
        from teammate_tee import STREAMS, tee_stream

        parse = STREAMS["codex"]
        seen, out = [], []

        def flaky_write(line):
            seen.append(line)
            if len(seen) == 2:
                raise OSError("disk full")

        lines = [f'{{"type":"turn.started","n":{i}}}\n' for i in range(4)]
        tee_stream(lines, flaky_write, out.append, parse)
        assert len(seen) == 4
        assert sum(o == "[turn.started]" for o in out) == 4

    def test_the_claude_leg_still_demands_its_terminal_object(self, tmp_path):
        """The two legs must diverge HERE and nowhere else: dropping the check
        for claude would hide a teammate whose stream died mid-run."""
        from teammate_tee import run_teammate

        errs = []
        run_teammate(
            ["/bin/sh", "-c", "echo not-json"],
            tmp_path,
            "",
            "story-042",
            tmp_path / "data",
            out=lambda _l: None,
            err=errs.append,
        )
        assert any("terminal result" in e for e in errs), errs
