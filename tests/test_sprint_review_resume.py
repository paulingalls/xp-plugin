import json
from pathlib import Path

from close_helpers import launches
from sprint_helpers import head, make_repo, marker_path, sprint, stage_key, staged_stub

FINDERS = ["find-security", "find-state-lifecycle", "find-test-vacuity"]
READ_ONLY = [*FINDERS, "verify-1", "verify-2"]
FINDING = {"fixed": [], "blocking": ["F"], "schema": 2, "dropped": [], "debt": []}
CLEAN = {"fixed": [], "blocking": [], "schema": 2, "dropped": [], "debt": []}


def _stop_at_closer(tmp_path, target="src.py"):
    """A round that fixes and then loses its closer, which is the state resume
    exists to pick up. `target` names what the fixer patches: a path outside the
    card's Files is the patch apply_patch REFUSES."""
    finding = {"fixed": [], "blocking": ["F"], "schema": 2, "dropped": [], "debt": []}
    staged_stub(
        tmp_path,
        patches=[("fix", target, "C = 2")],
        find=finding,
        verify=finding,
        fix={"fixed": ["F"], "blocking": [], "schema": 2, "dropped": [], "debt": []},
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


def _stop_at_fixer(tmp_path):
    staged_stub(tmp_path, find=FINDING, verify=FINDING)
    claude = tmp_path / "bin/claude"
    write = "open(m.group(1).strip(), 'w').write(json.dumps(report))"
    claude.write_text(claude.read_text().replace(write, f"None if key == 'fix' else {write}"))
    claude.chmod(0o755)


def _uncommitted_fixer(tmp_path):
    repo, env, g = make_repo(tmp_path)
    reviewed = head(repo, env)
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho RED-GATE >&2\nexit 1\n")
    hook.chmod(0o755)
    _stop_at_closer(tmp_path)
    stopped = sprint(repo, env, "review")
    assert stopped.returncode == 2
    assert "RED-GATE" in Path(env["XP_DATA"], "logs/story-042-fixer.log").read_text()
    round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    assert round_["stages"][-1] == "fix" and round_["incomplete"]
    assert head(repo, env) == reviewed and g("diff", "--cached", "--quiet").returncode == 1
    return repo, env, g, hook, reviewed


def test_valid_report_prefix_is_reused_in_the_same_round(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    _stop_at_fixer(tmp_path)
    first = sprint(repo, env, "review")
    assert first.returncode == 2 and "wrote no report" in first.stderr
    before = len(launches(tmp_path))

    resumed, stages = _fresh_stages(tmp_path, repo, env, before)

    assert resumed.returncode == 0, resumed.stderr
    assert stages == ["fix", "close"]
    assert "resume" in resumed.stdout.lower() and stages[0] in resumed.stdout
    assert all(f"reused {key}" in resumed.stdout for key in READ_ONLY)
    rounds = json.loads(marker_path(tmp_path).read_text())["rounds"]
    assert len(rounds) == 1
    assert rounds[0]["reused"] == READ_ONLY
    assert rounds[0]["ran"] == ["fix", "close"]
    assert rounds[0]["review_base"] == _g("merge-base", "main", "HEAD").stdout.strip()


def test_a_missing_finder_report_runs_it_and_every_later_stage(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    root = Path(env["XP_DATA"]) / "reports/sprint"
    (root / "2.find-state-lifecycle.round-1.json").unlink()
    before = len(launches(tmp_path))
    staged_stub(tmp_path, find=FINDING, verify=FINDING)

    resumed = sprint(repo, env, "review")
    stages = [stage_key(item["stdin"]) for item in launches(tmp_path)[before:]]

    assert resumed.returncode == 0, resumed.stderr
    assert set(stages) == {*FINDERS[1:], "verify-1", "verify-2", "fix", "close"}
    assert stages[-2:] == ["fix", "close"]
    assert "resumes at find-state-lifecycle" in resumed.stdout
    assert json.loads(marker_path(tmp_path).read_text())["rounds"][0]["ran"] == [
        *FINDERS[1:],
        "verify-1",
        "verify-2",
        "fix",
        "close",
    ]
    assert "reused find-security" in resumed.stdout
    assert "wrote no report" in resumed.stdout + resumed.stderr


def test_an_invalid_verifier_report_runs_it_and_every_later_stage(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    root = Path(env["XP_DATA"]) / "reports/sprint"
    (root / "2.verify-1.round-1.json").write_text("{not json")
    before = len(launches(tmp_path))
    staged_stub(tmp_path, find=FINDING, verify=FINDING)

    resumed = sprint(repo, env, "review")
    stages = [stage_key(item["stdin"]) for item in launches(tmp_path)[before:]]

    assert resumed.returncode == 0, resumed.stderr
    assert set(stages) == {"verify-1", "verify-2", "fix", "close"}
    assert stages[-2:] == ["fix", "close"]
    assert "resumes at verify-1" in resumed.stdout
    assert json.loads(marker_path(tmp_path).read_text())["rounds"][0]["ran"] == [
        "verify-1",
        "verify-2",
        "fix",
        "close",
    ]
    assert all(f"reused {key}" in resumed.stdout for key in FINDERS)
    assert "not JSON" in resumed.stdout + resumed.stderr


def test_an_unresolved_fixer_tree_refuses_before_any_reviewer_launch(tmp_path):
    repo, env, _g, _hook, _reviewed = _uncommitted_fixer(tmp_path)
    before = len(launches(tmp_path))
    marker = marker_path(tmp_path).read_text()

    refused = sprint(repo, env, "review")

    assert refused.returncode == 2
    assert len(launches(tmp_path)) == before and marker_path(tmp_path).read_text() == marker
    assert refused.stderr.startswith("refused:"), refused.stderr
    assert "finish" in refused.stderr and "commit" in refused.stderr
    assert "discard" in refused.stderr


def test_a_lead_discarded_fixer_cannot_replay_committing_work(tmp_path):
    repo, env, g, hook, reviewed = _uncommitted_fixer(tmp_path)
    hook.unlink()
    assert g("reset", "--hard", reviewed).returncode == 0
    before = len(launches(tmp_path))

    resumed, stages = _fresh_stages(tmp_path, repo, env, before)

    assert resumed.returncode == 0, resumed.stderr
    assert stages == ["fix", "close"]
    correction = launches(tmp_path)[before]["stdin"]
    assert "Do not edit or commit again" in correction
    assert head(repo, env) == reviewed


def test_a_second_death_during_a_resume_does_not_empty_the_round(tmp_path):
    """A resume that re-derives NOTHING must leave the round it read alone: an empty
    record forfeits the findings land reads AND leaves stages [], which `resumable`
    never takes again — so the evidence on disk becomes unreachable."""
    repo, env, _g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    before = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    assert before["blocking"] == ["F"] and before["stages"][-1] == "fix"

    (Path(env["XP_DATA"]) / "reports/sprint/2.find-security.round-1.json").unlink()
    claude = tmp_path / "bin/claude"
    write = "open(m.group(1).strip(), 'w').write(json.dumps(report))"
    claude.write_text(claude.read_text().replace(write, f"None if 'find' in key else {write}"))
    claude.chmod(0o755)

    second = sprint(repo, env, "review")

    assert second.returncode == 2
    after = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    assert after["stages"] == before["stages"] and after["blocking"] == ["F"]
    assert after["fixed"] == ["F"], after
    assert "No round was recorded" not in after["incomplete"], after["incomplete"]


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

    retried, stages = _fresh_stages(tmp_path, repo, env, len(launches(tmp_path)))
    assert retried.returncode == 0, retried.stderr
    assert "no measured reviewed HEAD" in retried.stderr and "fresh round" in retried.stderr
    assert all(stage in retried.stderr for stage in [*READ_ONLY, "fix"])
    assert stages[0].startswith("find-"), stages


def test_head_moved_after_a_pre_fix_stop_opens_a_fresh_round(tmp_path):
    repo, env, g = make_repo(tmp_path)
    _stop_at_fixer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    recorded = json.loads(marker_path(tmp_path).read_text())["rounds"][0]["stages"]
    (repo / "src.py").write_text("A = 2\n")
    assert g("add", "src.py").returncode == 0
    assert g("commit", "-qm", "lead moves a declared path").returncode == 0

    retried, stages = _fresh_stages(tmp_path, repo, env, len(launches(tmp_path)))

    assert retried.returncode == 0, retried.stderr
    assert stages[0].startswith("find-")
    assert "fresh round" in retried.stderr and all(stage in retried.stderr for stage in recorded)


def test_explicit_review_after_lead_head_motion_preserves_the_incomplete_round(tmp_path):
    repo, env, g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    prior = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    (repo / "other.py").write_text("D = 4\n")
    g("add", "other.py")
    assert g("commit", "-qm", "the lead corrects integration").returncode == 0
    before = head(repo, env)
    retried, stages = _fresh_stages(tmp_path, repo, env, len(launches(tmp_path)))
    assert retried.returncode == 0, retried.stderr
    assert stages[0].startswith("find-")
    rounds = json.loads(marker_path(tmp_path).read_text())["rounds"]
    assert len(rounds) == 2 and rounds[0] == prior
    assert "incomplete" not in rounds[1]
    assert head(repo, env) == before


def test_a_non_descendant_head_is_not_treated_as_discarded_fixer_work(tmp_path):
    repo, env, g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    reviewed = json.loads(marker_path(tmp_path).read_text())["rounds"][0]["reviewed_head"]
    assert g("reset", "--hard", f"{reviewed}^").returncode == 0
    (repo / "sibling.py").write_text("SIBLING = 1\n")
    g("add", "sibling.py")
    assert g("commit", "-qm", "sibling history").returncode == 0
    before = len(launches(tmp_path))

    refused = sprint(repo, env, "review")

    assert refused.returncode == 2 and "ancestry" in refused.stderr
    assert str(marker_path(tmp_path)) in refused.stderr, refused.stderr
    assert len(launches(tmp_path)) == before


def test_a_preview_names_reuse_without_mutating_the_round_or_launching(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    recorded = marker_path(tmp_path).read_text()

    Path(env["XP_DATA"], "reports/sprint/2.fix.round-1.json").unlink()
    before = len(launches(tmp_path))
    preview = sprint(repo, env, "review", "--dry-run")
    assert preview.returncode == 0
    assert "reused find-security" in preview.stdout
    assert "concurrent finder stages" not in preview.stdout
    assert len(launches(tmp_path)) == before
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


def test_a_round_recorded_during_the_closer_survives_the_resume(tmp_path):
    """The closer's stub writes the marker, which is what a concurrent `salvage` does
    and what the motion gate then refuses on. The resume must mark ITS OWN round
    incomplete: rewriting `rounds[-1]` under the lock lands on the round that arrived
    beside it, and land reads that one for blocking findings."""
    repo, env, _g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    marker = marker_path(tmp_path)
    landed = {
        "fixed": [],
        "blocking": [],
        "schema": 2,
        "dropped": [{"finding": item, "reason": "fixture reason"} for item in ["salvaged"]],
        "debt": [],
        "incomplete": "host killed",
    }
    claude = tmp_path / "bin/claude"
    claude.write_text(
        claude.read_text() + "if key == 'close':\n"
        f"    state = json.loads(open({str(marker)!r}).read())\n"
        f"    state['rounds'].append({json.dumps(landed)})\n"
        f"    open({str(marker)!r}, 'w').write(json.dumps(state))\n"
    )
    claude.chmod(0o755)

    resumed = sprint(repo, env, "review")

    assert resumed.returncode == 2 and "close marker changed" in resumed.stderr
    rounds = json.loads(marker.read_text())["rounds"]
    assert len(rounds) == 2
    assert rounds[1] == landed, "the resume rewrote the round that landed beside it"
    assert "close marker changed" in rounds[0]["incomplete"], rounds[0]


def test_rebatched_verifiers_are_not_reused_over_a_different_candidate_set(tmp_path):
    """`verify-N` is a batch INDEX, not a candidate set. Reusing it because the key
    is recorded credits a refutation the verifier never made: here three candidates
    that batched into verify-1 and verify-2 become one, which batches into verify-1
    alone, so neither recorded report covers what this round must judge."""
    repo, env, _g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    root = Path(env["XP_DATA"]) / "reports/sprint"
    for slug in FINDERS[1:]:
        (root / f"2.{slug}.round-1.json").write_text(json.dumps(CLEAN))
    before = len(launches(tmp_path))

    resumed, stages = _fresh_stages(tmp_path, repo, env, before)

    assert resumed.returncode == 0, resumed.stderr
    assert stages == ["verify-1"], stages
    assert "cannot reuse verifiers" in resumed.stdout, resumed.stdout
    round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    assert round_["reused"] == FINDERS and round_["ran"] == ["verify-1"]


def test_an_incomplete_round_naming_no_stages_opens_a_fresh_round(tmp_path):
    """A round recorded before `stages` existed names no prefix to resume from, and
    absent is not empty: taking it would read a key that is not there."""
    repo, env, _g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    state = json.loads(marker_path(tmp_path).read_text())
    state["rounds"][0].pop("stages")
    marker_path(tmp_path).write_text(json.dumps(state))
    before = len(launches(tmp_path))

    retried, stages = _fresh_stages(tmp_path, repo, env, before)

    assert retried.returncode == 0, retried.stderr
    assert "Traceback" not in retried.stderr, retried.stderr
    assert stages[0].startswith("find-"), stages
    assert len(json.loads(marker_path(tmp_path).read_text())["rounds"]) == 2
