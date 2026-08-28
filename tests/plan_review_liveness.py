import os
import signal
import subprocess
import sys
import time

from test_plan_review import CLEAN, CONFIG, PLAN_REVIEW, make_repo, plan_review

# A HANG GUARD, NOT A DEADLINE (constraint 2's second half). The subject is that an
# orphaned review FINISHES, never how fast: the planner stub sleeps 4s by design, so a
# 20s bound left ~5x headroom on an idle box and none under `-n auto` with ~900
# siblings — it red a sprint-9 RELEASE land. Generous costs nothing when the file
# arrives, because the loop breaks on the file and not on the clock.
FINISH_POLLS = 240  # x 0.25s


class TestTheReviewOutlivesItsCaller:
    def repo(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(CONFIG.format(spec="claude/haiku/low"))
        draft = tmp_path / "draft.md"
        draft.write_text("# draft plan\nstep 1\n")
        return repo, env, draft

    def slow_planner(self, tmp_path, seconds=4, findings=CLEAN):
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
        repo, env, draft = self.repo(tmp_path)
        self.slow_planner(tmp_path, seconds=4)
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
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        plans = tmp_path / "data" / "plans"
        for _ in range(FINISH_POLLS):
            if any(p.read_text().strip() for p in plans.glob("story-042*.md")):
                return
            time.sleep(0.25)
        raise AssertionError(f"the review died with its caller: {list(plans.glob('*'))}")

    def test_a_second_call_joins_the_running_review_instead_of_starting_one(self, tmp_path):
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
        assert CLEAN in again.stdout, again.stdout
        assert rec.read_text().count("LAUNCH") == 1, "a second reviewer was launched"
