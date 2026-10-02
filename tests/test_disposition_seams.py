"""Acceptance must preserve findings across parser, repair and release boundaries."""

import json

import pytest
from close_helpers import close, make_repo, marker, marker_file, stub_reviewer
from review_report import read_report
from test_close_repair import commit, red_round

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
def test_fresh_reports_refuse_duplicate_fields(tmp_path, raw, stage):
    path = tmp_path / "report.json"
    path.write_text(raw)
    parsed, error = read_report(path, stage)
    assert not parsed and "duplicate" in error


@pytest.mark.parametrize("raw", DUPLICATES)
def test_duplicate_report_cannot_record_or_land(tmp_path, raw):
    repo, env, g = make_repo(tmp_path)
    stub_reviewer(tmp_path, report=raw)
    before = g("rev-parse", "main").stdout
    result = close(repo, env, "review")
    assert result.returncode == 2 and "duplicate" in result.stderr
    assert not marker_file(tmp_path).exists()
    assert close(repo, env, "land").returncode == 2
    assert g("rev-parse", "main").stdout == before
    assert not (tmp_path / "data/closes.jsonl").exists()


@pytest.mark.parametrize("noted", [[], ["silent storage finding"]])
def test_legacy_review_time_repair_records_incomplete_and_refuses_land(tmp_path, noted):
    repo, env, g, launch = red_round(tmp_path)
    path = tmp_path / "data/reports/story-042.round-1.json"
    path.write_text(json.dumps({"fixed": [], "blocking": [], "noted": noted}))
    commit(g, repo, "src/thing.py", "A = 2\nbroken = True\n")
    before = g("rev-parse", "main").stdout
    repaired = close(repo, env, "repair")
    assert repaired.returncode == 2 and "legacy/untriaged" in repaired.stderr
    saved = marker(tmp_path)["rounds"][-1]
    assert saved["legacy_untriaged"] == noted and saved["incomplete"]
    assert not launch.exists()
    assert close(repo, env, "land").returncode == 2
    assert g("rev-parse", "main").stdout == before


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


def test_completed_legacy_round_still_allows_land_red_repair(tmp_path):
    repo, env, g = make_repo(tmp_path, files="src/thing.py, .xp/config.yml")
    config = repo / ".xp/config.yml"
    config.write_text(
        "roles:\n  reviewer: claude/opus\ntests:\n  story: grep -q fixed src/thing.py\n"
    )
    g("add", ".xp/config.yml")
    assert g("commit", "-qm", "configure tier").returncode == 0
    head = g("rev-parse", "HEAD").stdout.strip()
    base = g("merge-base", "main", "HEAD").stdout.strip()
    old = {"fixed": [], "blocking": [], "noted": ["historical finding"]}
    round_ = old | {"reviewed_head": head, "shown_sha": head, "review_base": base}
    marker_file(tmp_path).write_text(json.dumps({"rounds": [round_], **round_}))
    path = tmp_path / "data/reports/story-042.round-1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(old))
    red = close(repo, env, "land")
    assert red.returncode == 2 and "test tier red" in red.stderr
    commit(g, repo, "src/thing.py", "A = 2\nfixed = True\n")
    repaired = close(repo, env, "repair")
    assert repaired.returncode == 0, repaired.stderr
    assert not marker(tmp_path)["rounds"][-1].get("incomplete")
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert "historical finding" in landed.stdout
