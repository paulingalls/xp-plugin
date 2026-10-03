"""Construct invalid declarations and conflicting writes at their acceptance boundary."""

import pytest
from close import story_card
from plan_writer import CardEditRefusal, apply_card
from work import card_digest

CARD = """#### story-042 — demo   [in-progress]
Context: demo.
Decision: human choice.
Files: src/a.py, src/b.py
AC:
- Given X, Then Y
Verify: true
Verify reads: .
Executor: (default)
"""


@pytest.mark.parametrize(
    "old,new",
    [
        ("src/a.py, src/b.py", "src/a.py src/b.py"),
        ("src/a.py, src/b.py", "src/a.py (new"),
        ("Verify: true", "Verify: "),
        ("Verify: true\n", ""),
        ("Verify: true", "Verify: true | false"),
        ("Verify: true", "Verify: nonexistent-xp-command"),
        ("Verify reads: .", "Verify reads: /outside"),
        ("story-042", "story-043"),
        ("[in-progress]", "[ready]"),
    ],
)
def test_invalid_candidate_never_changes_declaration(tmp_path, old, new):
    candidate = tmp_path / "candidate.md"
    candidate.write_text(CARD.replace(old, new))
    writes = []

    def edit(mutate):
        result = mutate(CARD)
        writes.append(result)
        return result != CARD

    with pytest.raises(CardEditRefusal):
        apply_card(
            "story-042",
            card_digest(CARD),
            "in-progress",
            candidate,
            story_card,
            card_digest,
            edit,
            expected_card=CARD,
        )
    assert writes == []
    candidate.write_text(CARD.replace("Then Y", "Then repaired"))
    assert apply_card(
        "story-042",
        card_digest(CARD),
        "in-progress",
        candidate,
        story_card,
        card_digest,
        edit,
        expected_card=CARD,
    )
    assert "Then repaired" in writes[0]


def test_exact_read_is_checked_inside_lock(tmp_path):
    candidate = tmp_path / "candidate.md"
    candidate.write_text(CARD.replace("Then Y", "Then reviewed"))
    concurrent = CARD.replace("Context: demo.", "Context: concurrent.")

    def edit(mutate):
        mutate(concurrent)
        pytest.fail("stale write was accepted")

    with pytest.raises(CardEditRefusal):
        apply_card(
            "story-042",
            card_digest(concurrent),
            "in-progress",
            candidate,
            story_card,
            card_digest,
            edit,
            expected_card=CARD,
        )


def acceptance_fixture(tmp_path, monkeypatch):
    import json

    import plan_acceptance as acceptance
    from work import ready_marker_path

    monkeypatch.setenv("XP_DATA", str(tmp_path))
    plan = tmp_path / "plan.md"
    plan.write_text(CARD)
    marker = ready_marker_path("story-042")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"digest": card_digest(CARD), "card": CARD}))
    draft = tmp_path / "draft.md"
    draft.write_text("Reason: Honesty — refine the measured declaration.\n")
    out = tmp_path / "story-042.round-1.md"
    out.write_text(
        json.dumps(
            {"status": "edited", "human_question": None, "reasons": [draft.read_text().strip()]}
        )
    )
    candidate = acceptance.candidate_path(out)
    candidate.write_text(CARD.replace("Then Y", "Then refined"))
    return acceptance, plan, marker, draft, out, candidate


@pytest.mark.parametrize(
    "field,new",
    [
        ("demo   [in-progress]", "new title   [in-progress]"),
        ("Executor: (default)", "Executor: codex/other"),
        ("Decision: human choice.", "Decision: invented choice."),
    ],
)
def test_reserved_fields_cannot_acquire_reviewer_authority(tmp_path, monkeypatch, field, new):
    acceptance, plan, marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    original = marker.read_bytes()
    candidate.write_text(candidate.read_text().replace(field, new))
    with pytest.raises(CardEditRefusal, match="reserved"):
        acceptance.prepare("story-042", CARD, candidate, draft, out)
    assert marker.read_bytes() == original and plan.read_text() == CARD


@pytest.mark.parametrize("target", ["candidate", "plan", "findings", "credential", "card"])
def test_completed_round_cannot_bless_concurrent_motion(tmp_path, monkeypatch, target):
    import json

    acceptance, plan, marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    record = acceptance.prepare("story-042", CARD, candidate, draft, out)
    paths = {
        "candidate": candidate,
        "plan": draft,
        "findings": out,
        "credential": marker,
        "card": plan,
    }
    if target == "credential":
        marker.write_text(json.dumps({"digest": "new", "card": CARD}))
    elif target == "candidate":
        candidate.write_text(candidate.read_text().replace("Then refined", "Then unrelated"))
    else:
        paths[target].write_text(paths[target].read_text() + "concurrent change\n")
    original = marker.read_bytes()
    current_card = plan.read_bytes()
    with pytest.raises(CardEditRefusal):
        acceptance.publish("story-042", record)
    assert marker.read_bytes() == original and plan.read_bytes() == current_card


def test_interruption_after_card_write_recovers_only_recorded_transition(tmp_path, monkeypatch):
    acceptance, plan, marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    record = acceptance.prepare("story-042", CARD, candidate, draft, out)
    original = marker.read_bytes()
    atomic = acceptance.atomic_json

    def interrupted(path, value):
        if path == marker:
            raise OSError("injected credential write failure")
        atomic(path, value)

    monkeypatch.setattr(acceptance, "atomic_json", interrupted)
    with pytest.raises(OSError):
        acceptance.publish("story-042", record)
    assert plan.read_text() == record["after"]
    assert marker.read_bytes() == original
    monkeypatch.setattr(acceptance, "atomic_json", atomic)
    acceptance.publish("story-042", record)
    assert acceptance.latest("story-042") == record
    assert not acceptance.binding_problem("story-042")
    draft.write_text("unreviewed replacement")
    assert "accepted plan changed" in acceptance.binding_problem("story-042")


def test_accepted_snapshot_survives_later_files_growth(tmp_path, monkeypatch):
    import ready

    acceptance, plan, _marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    record = acceptance.prepare("story-042", CARD, candidate, draft, out)
    acceptance.publish("story-042", record)
    grown = (
        record["after"]
        .replace("src/b.py", "src/b.py, src/c.py (new)")
        .replace("Verify: true", "Verify: true && true")
    )
    plan.write_text(grown)
    assert ready.drift("story-042", grown) == ""
    assert acceptance.latest("story-042")["after"] == record["after"]
    changed = grown.replace("Then refined", "Then unreviewed")
    assert "edited after" in ready.drift("story-042", changed)


@pytest.mark.parametrize("corruption", [None, {}, [{"digest": "invented"}], "dropped binding"])
def test_unreadable_acceptance_cannot_certify_card(tmp_path, monkeypatch, corruption):
    import json

    import ready

    acceptance, _plan, marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    record = acceptance.prepare("story-042", CARD, candidate, draft, out)
    acceptance.publish("story-042", record)
    value = json.loads(marker.read_text())
    value["review_acceptances"] = corruption
    marker.write_text(json.dumps(value))
    assert ready.credential(marker) is None
    assert "unreadable" in ready.drift("story-042", record["after"])


def test_reserved_decision_continuations_cannot_change(tmp_path, monkeypatch):
    acceptance, plan, marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    before = CARD.replace(
        "Decision: human choice.", "Decision: human choice.\n  Reserved continuation."
    )
    import json

    plan.write_text(before)
    marker.write_text(json.dumps({"card": before, "digest": card_digest(before)}))
    candidate.write_text(before.replace("Reserved continuation.", "invented choice."))
    with pytest.raises(CardEditRefusal):
        acceptance.prepare("story-042", before, candidate, draft, out)
    candidate.write_text(before)
    assert acceptance.prepare("story-042", before, candidate, draft, out)["after"] == before


def test_foreground_recovery_keeps_question_blocked_after_redigest(tmp_path, monkeypatch):
    import json

    import ready

    acceptance, _plan, marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    value = json.loads(out.read_text()) | {"human_question": "choose a new API policy"}
    out.write_text(json.dumps(value))
    record = acceptance.prepare("story-042", CARD, candidate, draft, out)
    acceptance.publish("story-042", record)
    assert acceptance.restore_handoff(tmp_path, "story-042", {})
    from handoff import handoff_state

    assert handoff_state(tmp_path, "story-042")["stages"]["plan-reviewer"] == "blocked"
    minted = ready.credential(marker)
    minted["digest"] = card_digest(record["after"])
    marker.write_text(json.dumps(minted))
    assert not acceptance.restore_handoff(
        tmp_path, "story-042", handoff_state(tmp_path, "story-042")
    )
    from plan_review import durable_disposition

    assert durable_disposition(out.read_text())[0] == "blocked"


@pytest.mark.parametrize("context", ["card-edit", "executor"])
def test_candidate_recovery_names_actual_context_and_retains_growth(tmp_path, context):
    import re
    import shlex
    import subprocess
    import sys

    from spawn_helpers import SPAWN, make_repo

    repo, env, _g = make_repo(tmp_path)
    plan = tmp_path / "data/plan.md"
    original, status = story_card(plan.read_text(), "story-042")
    candidate = tmp_path / "caller.md"
    candidate.write_text(original.replace("src/thing.py", "src/thing.py, src/new.py (new)"))
    plan.write_text(plan.read_text().replace("Context: demo.", "Context: concurrent correction."))
    work = str(SPAWN.parent / "work.py")

    def edit(path, digest, lifecycle):
        return subprocess.run(
            [
                sys.executable,
                work,
                "edit-card",
                "story-042",
                "--context",
                context,
                "--digest",
                digest,
                "--status",
                lifecycle,
                str(path),
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

    refused = edit(candidate, card_digest(original), status)
    assert refused.returncode == 2 and context in refused.stderr
    command = re.search(r"run `([^`]+)`", refused.stderr).group(1)
    snapshot = subprocess.run(
        shlex.split(command), cwd=repo, env=env, capture_output=True, text=True
    )
    assert snapshot.returncode == 0, snapshot.stderr
    recovery = candidate.with_suffix(".recovery.md")
    recovery.write_text(
        recovery.read_text().replace("src/thing.py", "src/thing.py, src/new.py (new)")
    )
    digest = re.search(r"^digest: (.+)$", snapshot.stdout, re.M).group(1)
    lifecycle = re.search(r"^status: (.+)$", snapshot.stdout, re.M).group(1)
    result = edit(recovery, digest, lifecycle)
    assert result.returncode == 0, result.stderr
    assert "src/new.py" in plan.read_text() and "concurrent correction" in plan.read_text()


def test_receipt_for_another_story_is_not_recoverable_here(tmp_path, monkeypatch):
    acceptance, plan, marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    record = acceptance.prepare("story-042", CARD, candidate, draft, out)
    original = marker.read_bytes()
    record["story_id"] = "story-043"
    with pytest.raises(CardEditRefusal):
        acceptance.publish("story-042", record)
    assert marker.read_bytes() == original and plan.read_text() == CARD


@pytest.mark.parametrize("target", ["card", "credential"])
def test_publication_rechecks_motion_under_plan_lock(tmp_path, monkeypatch, target):
    import json

    acceptance, plan, marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    record = acceptance.prepare("story-042", CARD, candidate, draft, out)
    edit = acceptance.edit_plan
    calls = 0

    def interleaved(mutate):
        nonlocal calls
        calls += 1
        if calls == 2:
            if target == "card":
                plan.write_text(plan.read_text().replace("Then refined", "Then concurrent"))
            else:
                value = json.loads(marker.read_text()) | {"other": "concurrent credential"}
                marker.write_text(json.dumps(value))
        return edit(mutate)

    monkeypatch.setattr(acceptance, "edit_plan", interleaved)
    with pytest.raises(CardEditRefusal):
        acceptance.publish("story-042", record)
    assert acceptance.latest("story-042") is None


@pytest.mark.parametrize("fault", ["missing", "unreadable", "uncredentialed"])
def test_review_basis_refuses_before_recording_acceptance(tmp_path, monkeypatch, fault):
    import json

    acceptance, plan, marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    if fault == "missing":
        marker.unlink()
    elif fault == "unreadable":
        marker.write_text("not JSON")
    else:
        other = CARD.replace("Then Y", "Then different authority")
        marker.write_text(json.dumps({"card": other, "digest": card_digest(other)}))
    with pytest.raises(CardEditRefusal):
        acceptance.prepare("story-042", CARD, candidate, draft, out)
    assert not acceptance.receipt_path(out).exists()
    assert plan.read_text() == CARD


def test_interrupted_handoff_does_not_adopt_another_source_round(tmp_path, monkeypatch):
    import json

    from handoff import marker_path
    from plan_review import incomplete_marker

    acceptance, _plan, _marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    record = acceptance.prepare("story-042", CARD, candidate, draft, out)
    acceptance.publish("story-042", record)
    marker = incomplete_marker("story-042")
    marker.parent.mkdir(exist_ok=True)
    other = tmp_path / "unrelated-round.md"
    other.write_text(out.read_text())
    marker.write_text(json.dumps({"findings": str(other)}))
    assert not acceptance.restore_handoff(tmp_path, "story-042", {})
    assert not marker_path(tmp_path, "story-042").exists()


def test_invalid_review_candidate_names_the_resume_that_reruns_review(tmp_path):
    import re
    import shlex
    import subprocess
    from pathlib import Path

    from spawn_helpers import make_repo, spawn
    from test_card_update_contract import edited_stages
    from test_spawn_stages import event_roles

    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    malformed = ("src/thing.py, src/other.py", "src/thing.py src/other.py")
    events = edited_stages(tmp_path, [malformed])
    plan = Path(env["XP_DATA"]) / "plan.md"
    refused = spawn(repo, env, "story-042")
    assert refused.returncode != 0 and malformed[1] not in plan.read_text()
    command = re.search(r"invalid review candidate.*run `([^`]+)`", refused.stderr).group(1)
    binary = tmp_path / "bin/claude"
    binary.write_text(binary.read_text().replace("text = text.replace(old, new)", "pass"))
    resumed = subprocess.run(
        shlex.split(command), cwd=repo, env=env, capture_output=True, text=True
    )
    assert resumed.returncode == 0, resumed.stderr
    assert event_roles(events).count("plan-reviewer") == 2
    assert "teammate" in event_roles(events)


def test_reason_amendment_serializes_review_publication(tmp_path, monkeypatch):
    import fcntl
    import json
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import ready
    from ready import plan_needs_replan

    acceptance, _plan, marker, draft, out, candidate = acceptance_fixture(tmp_path, monkeypatch)
    candidate.write_text(CARD)
    out.write_text(json.dumps(dict(status="clean", human_question=None, reasons=[])))
    prior = acceptance.prepare("story-042", CARD, candidate, draft, out)
    acceptance.publish("story-042", prior)
    out = tmp_path / "story-042.round-2.md"
    out.write_text(json.dumps(dict(status="clean", human_question=None, reasons=[])))
    record = acceptance.prepare("story-042", CARD, candidate, draft, out)
    monkeypatch.setattr(ready, "progressed", lambda sid: True)
    entering = Event()
    proceed = Event()
    original_edit = acceptance.edit_plan
    original_read = ready.credential
    interleaved = False
    future = None

    def publication_edit(mutate):
        entering.set()
        assert proceed.wait(10), "amendment did not release the publication probe"
        return original_edit(mutate)

    def publish():
        try:
            acceptance.publish("story-042", record)
            return "published"
        except CardEditRefusal as error:
            return str(error)

    def credential(path):
        nonlocal interleaved, future
        snapshot = original_read(path)
        if not interleaved:
            interleaved = True
            future = pool.submit(publish)
            assert entering.wait(10), "publication did not reach the shared lock"
            with open(tmp_path / "locks/plan.lock", "a+") as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    proceed.set()
                else:
                    fcntl.flock(probe, fcntl.LOCK_UN)
                    proceed.set()
                    assert future.result(timeout=10) == "published"
        return snapshot

    monkeypatch.setattr(acceptance, "edit_plan", publication_edit)
    monkeypatch.setattr(ready, "credential", credential)
    before_digest = original_read(marker)["digest"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert ready.amend("story-042", "reason-only evidence") == 0
        outcome = future.result(timeout=10)
    assert interleaved and original_read(marker)["digest"] == before_digest
    retained = record if outcome == "published" else prior
    if outcome != "published":
        assert "credential changed" in outcome
    assert acceptance.latest("story-042") == retained
    assert not acceptance.binding_problem("story-042")
    assert plan_needs_replan("story-042", {})
    draft.write_text("unreviewed plan replacement")
    assert "accepted plan changed" in acceptance.binding_problem("story-042")
