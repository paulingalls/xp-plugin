"""The close warning for an interrupted plan review's three artifact states."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"))
import review


def artifacts(tmp_path, monkeypatch, findings):
    monkeypatch.setenv("XP_DATA", str(tmp_path))
    marker = tmp_path / "markers" / "story-042.plan-review-incomplete"
    marker.parent.mkdir()
    marker.write_text(json.dumps({"pid": 1234, "findings": str(findings)}))


def test_absent_findings_are_reported_unsigned(tmp_path, monkeypatch):
    findings = tmp_path / "plans" / "story-042.md"
    artifacts(tmp_path, monkeypatch, findings)
    notice = review.plan_review_notice("story-042")
    assert "DID NOT COMPLETE" in notice and "no reviewer signed off" in notice


def test_written_findings_are_reported_as_completed_work(tmp_path, monkeypatch):
    findings = tmp_path / "plans" / "story-042.md"
    findings.parent.mkdir()
    findings.write_text('{"status": "edited", "reasons": ["found it"]}')
    artifacts(tmp_path, monkeypatch, findings)
    notice = review.plan_review_notice("story-042")
    assert str(findings) in notice and "findings" in notice
    assert "no reviewer signed off" not in notice


def test_unreadable_findings_are_named_separately(tmp_path, monkeypatch):
    findings = tmp_path / "plans"
    findings.mkdir()
    artifacts(tmp_path, monkeypatch, findings)
    notice = review.plan_review_notice("story-042")
    assert str(findings) in notice and "UNREADABLE" in notice
    assert "no reviewer signed off" not in notice
