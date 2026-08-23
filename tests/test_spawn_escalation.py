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
from pathlib import Path

from spawn_helpers import SPAWN, make_repo, spawn

WORK = SPAWN.parent / "work.py"

ESCALATION = "the card's AC3 cannot be built: the API it names returns no such field"


def stub_escalating(tmp_path, commit=False, write_file=False, note=True):
    """A teammate that files a work.md note and stops, with the other two knobs
    the guards turn on: whether it committed, and whether it left files behind."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launch.json"
    body = [
        "#!/usr/bin/env python3",
        "import json, os, subprocess, sys",
        "stdin = sys.stdin.read()",
        f"json.dump({{'env': dict(os.environ)}}, open({str(rec)!r}, 'w'))",
        f"if {write_file!r} or {commit!r}:",
        "    open('half-done.py', 'w').write('# WIP\\n')",
        f"if {commit!r}:",
        "    subprocess.run(['git', 'add', '-A'], check=True)",
        "    subprocess.run(['git', 'commit', '-qm', 'real work'], check=True)",
        f"if {note!r}:",
        # THIS interpreter, not the stub's: `python3` on a stock mac is 3.9, where
        # every shipped script still tracebacks (note 1e7b1197). The stub must
        # exercise the escalation seam, not that.
        f"    subprocess.run([{sys.executable!r}, {str(WORK)!r},",
        f"                    'note', {ESCALATION!r}], check=True)",
        "print(json.dumps({'type': 'result', 'subtype': 'success', 'result': 'stopped'}))",
    ]
    (bin_dir / "claude").write_text("\n".join(body) + "\n")
    (bin_dir / "claude").chmod(0o755)
    return rec


def file_note(repo, env, text):
    subprocess.run(
        [sys.executable, str(WORK), "note", text],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )


def records(env):
    out = subprocess.run(
        [sys.executable, str(WORK), "list"], env=env, capture_output=True, text=True
    )
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


class TestDeliberateStop:
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
