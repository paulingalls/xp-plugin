"""Uncited plan-review artifact cases."""

import json
from pathlib import Path

from close_helpers import CLAUDE_SH
from slate_review import review_findings_path
from spawn_helpers import make_repo
from test_plan_review import CLEAN, CONFIG, plan_review, stub_planner


def findings_of(rec):
    """The FINDINGS_PATH the reviewer was actually handed."""
    stdin = json.loads(rec.read_text())["stdin"]
    (line,) = [ln for ln in stdin.splitlines() if ln.startswith("FINDINGS_PATH: ")]
    return Path(line.removeprefix("FINDINGS_PATH: "))


class TestPlanReviewArtifacts:
    def repo(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(CONFIG.format(spec="claude/haiku/low"))
        draft = tmp_path / "draft.md"
        draft.write_text("PLAN-SENTINEL: two files, one red test, then the code.\n")
        return repo, env, draft

    def test_the_findings_path_is_absolute_and_round_scoped(self, tmp_path):
        """One name for a file written once per round destroys the earlier round
        on write, and plan review does run in rounds."""
        repo, env, draft = self.repo(tmp_path)
        first_report = '{"status":"clean","reasons":[],"summary":"round one"}'
        rec = stub_planner(tmp_path, findings=first_report)
        first_run = plan_review(repo, env, "story-042", str(draft))
        assert first_run.returncode == 0
        first = findings_of(rec)
        assert first.is_absolute() and first.name == "story-042.round-1.md"
        rec = stub_planner(
            tmp_path, findings='{"status":"clean","reasons":[],"summary":"round two"}'
        )
        second_run = plan_review(repo, env, "story-042", str(draft))
        second = findings_of(rec)
        assert second_run.returncode == 0 and second.name == "story-042.round-2.md"
        assert first.read_text() == first_report
        handoffs = [run.stderr.splitlines()[-1] for run in (first_run, second_run)]
        assert all("read the disposition" in line for line in handoffs)
        assert all("re-read the reviewed plan" in line for line in handoffs)
        assert str(first) in handoffs[0] and str(second) in handoffs[1]
        assert handoffs[0] != handoffs[1]

    def test_a_gapped_legacy_tree_allocates_after_the_maximum_round(self, tmp_path, monkeypatch):
        _repo, env, _draft = self.repo(tmp_path)
        monkeypatch.setenv("XP_DATA", env["XP_DATA"])
        plans = Path(env["XP_DATA"]) / "plans"
        plans.mkdir(parents=True)
        (plans / "story-042.md").write_text("legacy round one")
        (plans / "story-042.round-3.md").write_text("round three")
        junk = ("round-0", "round-04", "round-x", "round-²")  # ²: isdigit, but int() refuses it
        for name in (f"story-042.{tail}.md" for tail in junk):
            (plans / name).write_text("not a canonical positive round")
        assert not (plans / "story-042.round-1.md").exists()
        assert not (plans / "story-042.round-2.md").exists()
        assert review_findings_path("story-042", "plan") == plans / "story-042.round-4.md"

    def test_legacy_round_one_allocates_numbered_round_two(self, tmp_path, monkeypatch):
        _repo, env, _draft = self.repo(tmp_path)
        monkeypatch.setenv("XP_DATA", env["XP_DATA"])
        plans = Path(env["XP_DATA"]) / "plans"
        plans.mkdir(parents=True)
        (plans / "story-042.md").write_text("legacy round one")
        assert review_findings_path("story-042", "plan") == plans / "story-042.round-2.md"

    def test_success_without_the_required_findings_file_refuses(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        rec = stub_planner(tmp_path, write_findings=False)
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 2 and "no findings" in r.stderr.lower(), r.stderr
        assert CLEAN not in r.stdout
        assert rec.exists(), "the fault injection never reached the reviewer"


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
        assert "plan" not in json.loads(self.marker(tmp_path).read_text())

    def test_a_completed_review_leaves_none(self, tmp_path):
        repo, env, draft = self.repo(tmp_path)
        stub_planner(tmp_path)
        r = plan_review(repo, env, "story-042", str(draft))
        assert r.returncode == 0, r.stderr
        assert not self.marker(tmp_path).exists(), "a clean review must not accuse itself"

    def test_an_unbound_marker_is_not_joined_as_a_running_round(self, tmp_path, monkeypatch):
        import slate_review as runner

        monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
        marker = self.marker(tmp_path)
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"pid": 1234}))
        probed = []
        monkeypatch.setattr(runner.os, "kill", lambda *args: probed.append(args))
        assert runner._running("story-042", "plan") is None
        assert not probed

    def test_a_review_killed_from_outside_still_leaves_it(self, tmp_path):
        """The arm the whole design is for: SIGKILL, so nothing runs on the way out.
        The marker must already be on disk before the reviewer is launched."""
        repo, env, draft = self.repo(tmp_path)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "claude").write_text(CLAUDE_SH + "cat >/dev/null\nkill -9 $PPID\n")
        (bin_dir / "claude").chmod(0o755)
        proc = plan_review(repo, env, "story-042", str(draft))
        assert proc.returncode != 0
        assert self.marker(tmp_path).exists(), "a killed review left no trace at all"
