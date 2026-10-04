"""Disposable consumer guarantees detect removed integration boundaries."""

import shutil

import pytest
from close_helpers import PLUGIN


@pytest.mark.meta
@pytest.mark.parametrize("guard", ["source", "branch", "receipt", "clean", "cleanup"])
def test_free_shipping_boundary_faults(tmp_path, monkeypatch, guard):
    import close_helpers
    from test_close_free_post_merge import (
        test_post_merge_motion_after_publication_preserves_cleanup_credentials,
        test_post_merge_requires_clean_shipping_source,
        test_post_merge_verify_motion_preserves_unreviewed_work,
    )

    motion = "branch" if guard == "branch" else "head"

    def guarantee(root):
        root.mkdir()
        if guard == "cleanup":
            test_post_merge_motion_after_publication_preserves_cleanup_credentials(root)
        elif guard == "clean":
            test_post_merge_requires_clean_shipping_source(root)
        else:
            test_post_merge_verify_motion_preserves_unreviewed_work(root, motion)

    guarantee(tmp_path / "control")
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    path = installed / "scripts/close/free.py"
    old, new = {
        "source": ("tracked_state() != shipping_source", "False"),
        "cleanup": ("if motion := shipping_motion():", 'if motion := "":'),
        "clean": (
            'if any(shipping_source[name] for name in ("status", "staged", "worktree")):',
            "if False:",
        ),
        "branch": (
            'or git("branch", "--show-current").stdout.strip() != shipping_branch',
            "or False",
        ),
        "receipt": ("invalidation = verify_receipt.invalidate(key)", 'invalidation = ""'),
    }[guard]
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))
    monkeypatch.setattr(close_helpers, "CLOSE", installed / "scripts/close.py")
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "fault")


@pytest.mark.meta
@pytest.mark.parametrize("consumer", ["compact", "fixer", "closer"])
@pytest.mark.parametrize("evidence", ["report", "refusal"])
def test_correction_evidence_removal_reds_consumer(tmp_path, monkeypatch, consumer, evidence):
    import plan_review_install
    from test_card_growth import test_adjusted_report_correction_preserves_committed_work
    from test_story_review_flow import test_report_correction_uses_retained_report_and_refusal

    def guarantee(root):
        root.mkdir()
        if consumer == "compact":
            test_report_correction_uses_retained_report_and_refusal(root)
        else:
            test_adjusted_report_correction_preserves_committed_work(root, "claude", consumer)

    guarantee(tmp_path / "control")
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    path = installed / "scripts/close/review_sequence.py"
    old, new = {
        "report": (
            r"""+ f"\nPrior report: {previous['path']}\nPrior log: {previous['log']}\n" """.rstrip()
            + "\n            + retained",
            '+ ""',
        ),
        "refusal": ('+ sequence["problem"]', '+ ""'),
    }[evidence]
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))
    monkeypatch.setattr(plan_review_install, "PLUGIN", installed)
    monkeypatch.setenv("XP_ADJUSTMENT_PLUGIN", str(installed))
    monkeypatch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "fault")
