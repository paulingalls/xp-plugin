"""Sprint-close note triage emission."""

import subprocess
import sys

from sprint_helpers import PLUGIN, make_repo, sprint


class TestTriageEmissionShrinks:
    """cmd_start listed every `## note ` block ever filed — no window, no filter —
    so a note re-emitted at every close forever. 75 at sprint-003, 53 predating
    the sprint. The verb is inert without this: archiving 75 records changes
    nothing a human sees until start stops naming them."""

    def test_an_archived_note_leaves_the_triage_emission(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        work = lambda *a: subprocess.run(  # noqa: E731
            [sys.executable, str(PLUGIN / "scripts" / "work.py"), *a],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        work("note", "KEEP-ME-SENTINEL")
        work("note", "ARCHIVE-ME-SENTINEL")
        ref = work("list").stdout.strip().splitlines()[-1].split()[0]
        before = sprint(repo, env, "start").stdout
        assert "ARCHIVE-ME-SENTINEL" in before and "KEEP-ME-SENTINEL" in before
        assert work("archive", "--ref", ref, "--disposition", "dropped").returncode == 0
        after = sprint(repo, env, "start").stdout
        assert "ARCHIVE-ME-SENTINEL" not in after, "archived note still queued for triage"
        assert "KEEP-ME-SENTINEL" in after, "filtered an unarchived note too"


def test_settled_history_stays_readable_without_new_adjudication(tmp_path):
    import json

    from sprint_helpers import marker_path, work

    repo, env, _g = make_repo(tmp_path)
    marker = marker_path(tmp_path)
    marker.parent.mkdir(parents=True)
    old = {"blocking": [], "noted": ["settled legacy finding"]}
    marker.write_text(json.dumps({"rounds": [old]}))
    report = tmp_path / "judgment.json"
    report.write_text(json.dumps({"blocking": [], "fixed": ["settled legacy finding"]}))
    judged = work(repo, env, "judge", "--source", str(marker), "--report", str(report))
    assert judged.returncode == 0, judged.stderr
    history = tmp_path / "data" / "work.md"
    preserved = history.read_bytes()
    marker.write_text(json.dumps({"rounds": [old, {"blocking": [], "fixed": []}]}))

    result = sprint(repo, env, "start")

    assert result.returncode == 0, result.stderr
    assert "Unresolved finding" not in result.stdout
    assert history.read_bytes() == preserved
    assert json.loads(marker.read_text())["rounds"][0] == old


def test_later_same_text_finding_is_a_new_obligation(tmp_path):
    import json

    from sprint_helpers import marker_path, work

    repo, env, _g = make_repo(tmp_path)
    marker = marker_path(tmp_path)
    marker.parent.mkdir(parents=True)
    old = {"blocking": [], "noted": ["recurring finding"]}
    marker.write_text(json.dumps({"rounds": [old]}))
    report = tmp_path / "judgment.json"
    report.write_text(json.dumps({"blocking": [], "fixed": ["recurring finding"]}))
    assert (
        work(repo, env, "judge", "--source", str(marker), "--report", str(report)).returncode == 0
    )
    marker.write_text(json.dumps({"rounds": [old, old]}))

    result = sprint(repo, env, "start")

    assert result.returncode == 0, result.stderr
    assert "Unresolved finding" in result.stdout and "recurring finding" in result.stdout


def test_missing_active_marker_cannot_hide_durable_blocker(tmp_path):
    import json

    from sprint_helpers import marker_path

    repo, env, _g = make_repo(tmp_path)
    marker = marker_path(tmp_path)
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"rounds": [{"blocking": ["durable blocker"]}]}))
    (tmp_path / "data/closes.jsonl").write_text(marker.read_text() + "\n")
    marker.unlink()
    result = sprint(repo, env, "start")
    assert result.returncode == 0, result.stderr
    assert "Unresolved finding" in result.stdout and "durable blocker" in result.stdout


def test_corrupt_close_evidence_refuses_before_readers(tmp_path):
    from sprint_helpers import launches, staged_stub

    repo, env, _g = make_repo(tmp_path)
    (tmp_path / "data/closes.jsonl").write_text("{corrupt\n")
    staged_stub(tmp_path)
    result = sprint(repo, env, "review")
    assert result.returncode == 2 and "Unreadable close history" in result.stderr
    assert launches(tmp_path) == []
