import json
from pathlib import Path

from close_helpers import launches
from sprint_helpers import head, make_repo, marker_path, sprint, stage_key, staged_stub


def _stop_at_closer(tmp_path, target="src.py"):
    """A round that fixes and then loses its closer, which is the state resume
    exists to pick up. `target` names what the fixer patches: a path outside the
    card's Files is the patch apply_patch REFUSES."""
    finding = {"fixed": [], "blocking": ["F"], "noted": []}
    staged_stub(
        tmp_path,
        patches=[("fix", target, "C = 2")],
        find=finding,
        verify=finding,
        fix={"fixed": ["F"], "blocking": [], "noted": []},
    )
    claude = tmp_path / "bin/claude"
    write = "open(m.group(1).strip(), 'w').write(json.dumps(report))"
    claude.write_text(claude.read_text().replace(write, f"None if key == 'close' else {write}"))
    claude.chmod(0o755)


def _fresh_stages(tmp_path, repo, env, before):
    """The stages a run launched after `before`, over a stub that reports nothing."""
    staged_stub(tmp_path)
    result = sprint(repo, env, "review")
    return result, [stage_key(item["stdin"]) for item in launches(tmp_path)[before:]]


def test_an_incomplete_round_after_fixer_resumes_at_closer(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    reviewed = head(repo, env)
    _stop_at_closer(tmp_path)

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

    resumed, resumed_stages = _fresh_stages(tmp_path, repo, env, prior_launches)
    assert resumed.returncode == 0, resumed.stderr
    assert resumed_stages == ["close"]
    state = json.loads(marker_path(tmp_path).read_text())
    assert len(state["rounds"]) == 1
    assert "incomplete" not in state["rounds"][0]
    assert state["rounds"][0]["reviewed_head"] == reviewed
    assert state["rounds"][0]["shown_sha"] == head(repo, env)
    handoff = Path(env["XP_DATA"]) / "reports/sprint/2.fix.round-1.diff"
    assert handoff.is_file()


def test_a_refused_fixer_patch_is_not_credited_by_a_resumed_closer(tmp_path):
    """apply_patch refuses a patch reaching outside the card's Files and resets the
    tree, so the round's `fixed` claims live in no commit — yet the round records
    them and stops at `fix` like a fixer that succeeded. Resumed, its closer would
    complete a round claiming a fix with no reviewer commit and no handoff diff to
    check it against, and land clears on the empty covered range."""
    repo, env, _g = make_repo(tmp_path)
    before = head(repo, env)
    _stop_at_closer(tmp_path, target=".xp/config.yml")

    first = sprint(repo, env, "review")
    assert first.returncode == 2 and "the Files line does not name it" in first.stderr
    round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
    assert round_["stages"][-1] == "fix" and round_["fixed"] == ["F"], round_
    assert head(repo, env) == before, "the refused patch must not have landed"

    second, stages = _fresh_stages(tmp_path, repo, env, len(launches(tmp_path)))
    assert second.returncode == 0, second.stderr
    assert stages[0].startswith("find-") and stages[-1] == "close", stages
    rounds = json.loads(marker_path(tmp_path).read_text())["rounds"]
    assert len(rounds) == 2 and rounds[-1]["fixed"] == [], rounds


def test_a_later_round_stopped_at_its_fixer_starts_a_fresh_round(tmp_path):
    """A later round is the fixer alone: it has no closer stage to resume at, and
    the path that would launch one never loads the stage charters."""
    repo, env, _g = make_repo(tmp_path)
    staged_stub(tmp_path)
    assert sprint(repo, env, "review").returncode == 0
    staged_stub(
        tmp_path,
        patches=[("fix", ".xp/config.yml", "# stray")],
        fix={"fixed": ["F"], "blocking": [], "noted": []},
    )
    second = sprint(repo, env, "review")
    assert second.returncode == 2 and "the Files line does not name it" in second.stderr
    rounds = json.loads(marker_path(tmp_path).read_text())["rounds"]
    assert rounds[-1]["stages"] == ["fix"] and rounds[-1]["incomplete"], rounds

    third, stages = _fresh_stages(tmp_path, repo, env, len(launches(tmp_path)))
    assert third.returncode == 0, third.stderr
    assert "Traceback" not in third.stderr, third.stderr
    assert stages == ["fix"], stages
    assert len(json.loads(marker_path(tmp_path).read_text())["rounds"]) == 3


def test_an_underivable_legacy_round_falls_back_to_a_full_round(tmp_path):
    """`review` is the only command that runs a review, so refusing it and naming
    "run a full review" as the repair leaves the sprint with no next action: every
    later invocation reaches the same refusal."""
    repo, env, _g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    state = json.loads(marker_path(tmp_path).read_text())
    for key in ("reviewed_head", "shown_sha"):
        state["rounds"][-1].pop(key)
        state.pop(key)
    marker_path(tmp_path).write_text(json.dumps(state))
    Path(env["XP_DATA"], "reports/sprint/2.fix.round-1.patch").unlink()

    retried, stages = _fresh_stages(tmp_path, repo, env, len(launches(tmp_path)))
    assert retried.returncode == 0, retried.stderr
    assert "cannot be derived" in retried.stderr and "fresh round" in retried.stderr
    assert stages[0].startswith("find-"), stages


def test_head_motion_after_an_incomplete_round_falls_back_to_a_full_round(tmp_path):
    repo, env, g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    (repo / "src.py").write_text((repo / "src.py").read_text() + "D = 4\n")
    g("commit", "-qam", "the lead keeps working")

    retried, stages = _fresh_stages(tmp_path, repo, env, len(launches(tmp_path)))
    assert retried.returncode == 0, retried.stderr
    assert "HEAD moved since the incomplete round" in retried.stderr
    assert stages[0].startswith("find-"), stages


def test_a_preview_neither_rewrites_the_resumed_round_nor_claims_its_reports(tmp_path):
    """`--dry-run` walks the resume path with the round already recorded, so its own
    refusal — "No round was recorded" — is the one sentence the marker must keep
    true. The unrecorded-report notice has the same premise: on resume those reports
    are the run's input, and salvage, which globs the NEXT round, records nothing."""
    repo, env, _g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    recorded = marker_path(tmp_path).read_text()

    Path(env["XP_DATA"], "reports/sprint/2.fix.round-1.json").unlink()
    preview = sprint(repo, env, "review", "--dry-run")
    assert preview.returncode == 2 and "No round was recorded" in preview.stderr
    assert marker_path(tmp_path).read_text() == recorded, "the preview rewrote the round"


def test_a_resumed_round_is_not_warned_that_its_own_reports_are_doomed(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    fix_report = Path(env["XP_DATA"], "reports/sprint/2.fix.round-1.json")

    resumed, _stages = _fresh_stages(tmp_path, repo, env, len(launches(tmp_path)))
    assert resumed.returncode == 0, resumed.stderr
    assert "DELETES" not in resumed.stderr and "salvage" not in resumed.stderr, resumed.stderr
    assert fix_report.is_file(), "the resumed round read this report; it was never doomed"
