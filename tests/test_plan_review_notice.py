"""The close warning binds every interrupted plan review to its own artifact."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"))
import review


def artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_DATA", str(tmp_path))
    marker = tmp_path / "markers" / "story-042.plan-review-incomplete"
    marker.parent.mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    legacy = plans / "story-042.md"
    legacy.write_text("ambient legacy findings")
    return marker, legacy


def bind(marker, findings):
    marker.write_text(json.dumps({"pid": 1234, "findings": str(findings)}))


@pytest.mark.parametrize("marker_text", ["not json", "[]"])
def test_corrupt_marker_never_guesses_ambient_legacy_findings(tmp_path, monkeypatch, marker_text):
    marker, legacy = artifacts(tmp_path, monkeypatch)
    marker.write_text(marker_text)
    notice = review.plan_review_notice("story-042")
    assert f"plan review marker is CORRUPT at {marker}" in notice
    assert str(legacy) not in notice


@pytest.mark.parametrize(
    "state", [{"pid": 1234}, {"pid": 1234, "findings": ""}, {"pid": 1234, "findings": 7}]
)
def test_marker_without_a_findings_binding_names_that_state(tmp_path, monkeypatch, state):
    marker, legacy = artifacts(tmp_path, monkeypatch)
    marker.write_text(json.dumps(state))
    notice = review.plan_review_notice("story-042")
    assert f"plan review marker has no findings binding at {marker}" in notice
    assert str(legacy) not in notice


def test_unreadable_marker_is_not_reported_as_corrupt(tmp_path, monkeypatch):
    marker, _legacy = artifacts(tmp_path, monkeypatch)
    marker.mkdir()
    notice = review.plan_review_notice("story-042")
    assert str(marker) in notice and "UNREADABLE" in notice
    assert "CORRUPT" not in notice


def test_missing_bound_findings_name_the_missing_artifact(tmp_path, monkeypatch):
    marker, _legacy = artifacts(tmp_path, monkeypatch)
    findings = tmp_path / "plans" / "story-042.round-2.md"
    bind(marker, findings)
    notice = review.plan_review_notice("story-042")
    assert str(findings) in notice and "MISSING" in notice
    assert "DID NOT COMPLETE" in notice and "no reviewer signed off" in notice
    assert "UNREADABLE" not in notice


def test_unreadable_bound_findings_are_named_separately(tmp_path, monkeypatch):
    marker, _legacy = artifacts(tmp_path, monkeypatch)
    findings = tmp_path / "plans" / "story-042.round-2.md"
    findings.mkdir()
    bind(marker, findings)
    notice = review.plan_review_notice("story-042")
    assert str(findings) in notice and "UNREADABLE" in notice
    assert "MISSING" not in notice


def test_empty_bound_findings_are_reported_unsigned(tmp_path, monkeypatch):
    marker, _legacy = artifacts(tmp_path, monkeypatch)
    findings = tmp_path / "plans" / "story-042.round-2.md"
    findings.write_text("")
    bind(marker, findings)
    notice = review.plan_review_notice("story-042")
    assert str(findings) in notice and "DID NOT COMPLETE" in notice
    assert "no reviewer signed off" in notice


def test_written_bound_findings_are_reported_as_completed_work(tmp_path, monkeypatch):
    marker, _legacy = artifacts(tmp_path, monkeypatch)
    findings = tmp_path / "plans" / "story-042.round-2.md"
    findings.write_text('{"status": "edited", "reasons": ["found it"]}')
    bind(marker, findings)
    notice = review.plan_review_notice("story-042")
    assert str(findings) in notice and "PRODUCED FINDINGS" in notice
    assert "no reviewer signed off" not in notice


@pytest.mark.parametrize("bound", [True, False])
def test_dead_round_two_never_reads_complete_round_one(tmp_path, monkeypatch, bound):
    """The unbound arm is the one that discriminates: a marker that still names
    round two is served round two by any implementation, so binding it proves
    nothing about guessing. Round two dying BEFORE it bound its artifact is the
    state a fallback resolves to an earlier round's file."""
    marker, legacy = artifacts(tmp_path, monkeypatch)
    first = tmp_path / "plans" / "story-042.round-1.md"
    second = tmp_path / "plans" / "story-042.round-2.md"
    first.write_text("complete round one")
    if bound:
        bind(marker, second)
    else:
        marker.write_text(json.dumps({"pid": 1234}))
    earlier = (first, legacy)
    read_text = Path.read_text

    def refuse_earlier_rounds(path, *args, **kwargs):
        assert path not in earlier, f"dead round two read {path} as its own result"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refuse_earlier_rounds)
    notice = review.plan_review_notice("story-042")
    assert all(str(path) not in notice for path in earlier)
    assert str(second) in notice if bound else "no findings binding" in notice
