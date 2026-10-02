"""Amendments are judged against bound predecessor evidence before replanning."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from plan_confirmation_support import ANSWER_REASON, QUESTION, REASON, amend, consumer, events
from plan_review_install import installed_launch
from spawn_helpers import spawn


def test_answered_block_confirms_before_planner(tmp_path):
    repo, env, seen = consumer(tmp_path)
    stopped = spawn(repo, env, "story-042")
    assert stopped.returncode != 0 and QUESTION in stopped.stderr
    amend(tmp_path, repo, env)
    resumed = spawn(repo, env, "resume", "story-042")
    assert resumed.returncode == 0, resumed.stderr
    observed = events(seen)
    assert [e["role"] for e in observed] == [
        "planner",
        "plan-reviewer",
        "plan-reviewer",
        "teammate",
        "reviewer",
    ]
    assert observed[2]["kind"] == "confirmation"
    executor = observed[3]
    assert "lease = 17" in executor["draft"]
    assert REASON in executor["draft"] and ANSWER_REASON in executor["draft"]
    assert ".confirmation-1.md" in executor["findings_path"]
    assert QUESTION in observed[2]["prompt"]


def stopped_amended(tmp_path, launch=spawn, **kwargs):
    repo, env, seen = consumer(tmp_path, **kwargs)
    first = launch(repo, env, "story-042")
    assert first.returncode != 0 and QUESTION in first.stderr
    original = (tmp_path / "data/plans/story-042.plan.md").read_bytes()
    amend(tmp_path, repo, env, launch)
    return repo, env, seen, original


def assert_confirmed(tmp_path, launch=spawn, **kwargs):
    repo, env, seen, original = stopped_amended(tmp_path, launch, **kwargs)
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    observed = events(seen)
    assert [e["role"] for e in observed].count("planner") == 1
    assert observed[2]["kind"] == "confirmation"
    executor = next(e for e in observed if e["role"] == "teammate")
    assert ".confirmation-1.md" in executor["findings_path"]
    assert "lease = 17" in executor["draft"]
    assert REASON in executor["draft"]
    manifests = list((tmp_path / "data/plans/story-042.predecessors").glob("*/manifest.json"))
    assert manifests
    draft_entry = next(
        e for e in json.loads(manifests[0].read_text()) if e["source"].endswith(".plan.md")
    )
    assert Path(draft_entry["snapshot"]).read_bytes() == original
    return observed


def test_confirmation_hands_executor_current_artifacts(tmp_path):
    observed = assert_confirmed(tmp_path)
    executor = next(e for e in observed if e["role"] == "teammate")
    assert json.loads(executor["findings"])["decision"] == "confirm"
    assert json.loads(executor["findings"])["human_question"] is None


def test_confirmation_preserves_prior_round(tmp_path):
    assert_confirmed(tmp_path)
    original = tmp_path / "data/plans/story-042.round-1.md"
    assert json.loads(original.read_text())["human_question"] == QUESTION


def test_substantive_amendment_can_require_replan(tmp_path):
    repo, env, seen, original = stopped_amended(tmp_path, decision="replan")
    (tmp_path / "replace").touch()
    resumed = spawn(repo, env, "resume", "story-042")
    assert resumed.returncode == 0, resumed.stderr
    observed = events(seen)
    assert [e["role"] for e in observed] == [
        "planner",
        "plan-reviewer",
        "plan-reviewer",
        "planner",
        "plan-reviewer",
        "teammate",
        "reviewer",
    ]
    assert observed[2]["kind"] == "confirmation" and observed[4]["kind"] == "full"
    assert observed[3]["replan_disposition"]["decision"] == "replan"
    assert "replacement requested" in observed[5]["draft"]
    assert "replacement reviewed" in observed[5]["findings"]
    digest = hashlib.sha256(original).hexdigest()
    assert list((tmp_path / "data/plans/story-042.predecessors").glob(f"*/{digest}"))
    assert (tmp_path / "data/plans/story-042.confirmation-1.md").exists()


@pytest.mark.parametrize("status", ["clean", "edited", "blocked"])
@pytest.mark.parametrize("question", [QUESTION, "New reserved choice?"])
def test_confirmation_question_blocks_every_status(tmp_path, status, question):
    repo, env, seen, _ = stopped_amended(tmp_path, status=status, question=question)
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0 and question in result.stderr
    assert all(e["role"] != "teammate" for e in events(seen))
    if status != "clean":
        draft = (tmp_path / "data/plans/story-042.plan.md").read_text()
        assert REASON in draft and ANSWER_REASON in draft
    count = len(events(seen))
    assert spawn(repo, env, "resume", "story-042").returncode != 0
    assert len(events(seen)) == count


def test_mixed_confirmation_retains_edits_and_reasons(tmp_path):
    test_confirmation_question_blocks_every_status(tmp_path, "edited", "New reserved choice?")


def test_confirmation_can_fix_new_silent_defect(tmp_path):
    repo, env, seen, _ = stopped_amended(tmp_path)
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "lease = 17\\nReason:", "lease = 17\\nsilent loss guard added\\nReason:"
        )
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    executor = next(e for e in events(seen) if e["role"] == "teammate")
    assert "silent loss guard added" in executor["draft"]


BOUNDARIES = [
    "missing-draft",
    "empty-draft",
    "nonutf8-draft",
    "changed-draft",
    "missing-findings",
    "malformed-findings",
    "changed-findings",
    "missing-evidence",
    "malformed-evidence",
    "version",
    "acceptance",
    "handoff-identity",
    "handoff-card",
    "chain-gap",
    "chain-after",
    "tree",
    "head",
    "index",
    "untracked",
    "same-dirty",
    "assume-unchanged",
    "skip-worktree",
]


def damage(tmp_path, kind, env):
    plans = tmp_path / "data/plans"
    draft = plans / "story-042.plan.md"
    findings = plans / "story-042.round-1.md"
    evidence = plans / "story-042.round-1.evidence.json"
    handoff = plans / "story-042.handoff.json"
    marker = tmp_path / "data/markers/story-042.ready.json"
    tree = tmp_path / "data/worktrees/story-042"
    if kind in ["missing-draft", "missing-findings", "missing-evidence"]:
        {"missing-draft": draft, "missing-findings": findings, "missing-evidence": evidence}[
            kind
        ].unlink()
    elif kind in ["empty-draft", "nonutf8-draft", "changed-draft"]:
        draft.write_bytes(
            {"empty-draft": b"", "nonutf8-draft": b"\xff", "changed-draft": b"changed"}[kind]
        )
    elif kind in ["malformed-findings", "changed-findings", "malformed-evidence"]:
        (evidence if kind == "malformed-evidence" else findings).write_text("broken")
    elif kind in ["version", "acceptance"]:
        value = json.loads(evidence.read_text())
        if kind == "version":
            value["version"] = 999
        else:
            value["acceptance"]["digest"] = "wrong"
        evidence.write_text(json.dumps(value))
    elif kind.startswith("handoff"):
        value = json.loads(handoff.read_text())
        value["plan_review_identity" if kind.endswith("identity") else "plan_reviewed_card"] = (
            "wrong"
        )
        handoff.write_text(json.dumps(value))
    elif kind.startswith("chain"):
        value = json.loads(marker.read_text())
        if kind == "chain-gap":
            value["amendments"][-1]["card"] = "wrong"
        else:
            value["amendments"][-1].pop("after")
        marker.write_text(json.dumps(value))
    else:
        target = tree / ".xp/system.md"
        if kind in ["assume-unchanged", "skip-worktree"]:
            subprocess.run(
                ["git", "update-index", "--" + kind, ".xp/system.md"], cwd=tree, env=env, check=True
            )
        if kind == "head":
            subprocess.run(
                ["git", "commit", "--allow-empty", "-qm", "motion"], cwd=tree, env=env, check=True
            )
        else:
            if kind in ("untracked", "same-dirty"):
                target = tree / ("dirty.txt" if kind == "same-dirty" else "new.txt")
            target.write_text("changed bytes\n")
            if kind == "index":
                subprocess.run(["git", "add", ".xp/system.md"], cwd=tree, env=env, check=True)


@pytest.mark.parametrize("kind", BOUNDARIES)
def test_confirmation_evidence_boundary(tmp_path, kind):
    repo, env, seen, _ = stopped_amended(tmp_path, dirty=kind == "same-dirty")
    prior = tmp_path / "data/plans/story-042.round-1.md"
    before = prior.read_bytes()
    damage(tmp_path, kind, env)
    (tmp_path / "replace").touch()
    result = spawn(repo, env, "resume", "story-042")
    observed = events(seen)
    assert all(e.get("kind") != "confirmation" for e in observed)
    refusal = kind in [
        "changed-draft",
        "missing-findings",
        "malformed-findings",
        "changed-findings",
    ]
    if refusal:
        assert result.returncode != 0 and "restore" in result.stderr
        assert all(e["role"] != "teammate" for e in observed)
        assert len(observed) == 2
    else:
        assert result.returncode == 0, result.stderr
        assert "cannot reuse" in result.stderr
        assert [e["role"] for e in observed][2:4] == ["planner", "plan-reviewer"]
        assert (tmp_path / "data/plans/story-042.superseded-1.round-1.md").read_bytes() == before


def test_fallback_preserves_draft_before_planner(tmp_path):
    repo, env, _seen, original = stopped_amended(tmp_path)
    damage(tmp_path, "missing-evidence", env)
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "if role == 'planner':",
            "if role == 'planner':\n if os.path.exists("
            + repr(str(tmp_path / "fail"))
            + "):\n  open(re.search(r'^PLAN_PATH: (.+)$', prompt, re.M).group(1), 'w')"
            ".write('lost')\n  sys.exit(1)",
        )
    )
    (tmp_path / "fail").touch()
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0
    digest = hashlib.sha256(original).hexdigest()
    snapshots = list((tmp_path / "data/plans/story-042.predecessors").glob(f"*/{digest}"))
    assert snapshots and snapshots[0].read_bytes() == original
    assert (tmp_path / "data/plans/story-042.plan.md").read_text() == "lost"


@pytest.mark.parametrize("decision", [None, "missing", "unknown", "unexplained"])
def test_invalid_confirmation_decision_refuses(tmp_path, decision):
    repo, env, seen, _ = stopped_amended(tmp_path, decision=decision)
    if decision == "missing":
        binary = tmp_path / "bin/claude"
        binary.write_text(binary.read_text().replace(", 'decision': 'missing'", ""))
    if decision == "unexplained":
        binary = tmp_path / "bin/claude"
        binary.write_text(
            binary.read_text().replace("'decision': 'unexplained'", "'decision': 'replan'")
        )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0
    assert all(e["role"] not in ("teammate",) for e in events(seen))
    assert [e["role"] for e in events(seen)].count("planner") == 1


@pytest.mark.parametrize("motion", ["card", "credential", "tree", "findings", "evidence"])
def test_confirmation_refuses_concurrent_motion(tmp_path, motion):
    repo, env, seen, _ = stopped_amended(tmp_path)
    binary = tmp_path / "bin/claude"
    target = {
        "card": tmp_path / "data/plan.md",
        "credential": tmp_path / "data/markers/story-042.ready.json",
        "tree": tmp_path / "data/worktrees/story-042/.xp/system.md",
        "findings": tmp_path / "data/plans/story-042.round-1.md",
        "evidence": tmp_path / "data/plans/story-042.round-1.evidence.json",
    }[motion]
    binary.write_text(
        binary.read_text().replace(
            " if confirming:\n", f' if confirming:\n  open({str(target)!r}, "a").write("motion")\n'
        )
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0 and "refused" in result.stderr
    assert all(e["role"] != "teammate" for e in events(seen))


def test_confirmation_lost_findings_cannot_certify(tmp_path):
    repo, env, seen, _ = stopped_amended(tmp_path)
    path = tmp_path / "data/plans/story-042.round-1.md"
    original = path.read_bytes()
    path.unlink()
    assert spawn(repo, env, "resume", "story-042").returncode != 0
    assert len(events(seen)) == 2
    path.write_bytes(original)
    assert spawn(repo, env, "resume", "story-042").returncode == 0


def test_confirmation_retry_preserves_completed_round(tmp_path):
    repo, env, _seen, _ = stopped_amended(tmp_path, question="Another ruling?")
    assert spawn(repo, env, "resume", "story-042").returncode != 0
    first = tmp_path / "data/plans/story-042.confirmation-1.md"
    original = first.read_bytes()
    card = tmp_path / "data/plan.md"
    card.write_text(card.read_text().replace("lease = 17.", "lease = 17. Another ruling answered."))
    assert spawn(repo, env, "amend", "story-042", "--reason", "second answer").returncode == 0
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace("'human_question': 'Another ruling?'", "'human_question': None")
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert first.read_bytes() == original
    assert (tmp_path / "data/plans/story-042.confirmation-2.md").exists()


def test_amended_confirmation_survives_full_review_cap(tmp_path, launch=spawn):
    repo, env, seen = consumer(tmp_path)
    assert launch(repo, env, "story-042").returncode != 0
    from spawn_helpers import SPAWN

    tree = tmp_path / "data/worktrees/story-042"
    code = (
        f"import sys; sys.path[:0] = [{str(SPAWN.parent)!r}, "
        f"{str(SPAWN.parent / 'spawn')!r}]; "
        "import plan_review, handoff, ready; from work import data_root; "
        "result = plan_review.run_foreground('story-042', "
        "handoff.draft_path(data_root(), 'story-042')); "
        "handoff.mark_plan_reviewed(data_root(), 'story-042', "
        "ready.current_digest('story-042'), result.acceptance); "
        "handoff.mark_stage(data_root(), 'story-042', 'plan-reviewer', 'blocked')"
    )
    second = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tree,
        env=env | {"XP_SPAWN_TEST": "1"},
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr
    assert len(events(seen)) == 3
    assert (tmp_path / "data/plans/story-042.round-2.md").exists()
    amend(tmp_path, repo, env, launch)
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert events(seen)[3]["kind"] == "confirmation"


def test_unchanged_confirmation_does_not_relaunch_forever(tmp_path):
    test_confirmation_question_blocks_every_status(tmp_path, "edited", QUESTION)


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("decision", ["confirm", "replan"])
def test_installed_confirmation_and_replan_paths(tmp_path, harness, decision):
    launch = installed_launch(tmp_path)
    if decision == "confirm":
        assert_confirmed(tmp_path, launch, harness=harness)
    else:
        repo, env, seen, _ = stopped_amended(tmp_path, launch, harness=harness, decision=decision)
        (tmp_path / "replace").touch()
        result = launch(repo, env, "resume", "story-042")
        assert result.returncode == 0, result.stderr
        assert [e["role"] for e in events(seen)] == [
            "planner",
            "plan-reviewer",
            "plan-reviewer",
            "planner",
            "plan-reviewer",
            "teammate",
            "reviewer",
        ]
        assert events(seen)[2]["kind"] == "confirmation"


@pytest.mark.parametrize("prior_status", ["clean", "edited"])
def test_evidence_amendment_confirms_existing_plan(tmp_path, prior_status):
    repo, env, seen = consumer(tmp_path, initial_status=prior_status, initial_question=None)
    first = spawn(repo, env, "story-042")
    assert first.returncode != 0
    assert len(events(seen)) == 2
    card = tmp_path / "data/plan.md"
    card.write_text(
        card.read_text().replace("Context: demo.", "Context: measured evidence now recorded.")
    )
    assert spawn(repo, env, "amend", "story-042", "--reason", "evidence correction").returncode == 0
    (tmp_path / "executor-stop").unlink()
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert events(seen)[2]["kind"] == "confirmation"
    assert [e["role"] for e in events(seen)].count("planner") == 1


def test_failed_preservation_never_launches_planner(tmp_path):
    repo, env, seen, _ = stopped_amended(tmp_path)
    damage(tmp_path, "missing-evidence", env)
    (tmp_path / "data/plans/story-042.predecessors").write_text("blocks snapshot directory")
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0 and "preserve predecessor" in result.stderr
    assert len(events(seen)) == 2
    assert (tmp_path / "data/plans/story-042.round-1.md").exists()


@pytest.mark.parametrize(
    "artifact", ["draft", "findings", "evidence", "credential", "receipt", "candidate"]
)
def test_unreadable_confirmation_input_requires_restoration(tmp_path, artifact):
    repo, env, seen, _ = stopped_amended(tmp_path)
    plans = tmp_path / "data/plans"
    path = {
        "draft": plans / "story-042.plan.md",
        "findings": plans / "story-042.round-1.md",
        "evidence": plans / "story-042.round-1.evidence.json",
        "credential": tmp_path / "data/markers/story-042.ready.json",
        "receipt": plans / "story-042.round-1.acceptance.json",
        "candidate": plans / "story-042.round-1.card.md",
    }[artifact]
    mode = path.stat().st_mode
    path.chmod(0)
    try:
        result = spawn(repo, env, "resume", "story-042")
        assert result.returncode != 0 and str(path) in result.stderr
        assert len(events(seen)) == 2
    finally:
        path.chmod(mode)
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert events(seen)[2]["kind"] == "confirmation"


@pytest.mark.parametrize("artifact", ["receipt", "candidate"])
def test_missing_card_binding_requires_restoration(tmp_path, artifact):
    repo, env, seen, _ = stopped_amended(tmp_path)
    suffix = "acceptance.json" if artifact == "receipt" else "card.md"
    path = tmp_path / f"data/plans/story-042.round-1.{suffix}"
    original = path.read_bytes()
    path.unlink()
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0 and "restore" in result.stderr
    assert len(events(seen)) == 2
    path.write_bytes(original)
    assert spawn(repo, env, "resume", "story-042").returncode == 0


def test_reason_only_amendment_is_judged_without_waiving_question(tmp_path):
    repo, env, seen = consumer(tmp_path, question=QUESTION)
    assert spawn(repo, env, "story-042").returncode != 0
    assert (
        spawn(repo, env, "amend", "story-042", "--reason", "question remains reserved").returncode
        == 0
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0 and QUESTION in result.stderr
    assert events(seen)[2]["kind"] == "confirmation"
    assert all(e["role"] != "teammate" for e in events(seen))
