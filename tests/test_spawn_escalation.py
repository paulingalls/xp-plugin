"""A teammate that STOPS deliberately hands back an escalation, not a failure.

Verify: pytest -q -n auto tests/test_spawn_escalation.py

TEAMMATE.md tells a blocked teammate to say so, file a note, and stop. spawn then
refused that exact handback — "the teammate made no commits of its own" — and
stranded the worktree. Field-measured (Legacy): four runs, ~$38, three with zero
commits, two of them correct escalations; one carried a plan three review rounds
deep and was reported as having done nothing.

The record filed during the run is what separates the two, because it is what
TEAMMATE.md already tells the teammate to leave. Forging it is not a hole: a
teammate that files a note and stops has claimed exactly what stopping claims.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from spawn_helpers import SPAWN, make_repo, spawn

WORK = SPAWN.parent / "work.py"

ESCALATION = "the card's AC3 cannot be built: the API it names returns no such field"


def stub_escalating(
    tmp_path,
    commit=False,
    write_file=False,
    note=True,
    crash=False,
    wait_for=None,
    artifacts=False,
    note_text=ESCALATION,
):
    """A teammate that files a work.md note and stops, with the other two knobs
    the guards turn on: whether it committed, and whether it left files behind."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launch.json"
    body = [
        "#!/usr/bin/env python3",
        "import json, os, subprocess, sys, time",
        "stdin = sys.stdin.read()",
        f"json.dump({{'env': dict(os.environ), 'stdin': stdin}}, open({str(rec)!r}, 'w'))",
        f"if {write_file!r} or {commit!r}:",
        "    open('half-done.py', 'w').write('# WIP\\n')",
        f"if {artifacts!r}:",
        "    plans = os.path.join(os.environ['XP_DATA'], 'plans')",
        "    os.makedirs(plans, exist_ok=True)",
        "    open(os.path.join(plans, 'story-042.plan.md'), 'w').write('DRAFT-SENTINEL\\n')",
        "    open(os.path.join(plans, 'story-042.md'), 'w').write('FINDING-ONE\\n')",
        "    open(os.path.join(plans, 'story-042.round-2.md'), 'w').write('FINDING-TWO\\n')",
        f"if {commit!r}:",
        "    subprocess.run(['git', 'add', '-A'], check=True)",
        "    subprocess.run(['git', 'commit', '-qm', 'real work'], check=True)",
        f"if {note!r}:",
        # THIS interpreter, not the stub's: `python3` on a stock mac is 3.9, where
        # every shipped script still tracebacks (note 1e7b1197). The stub must
        # exercise the escalation seam, not that.
        f"    subprocess.run([{sys.executable!r}, {str(WORK)!r},",
        f"                    'note', {note_text!r}], check=True)",
        f"while {str(wait_for) if wait_for else ''!r} and not os.path.exists("
        f"{str(wait_for) if wait_for else ''!r}):",
        "    time.sleep(0.01)",
        f"if {crash!r}:",
        "    sys.exit(9)",
        "print(json.dumps({'type': 'result', 'subtype': 'success', 'result': 'stopped'}))",
    ]
    (bin_dir / "claude").write_text("\n".join(body) + "\n")
    (bin_dir / "claude").chmod(0o755)
    return rec


def file_note(repo, env, text):
    return subprocess.run(
        [sys.executable, str(WORK), "note", text],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def records(env):
    out = subprocess.run(
        [sys.executable, str(WORK), "list"], env=env, capture_output=True, text=True
    )
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


class TestDeliberateStop:
    def test_a_dead_teammate_with_a_clean_commit_is_not_reported_as_finished(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_escalating(tmp_path, commit=True, note=False, crash=True)
        result = spawn(repo, env, "story-042")
        assert result.returncode == 3 and "DIED" in result.stderr, result.stderr
        assert "produced commit" not in result.stdout
        assert (tmp_path / "data" / "plans" / "story-042.handoff.json").exists()

    def test_a_teammate_that_filed_a_record_and_stopped_is_an_escalation(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_escalating(tmp_path)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 3, f"rc={r.returncode}\n{r.stderr}"
        assert "escalat" in r.stderr.lower(), r.stderr
        assert "story-042" in r.stderr and "worktrees/story-042" in r.stderr, r.stderr
        assert records(env), "the escalation record itself is missing"

    def test_the_escalation_names_the_record_the_lead_must_read(self, tmp_path):
        """Naming the tree is not enough: the lead's next action is reading WHY,
        and the id is what `work.py list` is searched by."""
        repo, env, _g = make_repo(tmp_path)
        stub_escalating(tmp_path)
        r = spawn(repo, env, "story-042")
        filed = records(env)[-1].split()[0]
        assert filed in r.stderr, f"record {filed} not named:\n{r.stderr}"

    def test_uncommitted_work_does_not_hide_the_escalation(self, tmp_path):
        """The dirty-tree guard fires BEFORE the no-commits one, so a teammate that
        stopped mid-edit hits a different refusal than the one reported from the
        field. Both must resolve to the same escalation."""
        repo, env, _g = make_repo(tmp_path)
        stub_escalating(tmp_path, write_file=True)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 3, f"rc={r.returncode}\n{r.stderr}"
        assert "escalat" in r.stderr.lower(), r.stderr
        assert "half-done.py" in r.stderr, "the work left behind is not named"

    def test_a_run_that_died_after_filing_is_not_called_a_deliberate_stop(self, tmp_path):
        """The record separates a stop from a non-finish; the harness's own exit
        status separates a stop from a DEATH, and it costs nothing to read. A
        teammate that filed a discovery note at turn 3 and died at turn 50 chose
        nothing, and a lead told it escalated goes looking for a wrong card."""
        repo, env, _g = make_repo(tmp_path)
        stub_escalating(tmp_path, crash=True)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 3, f"rc={r.returncode}\n{r.stderr}"
        assert "escalated by the teammate" not in r.stderr.lower(), r.stderr
        assert "rc 9" in r.stderr, r.stderr
        assert records(env)[-1].split()[0] in r.stderr, r.stderr
        # naming records without naming what to do with them is half a refusal
        assert "work.py list" in r.stderr, r.stderr

    def test_a_death_that_filed_nothing_is_still_reported_as_a_death(self, tmp_path):
        """rc discriminates before any record does. The seam reads the two halves
        independently, so the half with no record must not fall through to the
        plain no-commits refusal and lose the fact that the harness died."""
        repo, env, _g = make_repo(tmp_path)
        stub_escalating(tmp_path, note=False, crash=True)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 3, f"rc={r.returncode}\n{r.stderr}"
        assert "died" in r.stderr.lower() and "escalat" not in r.stderr.lower(), r.stderr

    def test_records_accumulate_across_successive_stops(self, tmp_path):
        """A record filed at stop 1 is in `before` at stop 2 and can never be
        `during` again, so a marker that overwrites hands stop 3 only stop 2's
        words. story-028 stopped five times; the draft and the findings survive
        all five because they are files, and the records must not be the one
        artifact that does not."""
        repo, env, g = make_repo(tmp_path)
        later = "still blocked: the field the card names is still absent"
        for text in (ESCALATION, later):
            stub_escalating(tmp_path, note_text=text)
            assert spawn(repo, env, "story-042").returncode == 3
            tree = Path(env["XP_DATA"]) / "worktrees" / "story-042"
            assert g("worktree", "remove", "--force", str(tree)).returncode == 0
            g("branch", "-D", "ada/story-042-demo-story")
            plan = Path(env["XP_DATA"]) / "plan.md"
            plan.write_text(plan.read_text().replace("[in-progress]", "[ready]"))
        inherited = spawn(repo, env, "story-042", "--dry-run").stdout
        assert ESCALATION in inherited and later in inherited, inherited

    def test_no_record_is_still_refused(self, tmp_path):
        """The guard is not weakened: a teammate that simply did not finish, and
        said nothing, is refused exactly as before."""
        repo, env, _g = make_repo(tmp_path)
        stub_escalating(tmp_path, note=False)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2, f"rc={r.returncode}\n{r.stderr}"
        assert "no commits" in r.stderr.lower(), r.stderr
        assert "escalat" not in r.stderr.lower(), r.stderr

    def test_a_record_filed_before_the_run_is_not_this_runs_escalation(self, tmp_path):
        """The snapshot is the whole seam. Every real repo's work.md already holds
        records, so a spawn that read the FILE rather than the delta would report
        every crashed teammate as an escalation and send the lead to read a note
        from another story."""
        repo, env, _g = make_repo(tmp_path)
        stub_escalating(tmp_path, note=False)
        file_note(repo, env, "a decision filed by an earlier story, long before this run")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2, f"rc={r.returncode}\n{r.stderr}"
        assert "no commits" in r.stderr.lower(), r.stderr
        assert "escalat" not in r.stderr.lower(), r.stderr

    def test_a_concurrent_lead_record_does_not_turn_a_yield_into_an_escalation(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        release = tmp_path / "release"
        rec = stub_escalating(tmp_path, note=False, wait_for=release)
        proc = subprocess.Popen(
            [sys.executable, str(SPAWN), "story-042"],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(1000):
            if rec.exists():
                break
            time.sleep(0.01)
        else:
            proc.kill()
            raise AssertionError("the teammate never launched")
        file_note(repo, env, "the lead filed this while the teammate ran\nStory: story-042")
        release.touch()
        _stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 2, stderr
        assert "escalat" not in stderr.lower(), stderr

    def test_an_escalation_names_only_the_teammates_record(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        release = tmp_path / "release"
        rec = stub_escalating(tmp_path, wait_for=release)
        proc = subprocess.Popen(
            [sys.executable, str(SPAWN), "story-042"],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(1000):
            if rec.exists() and len(records(env)) == 1:
                break
            time.sleep(0.01)
        else:
            proc.kill()
            raise AssertionError("the teammate never filed its escalation")
        lead = file_note(repo, env, "the lead filed this during the teammate's stop")
        teammate = next(line.split()[0] for line in records(env) if not line.startswith(lead))
        release.touch()
        _stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 3 and "escalated by the teammate" in stderr.lower()
        assert teammate in stderr and lead not in stderr, stderr

    def test_a_finished_story_is_never_an_escalation(self, tmp_path):
        """A record filed during a SUCCESSFUL run is a discovery, not a stop —
        the record only turns a refusal into an escalation, it never makes one."""
        repo, env, _g = make_repo(tmp_path)
        stub_escalating(tmp_path, commit=True, note=True)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, f"rc={r.returncode}\n{r.stderr}"
        assert "escalat" not in r.stderr.lower(), r.stderr
        assert json.loads((tmp_path / "launch.json").read_text())["env"]["XP_ROLE"] == "teammate"
        assert Path(env["XP_DATA"], "worktrees", "story-042").exists()


class TestAnUnreadableHandoffMarkerIsNotAFirstSpawn:
    """Constraint 15 at the one site where conflating the two is SILENT: `{}` meant
    "first spawn ever", so a truncated or unreadable marker discarded the draft,
    its plan-review findings and the escalation record — all readable on disk
    right beside it — and the successor re-derived the plan its predecessor was
    stopped for, which is the entire cost story-041 exists to remove."""

    def artifacts(self, tmp_path, marker_text):
        import spawn  # noqa: F401  — seeds scripts/spawn on sys.path
        from handoff import draft_path, marker_path

        root = tmp_path / "data"
        (root / "plans").mkdir(parents=True)
        draft_path(root, "story-042").write_text("DRAFT-SENTINEL\n")
        (root / "plans" / "story-042.md").write_text("FINDING-ONE\n")
        marker_path(root, "story-042").write_text(marker_text)
        return root

    def test_a_truncated_marker_still_hands_over_what_survived(self, tmp_path):
        import spawn  # noqa: F401

        # exactly what a stop interrupted mid-write leaves: a valid JSON PREFIX
        root = self.artifacts(tmp_path, '{"why": "no commits", "record')
        from handoff import inheritance

        handed = inheritance(root, "story-042")
        assert "DRAFT-SENTINEL" in handed and "FINDING-ONE" in handed, handed
        assert "unreadable" in handed, "the successor is not told why the why is missing"

    def test_a_marker_that_never_EXISTED_still_hands_over_nothing(self, tmp_path):
        """The other arm, or the fix above turns every FIRST spawn into an
        inheriting one and every card pays for a section saying nothing."""
        import spawn  # noqa: F401
        from handoff import draft_path, inheritance

        root = tmp_path / "data"
        (root / "plans").mkdir(parents=True)
        draft_path(root, "story-042").write_text("DRAFT-SENTINEL\n")
        assert inheritance(root, "story-042") == ""

    def test_a_write_that_dies_mid_flight_leaves_THE_LAST_marker_intact(self, tmp_path):
        """The PRODUCER half — the reader above tolerates a torn marker, and this
        is what stops one being made. Fault-injected by failing the write after it
        has emitted bytes: written in place that leaves the truncated prefix, and
        stop 1's records are gone; written beside and moved, stop 1 survives."""
        import spawn  # noqa: F401
        from handoff import marker_path, record_handoff

        root = tmp_path / "data"
        record_handoff(root, "story-042", set(), "stop one", 0)
        whole = Path.write_text

        def torn(self, text, *args, **kwargs):
            whole(self, text[: len(text) // 2], *args, **kwargs)
            raise OSError("no space left on device")

        Path.write_text = torn
        try:
            with pytest.raises(OSError):
                record_handoff(root, "story-042", set(), "stop two", 0)
        finally:
            Path.write_text = whole
        assert json.loads(marker_path(root, "story-042").read_text())["why"] == "stop one"
