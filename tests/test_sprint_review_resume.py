import json
from pathlib import Path

from close_helpers import launches
from sprint_helpers import head, make_repo, marker_path, sprint, stage_key, staged_stub

FINDERS = ["find-security", "find-state-lifecycle", "find-test-vacuity"]
READ_ONLY = [*FINDERS, "verify-1", "verify-2"]
FINDING = {"fixed": [], "blocking": ["F"], "noted": []}


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
    assert stopped.returncode == 2 and "RED-GATE" in stopped.stderr
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
    assert all(f"reused {key}" in resumed.stdout for key in READ_ONLY)
    rounds = json.loads(marker_path(tmp_path).read_text())["rounds"]
    assert len(rounds) == 1
    assert rounds[0]["reused"] == READ_ONLY
    assert rounds[0]["ran"] == ["fix", "close"]


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
    assert stages == [*FINDERS[1:], "verify-1", "verify-2", "fix", "close"]
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
    assert stages == ["verify-1", "verify-2", "fix", "close"]
    assert all(f"reused {key}" in resumed.stdout for key in FINDERS)
    assert "not JSON" in resumed.stdout + resumed.stderr


def test_an_unresolved_fixer_tree_refuses_before_any_reviewer_launch(tmp_path):
    repo, env, _g, _hook, _reviewed = _uncommitted_fixer(tmp_path)
    before = len(launches(tmp_path))
    marker = marker_path(tmp_path).read_text()

    refused = sprint(repo, env, "review")

    assert refused.returncode == 2
    assert len(launches(tmp_path)) == before and marker_path(tmp_path).read_text() == marker
    assert "finish" in refused.stderr and "commit" in refused.stderr
    assert "discard" in refused.stderr


def test_a_lead_committed_fixer_resumes_only_the_closer(tmp_path):
    repo, env, g, hook, _reviewed = _uncommitted_fixer(tmp_path)
    hook.unlink()
    assert g("commit", "-qm", "lead finishes fixer").returncode == 0
    before = len(launches(tmp_path))

    resumed, stages = _fresh_stages(tmp_path, repo, env, before)

    assert resumed.returncode == 0, resumed.stderr
    assert stages == ["close"] and "reused fix" in resumed.stdout
    round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    assert round_["reused"] == [*READ_ONLY, "fix"] and round_["ran"] == ["close"]
    handoff = Path(env["XP_DATA"]) / "reports/sprint/2.fix.round-1.diff"
    assert "lead finishes fixer" in handoff.read_text() and "+C = 2" in handoff.read_text()


def test_a_lead_discarded_fixer_reruns_it_before_the_closer(tmp_path):
    repo, env, g, hook, reviewed = _uncommitted_fixer(tmp_path)
    hook.unlink()
    assert g("reset", "--hard", reviewed).returncode == 0
    before = len(launches(tmp_path))

    resumed, stages = _fresh_stages(tmp_path, repo, env, before)

    assert resumed.returncode == 0, resumed.stderr
    assert stages == ["fix", "close"]
    round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    assert len(json.loads(marker_path(tmp_path).read_text())["rounds"]) == 1
    assert round_["fixed"] == [] and "fix" not in round_["reused"]
    assert round_["ran"] == ["fix", "close"]


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
    assert stages == ["fix", "close"]
    rounds = json.loads(marker_path(tmp_path).read_text())["rounds"]
    assert len(rounds) == 1 and rounds[0]["fixed"] == [], rounds
    assert rounds[0]["reused"] == READ_ONLY and rounds[0]["ran"] == ["fix", "close"]


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


def test_unaccounted_head_motion_after_an_incomplete_round_refuses(tmp_path):
    repo, env, g = make_repo(tmp_path)
    _stop_at_closer(tmp_path)
    assert sprint(repo, env, "review").returncode == 2
    (repo / "other.py").write_text("D = 4\n")
    g("add", "other.py")
    g("commit", "-qm", "the lead keeps working")
    before = len(launches(tmp_path))

    retried = sprint(repo, env, "review")

    assert retried.returncode == 2 and "unaccounted paths: other.py" in retried.stderr
    assert len(launches(tmp_path)) == before


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

    assert refused.returncode == 2 and "not a descendant" in refused.stderr
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
    landed = {"fixed": [], "blocking": [], "noted": ["salvaged"], "incomplete": "host killed"}
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
