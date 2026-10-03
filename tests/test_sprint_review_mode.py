"""Later explicit review judges changed integration without committing."""

import json
from pathlib import Path

import pytest
from sprint_helpers import bundles, head, launches, make_repo, marker_path, sprint, staged_stub


@pytest.mark.parametrize("producer", ["fix", "close"])
def test_later_interruption_corrects_only_the_producer_report(tmp_path, producer):
    repo, env, g = make_repo(tmp_path)
    staged_stub(tmp_path)
    assert sprint(repo, env, "review").returncode == 0
    (repo / "src.py").write_text("A = 2\n")
    assert g("commit", "-qam", "lead integration correction").returncode == 0
    staged_stub(
        tmp_path,
        solution={
            "schema": 2,
            "fixed": [],
            "dropped": [],
            "debt": [],
            "blocking": [],
            "actionable": ["integration defect"],
        },
        fix={
            "schema": 2,
            "fixed": ["integration defect"],
            "blocking": [],
            "dropped": [],
            "debt": [],
        },
        patches=[("fix", "src.py", "B = 3")],
    )
    child = tmp_path / "bin/claude"
    write = "open(m.group(1).strip(), 'w').write(json.dumps(report))"
    child.write_text(child.read_text().replace(write, f"None if key == {producer!r} else {write}"))
    stopped = sprint(repo, env, "review")
    assert stopped.returncode == 2, stopped.stdout + stopped.stderr
    if producer == "fix":
        stopped_round = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert "integration defect" in stopped_round["blocking"]
    corrected = head(repo, env)
    prior = len(launches(tmp_path))
    staged_stub(tmp_path)

    resumed = sprint(repo, env, "review")

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    from sprint_helpers import stage_key

    assert [stage_key(item["stdin"]) for item in launches(tmp_path)[prior:]] == (
        ["fix", "close"] if producer == "fix" else ["close"]
    )
    assert "Do not edit or commit again" in launches(tmp_path)[prior]["stdin"]
    closer = launches(tmp_path)[-1]["stdin"]
    recorded_start = state_start = json.loads(marker_path(tmp_path).read_text())["rounds"][-1][
        "reviewed_head"
    ]
    assert f"{recorded_start}..{corrected}" in closer
    assert g("diff", f"{state_start}..{corrected}").stdout
    assert head(repo, env) == corrected
    state = json.loads(marker_path(tmp_path).read_text())
    assert len(state["rounds"]) == 2
    assert "incomplete" not in state["rounds"][-1]
    assert Path(env["XP_DATA"], "reports/sprint/2.fix.round-2.diff").is_file()


def test_lead_corrected_delta_requires_explicit_integration_judgment(tmp_path):
    repo, env, g = make_repo(tmp_path)
    first = head(repo, env)
    marker = marker_path(tmp_path)
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "rounds": [
                    {
                        "blocking": ["current integration blocker"],
                        "fixed": ["settled fix"],
                        "dropped": [{"finding": "settled drop", "reason": "refuted"}],
                        "shown_sha": first,
                    }
                ],
                "shown_sha": first,
            }
        )
    )
    unchanged = sprint(repo, env, "review")
    assert unchanged.returncode == 2 and launches(tmp_path) == []
    (repo / "src.py").write_text("A = 2\n")
    assert g("commit", "-qam", "lead correction").returncode == 0
    corrected = head(repo, env)
    assert sprint(repo, env, "land", "--dry-run").returncode == 2
    assert launches(tmp_path) == []
    staged_stub(tmp_path)

    result = sprint(repo, env, "review")

    assert result.returncode == 0, result.stderr
    assert len(launches(tmp_path)) == 1
    assert len(bundles(tmp_path, "solution")) == 1
    assert head(repo, env) == corrected
    bundle = bundles(tmp_path, "solution")[0]
    assert "current integration blocker" in bundle
    assert "settled fix" not in bundle and "settled drop" not in bundle
    assert "The delta since the last recorded round" in bundle


@pytest.mark.parametrize("role", ["fixer", "closer"])
def test_later_review_validates_all_roles_before_launch(tmp_path, role):
    repo, env, g = make_repo(tmp_path)
    staged_stub(tmp_path)
    assert sprint(repo, env, "review").returncode == 0
    config = repo / ".xp/config.yml"
    config.write_text(
        config.read_text().replace(
            "reviewer: claude/opus", f"reviewer: claude/opus\n  {role}: invalid/model"
        )
    )
    assert g("commit", "-qam", "lead changes role configuration").returncode == 0
    before, count = head(repo, env), len(launches(tmp_path))
    prior = marker_path(tmp_path).read_bytes()
    staged_stub(
        tmp_path,
        solution={"actionable": ["missing C"], "blocking": []},
        fix={"fixed": ["missing C"], "blocking": []},
        patches=[("fix", "src.py", "C = 3")],
    )

    result = sprint(repo, env, "review")

    assert result.returncode == 2, result.stdout + result.stderr
    assert len(launches(tmp_path)) == count, "bad downstream role refused only after work ran"
    assert head(repo, env) == before
    assert marker_path(tmp_path).read_bytes() == prior
