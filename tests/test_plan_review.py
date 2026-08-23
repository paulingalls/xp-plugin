"""Plan review as a headless ROLE, not a harness subagent (story-026).
Verify: pytest -q tests/test_plan_review.py"""

import json
import shutil
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

import pytest
from spawn_helpers import make_repo, spawn, stub_codex

PLUGIN = Path(__file__).parent.parent / "plugins" / "xp-plugin"
PLAN_REVIEW = PLUGIN / "scripts" / "plan_review.py"
# a phrase from the charter BODY: the stub is handed what it must see, so a
# bundle assembled with an empty charter section cannot pass for a real one
CHARTER_MARK = "Checks, in order of payoff"

CONFIG = """release: sprint
sprint_branch: main

roles:
  executor: claude/opus
  reviewer: codex/gpt-5.6-terra/high
  plan-reviewer: {spec}

tests:
  story: true
"""


def stub_planner(tmp_path, findings="ROUND FINDINGS", write_findings=True, motion=""):
    """A fake `claude` that REFUSES a prompt carrying no charter.

    The rubric is the whole value of a review: a leg that lost it would still
    exit 0, print plausible prose and leave a findings file behind. Nothing
    downstream can tell that apart, so the detector belongs at the binary.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launch.json"
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, sys\n"
        "stdin = sys.stdin.read()\n"
        "json.dump({'argv': sys.argv[1:], 'env': dict(os.environ), 'stdin': stdin},"
        f" open({str(rec)!r}, 'w'))\n"
        f"if {CHARTER_MARK!r} not in stdin:\n"
        "    print('error: the prompt carries no charter', file=sys.stderr)\n"
        "    sys.exit(2)\n"
        "m = re.search(r'^FINDINGS_PATH: (.+)$', stdin, re.M)\n"
        "assert m, 'the bundle named no FINDINGS_PATH'\n"
        f"write_findings = {write_findings!r}\n"
        f"motion = {motion!r}\n"
        f"open(m.group(1).strip(), 'w').write({findings!r}) if write_findings else None\n"
        "if motion in ('dirty', 'commit'):\n"
        "    open('drift.txt', 'a').write('reviewer motion\\n')\n"
        "if motion == 'draft':\n"
        f"    open({str(tmp_path / 'draft.md')!r}, 'a').write('reviewer motion\\n')\n"
        "if motion == 'card':\n"
        f"    open({str(tmp_path / 'data' / 'plan.md')!r}, 'a').write('reviewer motion\\n')\n"
        "if motion == 'commit':\n"
        "    import subprocess\n"
        "    subprocess.run(['git', 'add', '-A'], check=True)\n"
        "    subprocess.run(['git', 'commit', '-qm', 'plan reviewer motion'], check=True)\n"
        f"print(json.dumps({{'type': 'result', 'result': {findings!r}}}))\n"
    )
    (bin_dir / "claude").chmod(0o755)
    return rec


def plan_review(repo, env, *args, script=PLAN_REVIEW):
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=repo, env=env, capture_output=True, text=True
    )


def findings_of(rec):
    """The FINDINGS_PATH the reviewer was actually handed."""
    stdin = json.loads(rec.read_text())["stdin"]
    (line,) = [ln for ln in stdin.splitlines() if ln.startswith("FINDINGS_PATH: ")]
    return Path(line.removeprefix("FINDINGS_PATH: "))


class TestTheLaunch:
    def repo(self, tmp_path, spec="claude/haiku/low"):
        repo, env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(CONFIG.format(spec=spec))
        draft = tmp_path / "draft.md"
        draft.write_text("PLAN-SENTINEL: two files, one red test, then the code.\n")
        return repo, env, draft

    def test_the_charter_the_plan_and_the_card_reach_the_reviewer(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path)
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 0, r.stderr
        launch = json.loads(rec.read_text())
        stdin, argv = launch["stdin"], launch["argv"]
        assert CHARTER_MARK in stdin  # the charter, inlined — codex has no --plugin-dir
        assert "PLAN-SENTINEL" in stdin
        assert "demo story" in stdin  # the card slice
        assert "CONSTRAINT-SENTINEL" in stdin
        assert argv[argv.index("--model") + 1] == "haiku"  # the plan-reviewer ROLE
        assert argv[argv.index("--effort") + 1] == "low"
        assert launch["env"]["XP_ROLE"] == "plan-reviewer"  # cannot close
        assert "ROUND FINDINGS" in r.stdout  # returned, not only written

    def test_an_empty_charter_ships_NOTHING(self, tmp_path):
        """The AC's fault injection, CONSTRUCTED rather than mocked: truncate the
        charter in a COPY of the plugin tree and run that copy's script. A missing
        file already refuses through _read_shipped; an empty one is what would
        otherwise ship a bundle with a hollow rubric and no sign of it."""
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path)
        tree = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, tree)
        (tree / "agents" / "plan-reviewer.md").write_text("---\nname: plan-reviewer\n---\n")
        r = plan_review(
            repo, env, "story-042", str(draft), script=tree / "scripts" / "plan_review.py"
        )
        assert r.returncode == 2, r.stdout + r.stderr
        assert "Traceback" not in r.stderr, r.stderr
        assert "charter" in r.stderr.lower(), r.stderr
        assert not rec.exists(), "spent a review on an empty rubric"

    def test_the_findings_path_is_absolute_and_round_scoped(self, tmp_path):
        """One name for a file written once per round destroys the earlier round
        on write, and plan review does run in rounds."""
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path, findings="round one")
        assert plan_review(repo, env, "story-042", str(draft)).returncode == 0
        first = findings_of(rec)
        assert first.is_absolute() and first.name == "story-042.md"
        rec = stub_planner(tmp_path, findings="round two")
        assert plan_review(repo, env, "story-042", str(draft)).returncode == 0
        assert findings_of(rec).name == "story-042.round-2.md"
        assert first.read_text() == "round one"

    def test_success_without_the_required_findings_file_refuses(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path, write_findings=False)
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 2 and "no findings" in r.stderr.lower(), r.stderr
        assert "ROUND FINDINGS" not in r.stdout
        assert rec.exists(), "the fault injection never reached the reviewer"

    @pytest.mark.slow
    def test_report_only_role_refuses_every_guarded_motion(self, tmp_path):
        for motion in ("dirty", "commit", "draft", "card"):
            repo, env, draft = self.repo(tmp_path / motion)
            stub_planner(tmp_path / motion, motion=motion)
            before = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
            ).stdout.strip()
            r = plan_review(repo, env, "story-042", str(draft))
            assert r.returncode == 2 and "changed" in r.stderr.lower(), r.stderr
            if motion == "commit":
                after = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo,
                    env=env,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                assert after != before, "the committed-motion injection never happened"

    def test_a_missing_plan_file_refuses_without_launching(self, tmp_path):
        repo, env, _draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path)
        r = plan_review(repo, env, "story-042", str(tmp_path / "nope.md"))
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr
        assert not rec.exists()

    def test_an_empty_plan_refuses_without_launching(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        draft.write_text("")
        rec = stub_planner(tmp_path)
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 2 and "empty" in r.stderr.lower(), r.stderr
        assert not rec.exists()

    def test_a_missing_story_card_refuses_without_launching(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path)
        r = plan_review(repo, env, "story-nope", str(draft))
        assert r.returncode == 2 and "card" in r.stderr.lower(), r.stderr
        assert not rec.exists()

    def test_dry_run_launches_nothing_and_prints_the_argv(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path)
        r = plan_review(repo, env, "story-042", str(draft), "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "--model haiku" in r.stdout and CHARTER_MARK in r.stdout
        assert not rec.exists()
        assert not (tmp_path / "data" / "plans").exists()

    def test_a_codex_plan_reviewer_is_hardened_and_stays_network_off(self, tmp_path):
        """It nests nothing, so it gets no network — the other half of the
        executor's flag, asserted on the leg that must not have it."""
        repo, env, draft = self.repo(tmp_path, spec="codex/gpt-5.6-terra/high")
        rec = stub_codex(tmp_path, commit=False, network=False, findings="ROUND FINDINGS")
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 0, r.stderr
        argv = json.loads(rec.read_text())["argv"]
        assert ("--sandbox", "workspace-write") in list(pairwise(argv)), argv
        assert ("--disable", "unified_exec") not in list(pairwise(argv)), argv
        assert argv[argv.index("-m") + 1] == "gpt-5.6-terra"
        assert CHARTER_MARK in json.loads(rec.read_text())["stdin"]
        assert "ROUND FINDINGS" in r.stdout


class TestTheProfileCarriesTheInvocation:
    """AC2: the teammate profile's plan-review section IS the invocation. A codex
    teammate has no --plugin-dir, so the charter is not in its tree at all — and
    the profile may not carry the charter body either (3693 tokens against a 2500
    target). What it carries is the command that reaches both."""

    def rendered(self, tmp_path, executor):
        root = tmp_path / executor.split("/")[0]
        repo, env, _g = make_repo(root, executor=executor)
        r = spawn(repo, env, "story-042", "--dry-run")
        assert r.returncode == 0, r.stderr
        return r.stdout

    def test_both_harnesses_are_handed_the_command(self, tmp_path):
        for executor in ("claude/opus", "codex/gpt-5.6-terra/high"):
            profile = self.rendered(tmp_path, executor)
            (bullet,) = [b for b in profile.split("- **") if b.startswith("Multi-file change?")]
            section = bullet.split("- **")[0]
            assert str(PLAN_REVIEW) in section, section
            assert "python3" in section, section


class TestIncompleteReviewIsVisibleToTheLead:
    """A plan review that dies reaches the lead ONLY if the teammate volunteers it
    (field report, Legacy: theirs did, and nothing made it). The evidence of a
    skipped gate is an ABSENCE, and absences leave no artifact.

    So the marker is written at START and removed on SUCCESS, not written on
    failure: the failure that matters is an external kill (exit 124, measured —
    codex's shell timeout_ms is model-supplied and defaults to ~10s), and a killed
    process writes nothing on its way out.
    """

    def repo(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(CONFIG.format(spec="claude/haiku/low"))
        draft = tmp_path / "draft.md"
        draft.write_text("# draft plan\nstep 1\n")
        return repo, env, draft

    def marker(self, tmp_path):
        return tmp_path / "data" / "markers" / "story-042.plan-review-incomplete"

    def test_a_review_that_writes_no_findings_leaves_the_marker(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        stub_planner(tmp_path, write_findings=False)
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode != 0, r.stdout
        assert self.marker(tmp_path).exists(), "nothing records that the gate did not run"

    def test_a_completed_review_leaves_none(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        stub_planner(tmp_path)
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 0, r.stderr
        assert not self.marker(tmp_path).exists(), "a clean review must not accuse itself"

    def test_a_review_killed_from_outside_still_leaves_it(self, tmp_path):
        """The arm the whole design is for: SIGKILL, so nothing runs on the way out.
        The marker must already be on disk before the reviewer is launched."""
        import os
        import signal

        repo, env, draft = self.repo(tmp_path)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "claude").write_text(
            "#!/usr/bin/env python3\n"
            "import os, signal, sys\n"
            "sys.stdin.read()\n"
            "os.kill(os.getppid(), signal.SIGKILL)\n"
        )
        (bin_dir / "claude").chmod(0o755)
        proc = plan_review(repo, env, "story-042", str(draft))
        assert proc.returncode != 0
        assert self.marker(tmp_path).exists(), "a killed review left no trace at all"
        assert os and signal


class TestTheReviewOutlivesItsCaller:
    """The gate must not depend on a model choosing the surviving invocation.

    Measured twice in the field, once per harness: a codex teammate's foreground
    call was killed at the model's own timeout guess (exit 124), and a claude
    teammate backgrounded the review and yielded, which ends a headless run and
    orphaned it. So the SCRIPT detaches the review and waits on it, and a caller
    that dies leaves a review that finishes.
    """

    def repo(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(CONFIG.format(spec="claude/haiku/low"))
        draft = tmp_path / "draft.md"
        draft.write_text("# draft plan\nstep 1\n")
        return repo, env, draft

    def slow_planner(self, tmp_path, seconds=4, findings="SLOW FINDINGS"):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        rec = tmp_path / "launch.json"
        (bin_dir / "claude").write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, re, sys, time\n"
            "stdin = sys.stdin.read()\n"
            f"open({str(rec)!r}, 'a').write('LAUNCH\\n')\n"
            f"time.sleep({seconds})\n"
            "m = re.search(r'^FINDINGS_PATH: (.+)$', stdin, re.M)\n"
            f"open(m.group(1).strip(), 'w').write({findings!r})\n"
            f"print(json.dumps({{'type': 'result', 'result': {findings!r}}}))\n"
        )
        (bin_dir / "claude").chmod(0o755)
        return rec

    def test_a_killed_caller_leaves_a_review_that_finishes(self, tmp_path):
        import time

        repo, env, draft = self.repo(tmp_path)
        self.slow_planner(tmp_path, seconds=4)
        import os
        import signal

        proc = subprocess.Popen(
            [sys.executable, str(PLAN_REVIEW), "story-042", str(draft)],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        time.sleep(1.5)
        # the GROUP, not the process: a harness timeout takes the shell and every
        # descendant with it, which is what killed the field review. Killing only
        # the direct child leaves the reviewer running and passes vacuously.
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()

        plans = tmp_path / "data" / "plans"
        for _ in range(80):
            if any(p.read_text().strip() for p in plans.glob("story-042*.md")):
                return
            time.sleep(0.25)
        raise AssertionError(f"the review died with its caller: {list(plans.glob('*'))}")

    def test_a_second_call_joins_the_running_review_instead_of_starting_one(self, tmp_path):
        import time

        repo, env, draft = self.repo(tmp_path)
        rec = self.slow_planner(tmp_path, seconds=4)
        first = subprocess.Popen(
            [sys.executable, str(PLAN_REVIEW), "story-042", str(draft)],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(1.5)
        first.kill()
        first.wait()
        again = plan_review(repo, env, "story-042", str(draft))
        assert again.returncode == 0, again.stderr
        assert "SLOW FINDINGS" in again.stdout, again.stdout
        assert rec.read_text().count("LAUNCH") == 1, "a second reviewer was launched"
