import json
from pathlib import Path

from close_helpers import launches
from sprint_helpers import head, make_repo, marker_path, sprint, stage_key, staged_stub


def test_an_incomplete_round_after_fixer_resumes_at_closer(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    reviewed = head(repo, env)
    finding = {"fixed": [], "blocking": ["F"], "noted": []}
    staged_stub(
        tmp_path,
        patches=[("fix", "src.py", "C = 2")],
        find=finding,
        verify=finding,
        fix={"fixed": ["F"], "blocking": [], "noted": []},
    )
    claude = tmp_path / "bin/claude"
    text = claude.read_text()
    write = "open(m.group(1).strip(), 'w').write(json.dumps(report))"
    claude.write_text(text.replace(write, f"None if key == 'close' else {write}"))
    claude.chmod(0o755)

    first = sprint(repo, env, "review")
    assert first.returncode == 2 and "wrote no report" in first.stderr
    state = json.loads(marker_path(tmp_path).read_text())
    assert state["rounds"][-1]["stages"][-1] == "fix"
    assert state["rounds"][-1]["reviewed_head"] == reviewed
    assert head(repo, env) != reviewed
    prior_launches = len(launches(tmp_path))

    # Sprint 19 produced its incomplete marker before resume provenance shipped.
    state["rounds"][-1].pop("reviewed_head")
    state["rounds"][-1].pop("shown_sha")
    state.pop("reviewed_head")
    state.pop("shown_sha")
    marker_path(tmp_path).write_text(json.dumps(state))

    staged_stub(tmp_path)
    resumed = sprint(repo, env, "review")
    assert resumed.returncode == 0, resumed.stderr
    resumed_stages = [stage_key(item["stdin"]) for item in launches(tmp_path)[prior_launches:]]
    assert resumed_stages == ["close"]
    state = json.loads(marker_path(tmp_path).read_text())
    assert len(state["rounds"]) == 1
    assert "incomplete" not in state["rounds"][0]
    assert state["rounds"][0]["reviewed_head"] == reviewed
    assert state["rounds"][0]["shown_sha"] == head(repo, env)
    handoff = Path(env["XP_DATA"]) / "reports/sprint/2.fix.round-1.diff"
    assert handoff.is_file()
