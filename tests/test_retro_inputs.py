import json

import pytest
import xp
from test_land import git
from test_retro import result
from test_retro_filing import state
from xpcore import retro

pytest_plugins = ["test_retro_filing"]


def test_live_issue_snapshot(publishing):
    root, _, _, store, home = publishing
    issues = [
        {
            "number": n,
            "labels": [{"name": ("bug", "debt", "lesson")[n % 3]}],
            "title": f"Evidence-{n:03}",
            "state": "CLOSED",
            "stateReason": "COMPLETED" if n % 2 else "NOT_PLANNED",
            "closedAt": f"2026-11-{1 + n // 24:02}T{n % 24:02}:00:00Z",
        }
        for n in range(1, 54)
    ]
    # Creation order differs from closure order; the last page has an open issue.
    issues = issues[::2] + issues[1::2]
    issues += [
        {
            "number": 100,
            "labels": [{"name": "bug"}, {"name": "lesson"}],
            "title": "Still open",
            "state": "OPEN",
            "stateReason": None,
            "closedAt": None,
        }
    ]
    issues.append(
        {
            "number": 101,
            "title": "Unrelated chore",
            "labels": [{"name": "chore"}],
            "state": "OPEN",
            "stateReason": None,
            "closedAt": None,
        }
    )
    s = state(publishing)
    s["pages"] = [
        {"data": {"repository": {"issues": {"nodes": nodes}}}}
        for nodes in (issues[:30], issues[30:])
    ]
    store.write_text(json.dumps(s))
    assert xp.main(["retro", "1"]) == 0
    prompt = (home / "retro-prompt").read_text()
    assert prompt.count("#100 Still open") == 1
    assert "Unrelated chore" not in prompt
    for n in range(4, 54):
        assert prompt.count(f"#{n} Evidence-{n:03}") == 1
    for n in (1, 2, 3):
        assert f"Evidence-{n:03}" not in prompt
    assert "CLOSED" in prompt and "COMPLETED" in prompt and "NOT_PLANNED" in prompt
    calls = [args for args, _ in state(publishing)["calls"]]
    assert [
        "repo",
        "view",
        git(root, "remote", "get-url", "origin"),
        "--json",
        "nameWithOwner",
    ] in calls
    query = next(c for c in calls if c[:2] == ["api", "graphql"])
    assert "--paginate" in query and "--slurp" in query
    rendered = " ".join(query)
    for field in (
        "repository(",
        "$endCursor",
        "after:",
        "stateReason",
        "closedAt",
        "hasNextPage",
        "endCursor",
        'labels:["bug","debt","lesson"]',
        "owner=owner",
        "name=project",
    ):
        assert field in rendered
    assert "search(" not in rendered


def test_snapshot_failure_stops_seat(publishing, monkeypatch, capsys):
    _, _, folder, _, home = publishing
    monkeypatch.setenv("GH_FAIL", "1")
    assert xp.main(["retro", "1"]) == 1
    assert "issue snapshot lookup failed" in capsys.readouterr().err
    assert not (home / "retro-prompt").exists()
    assert not (folder / "retro.md").exists()
    assert not retro.ledger_path().exists()


@pytest.mark.parametrize("setting", ["off", ""])
def test_local_mode_has_no_github_calls(publishing, monkeypatch, setting):
    root, _, _, _, _ = publishing
    config = root / ".xp/config.yml"
    config.write_text(
        config.read_text().replace("github_issues: on", "github_issues: off" if setting else "")
    )
    result(monkeypatch)
    assert xp.main(["retro", "1"]) == 0
    assert "[proposed] A lesson" in retro.ledger_path().read_text()
    assert "; #" not in retro.ledger_path().read_text()
    monkeypatch.setenv("RETRO_RESULT", '{"sightings":[],"proposals":[]}')
    assert xp.main(["retro", "1"]) == 0
    assert not retro.ledger_path().read_text()
    assert not state(publishing)["calls"]
