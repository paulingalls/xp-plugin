"""Acceptance must preserve findings across parser, repair and release boundaries."""

import json

import pytest
from close_helpers import close, make_repo, marker_file, stub_reviewer
from review_report import read_report

DUPLICATES = [
    '{"schema":2,"fixed":[],"blocking":["unmet AC: silent record loss"],'
    '"blocking":[],"dropped":[],"debt":[]}',
    '{"schema":2,"fixed":[],"blocking":[],"dropped":'
    '[{"finding":"loss","reason":"","reason":"loud"}],"debt":[]}',
    '{"schema":2,"fixed":[],"blocking":[],"dropped":'
    '[{"finding":"loss","reason":""}],"dropped":[],"debt":[]}',
]


@pytest.mark.parametrize("raw", DUPLICATES)
@pytest.mark.parametrize("stage", ["", "find-security", "fix", "closer"])
@pytest.mark.parametrize("fresh", [True, False])
def test_reports_refuse_duplicate_fields(tmp_path, raw, stage, fresh):
    path = tmp_path / "report.json"
    path.write_text(raw)
    parsed, error = read_report(path, stage, fresh=fresh)
    assert not parsed and "duplicate" in error


@pytest.mark.parametrize("raw", DUPLICATES)
@pytest.mark.parametrize("why", ["refused: ambiguous evidence", ""])
def test_stamping_does_not_destroy_duplicate_evidence(tmp_path, raw, why):
    import review

    path = tmp_path / "report.json"
    path.write_text(raw)
    before = path.read_bytes()
    assert review.stamp(path, why) == why
    assert path.read_bytes() == before


@pytest.mark.parametrize("raw", DUPLICATES)
def test_duplicate_report_cannot_record_or_land(tmp_path, raw):
    repo, env, g = make_repo(tmp_path)
    stub_reviewer(tmp_path, report=raw)
    before = g("rev-parse", "main").stdout
    result = close(repo, env, "review")
    assert result.returncode == 2 and "duplicate" in result.stderr
    path = tmp_path / "data/reports/story-042.round-1.json"
    assert path.read_text() == raw
    rescued = close(repo, env, "review")
    assert rescued.returncode == 2 and "duplicate" in rescued.stderr
    assert path.read_text() == raw
    assert not marker_file(tmp_path).exists()
    assert close(repo, env, "land").returncode == 2
    assert g("rev-parse", "main").stdout == before
    assert not (tmp_path / "data/closes.jsonl").exists()


@pytest.mark.parametrize("raw", DUPLICATES[:2])
def test_duplicate_stage_report_cannot_certify_sprint(tmp_path, raw):
    from sprint_helpers import make_repo as sprint_repo
    from sprint_helpers import marker_path, sprint, staged_stub

    repo, env, g = sprint_repo(tmp_path)
    staged_stub(tmp_path)
    binary = tmp_path / "bin/claude"
    body = binary.read_text().replace("json.dumps(report)", repr(raw))
    binary.write_text(body)
    before = g("rev-parse", "main").stdout
    result = sprint(repo, env, "review")
    assert result.returncode == 2 and "duplicate" in result.stderr
    assert not marker_path(tmp_path).exists()
    assert sprint(repo, env, "land").returncode == 2
    assert g("rev-parse", "main").stdout == before


@pytest.mark.parametrize("bucket", ["dropped", "debt"])
def test_unexplained_disposition_cannot_certify_review(tmp_path, bucket):
    repo, env, _git = make_repo(tmp_path)
    stub_reviewer(tmp_path, report={"actionable": [], "blocking": [], bucket: ["silent loss"]})
    result = close(repo, env, "review")
    assert result.returncode == 2 and bucket in result.stderr
    assert not marker_file(tmp_path).exists()
    path = tmp_path / "data/reports/story-042.round-1.json"
    assert read_report(path, stage="solution")[1]


def test_sprint_delta_cannot_drop_unresolved_actionable_findings(tmp_path):
    from sprint_helpers import make_repo as sprint_repo
    from sprint_helpers import marker_path, record_reviews, sprint, staged_stub

    repo, env, git = sprint_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    (repo / "src.py").write_text("A = 2\n")
    assert git("commit", "-qam", "lead delta").returncode == 0
    staged_stub(
        tmp_path,
        solution={"actionable": ["silent loss"], "blocking": []},
        fix={"actionable": ["unmet AC: silent loss"], "blocking": []},
    )
    result = sprint(repo, env, "review")
    assert result.returncode == 2 and "actionable" in result.stderr
    assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["incomplete"]


def test_minimal_judgment_remains_effective_in_triage(tmp_path):
    from sprint_helpers import make_repo as sprint_repo
    from sprint_helpers import sprint
    from work_helpers import run

    repo, env, _git = sprint_repo(tmp_path)
    root = tmp_path / "data"
    (root / "closes.jsonl").write_text(
        json.dumps({"rounds": [{"blocking": [], "noted": ["old loss"]}]}) + "\n"
    )
    path = tmp_path / "judgment.json"
    path.write_text(json.dumps({"blocking": [], "fixed": ["old loss"]}))
    result = run(["judge", "--source", "closes.jsonl:1", "--report", str(path)], root)
    assert result.returncode == 0, result.stderr
    started = sprint(repo, env, "start")
    assert started.returncode == 0, started.stderr
    shown = started.stdout
    assert "Unreadable judgment" not in shown
    assert "Unresolved finding" not in shown


def test_sprint_delta_fixer_cannot_rename_undeclared_project_authority(tmp_path):
    from sprint_helpers import make_repo as sprint_repo
    from sprint_helpers import record_reviews, sprint, staged_stub

    repo, env, _git = sprint_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    staged_stub(tmp_path, solution={"actionable": ["fix F"], "blocking": []})
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "sys.stdout.write(",
            "if key == 'fix': subprocess.run(['git','mv','.xp/system.md','system.md'],check=True)\n"
            "if key == 'fix': "
            "subprocess.run(['git','commit','-qm','move project authority'],check=True)\n"
            "sys.stdout.write(",
        )
    )
    result = sprint(repo, env, "review")
    assert result.returncode == 2 and "undeclared .xp path" in result.stderr
    assert (repo / "system.md").exists()
