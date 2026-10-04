"""Retained boundaries must reject their constructed target defects."""

import importlib.util
import shutil

import pytest
from close_helpers import PLUGIN


@pytest.mark.meta
@pytest.mark.parametrize(
    "guard",
    [
        "stale",
        "sibling",
        "atomic",
        "false-green",
        "question",
        "scope",
        "fix-replay",
        "reserved",
        "completed-fix-replay",
        "red-history",
    ],
)
def test_retained_guard_detects_fault(tmp_path, monkeypatch, guard):
    import plan_review_install
    import spawn_helpers
    import test_card_growth as cases
    import test_plan_findings_handoff as cards
    import test_plan_human_question as human
    from test_story_forward_progress import test_scope_amendment_returns_to_planning

    def guarantee(root):
        root.mkdir()
        if guard in ("stale", "sibling"):
            cards.test_card_snapshot_route_is_locked_and_rejects_stale_candidate(root)
        elif guard == "atomic":
            with monkeypatch.context() as patch:
                cases.test_atomic_edit_failure_retains_shared_plan(root, patch, "write")
        elif guard == "false-green":
            cases.test_current_verify_red_cannot_inherit_previous_green(root)
        elif guard == "question":
            human.test_mixed_corrections_wait_for_explicit_answer(root)
        elif guard == "scope":
            test_scope_amendment_returns_to_planning(root)
        elif guard == "fix-replay":
            cases.test_adjusted_report_correction_preserves_committed_work(root, "claude", "fixer")
        elif guard in ("completed-fix-replay", "red-history"):
            cases.test_adjusted_completed_review_rechecks_obligations(
                root, "completed" if guard == "completed-fix-replay" else "validation-red"
            )
        else:
            for field in ("title", "executor", "decision"):
                child = root / field
                child.mkdir()
                cases.test_reserved_edit_cannot_continue_without_amendment(child, field)

    guarantee(tmp_path / "control")
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    mutations = {
        "stale": (
            "scripts/plan_writer.py",
            "if card_digest(current) != expected_digest or (",
            "if False and (",
        ),
        "sibling": (
            "scripts/plan_writer.py",
            "return current_plan.replace(current, candidate, 1)",
            "return candidate",
        ),
        "atomic": (
            "scripts/plan_writer.py",
            'tmp = path.with_name(path.name + ".tmp")',
            "tmp = path",
        ),
        "false-green": (
            "scripts/close/verify_receipt.py",
            'if receipt["raw"] != raw or receipt["verify"] != verify:',
            "if False:",
        ),
        "question": ("scripts/plan_disposition.py", "if question is not None:", "if False:"),
        "scope": (
            "scripts/spawn/ready.py",
            'return bool(current and len(current.get("amendments", [])) > count)',
            "return False",
        ),
        "fix-replay": (
            "scripts/close/review_sequence.py",
            'and sequence["status"] == "incomplete"',
            'and False and sequence["status"] == "incomplete"',
        ),
        "completed-fix-replay": (
            "scripts/spawn/completion.py",
            'if sequence and sequence["status"] == "completed":',
            "if False:",
        ),
        "red-history": (
            "scripts/close/review_sequence.py",
            '[item for item in sequence["validation"] if item["error"]]',
            "[]",
        ),
        "reserved": (
            "scripts/spawn/ready.py",
            'if protected(minted["card"]) != protected(card):',
            "if False:",
        ),
    }
    relative, old, new = mutations[guard]
    path = installed / relative
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))
    monkeypatch.setenv("XP_ADJUSTMENT_PLUGIN", str(installed))
    monkeypatch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
    monkeypatch.setattr(plan_review_install, "PLUGIN", installed)
    monkeypatch.setattr(spawn_helpers, "SPAWN", installed / "scripts/spawn.py")
    monkeypatch.setattr(cards, "SPAWN", installed / "scripts/spawn.py")
    from close_helpers import close

    monkeypatch.setattr(
        cases,
        "close",
        lambda repo, env, *args: close(repo, env, *args, close=installed / "scripts/close.py"),
    )
    if guard == "atomic":
        import plan_writer

        spec = importlib.util.spec_from_file_location("fault_writer", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setattr(plan_writer, "locked_edit", module.locked_edit)
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "mutant")
