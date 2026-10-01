import json

import pytest
from now_or_never_helpers import debt, report
from sprint_helpers import make_repo, sprint
from work_helpers import run


class TestHistoryJudgment:
    def test_legacy_finding_has_a_durable_source_linked_judgment(self, tmp_path):
        repo, env, _ = make_repo(tmp_path)
        root = tmp_path / "data"
        source = root / "closes.jsonl"
        old = {
            "story": "story-000",
            "rounds": [
                {"fixed": [], "blocking": [], "noted": ["old usage", "old storage", "old encoding"]}
            ],
        }
        source.write_text(json.dumps(old) + "\n")
        before = sprint(repo, env, "start")
        assert "legacy/untriaged: old usage" in before.stdout
        ref = debt(root)
        judgment = report(
            fixed=["old usage"],
            dropped=[{"finding": "old encoding", "reason": "too-big loud encoding policy"}],
            debt=[
                {
                    "finding": "old storage",
                    "ref": ref,
                    "too_big": "separate storage design",
                    "too_important": "silent loss",
                }
            ],
        )
        path = tmp_path / "judgment.json"
        path.write_text(json.dumps(judgment))
        judged = run(["judge", "--source", "closes.jsonl:1", "--report", str(path)], root)
        assert judged.returncode == 0, judged.stderr
        text = (root / "work.md").read_text()
        assert str(source) + ":1" in text and "too-big loud encoding policy" in text
        assert ref in text and "separate storage design" in text and "silent loss" in text
        after = sprint(repo, env, "start")
        assert after.returncode == 0, after.stderr
        assert "Unresolved finding" not in after.stdout
        assert json.loads(source.read_text()) == old

    def test_judgment_cannot_clear_a_later_occurrence_in_changed_marker(self, tmp_path):
        repo, env, _ = make_repo(tmp_path)
        root = tmp_path / "data"
        source = root / "markers/story-old.json"
        source.parent.mkdir(exist_ok=True)
        old = {"fixed": [], "blocking": [], "noted": ["old loss"]}
        source.write_text(json.dumps({"rounds": [old]}))
        path = tmp_path / "judgment.json"
        path.write_text(
            json.dumps(report(dropped=[{"finding": "old loss", "reason": "loud policy"}]))
        )
        assert run(["judge", "--source", str(source), "--report", str(path)], root).returncode == 0
        source.write_text(json.dumps({"rounds": [old, report(blocking=["old loss"])]}))
        result = sprint(repo, env, "start")
        assert "Unresolved finding" in result.stdout and "blocking: old loss" in result.stdout

    def test_triage_shows_the_latest_retention_reasons(self, tmp_path):
        repo, env, _ = make_repo(tmp_path)
        root = tmp_path / "data"
        ref = debt(root)
        for reason in ("old retention", "new retention"):
            result = run(
                [
                    "keep",
                    "--ref",
                    ref,
                    "--too-big",
                    reason,
                    "--too-important",
                    "current silent risk",
                ],
                root,
            )
            assert result.returncode == 0, result.stderr
        shown = sprint(repo, env, "start")
        assert "new retention" in shown.stdout and "current silent risk" in shown.stdout
        assert "old retention" not in shown.stdout

    def test_source_blocker_stays_visible_after_lead_judgment(self, tmp_path):
        repo, env, _ = make_repo(tmp_path)
        root = tmp_path / "data"
        source = root / "markers/story-blocked.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps({"rounds": [report(blocking=["unmet acceptance"])]}))
        path = tmp_path / "judgment.json"
        path.write_text(json.dumps(report(fixed=["unmet acceptance"])))
        result = run(["judge", "--source", str(source), "--report", str(path)], root)
        assert result.returncode == 0, result.stderr
        shown = sprint(repo, env, "start")
        assert "Unresolved finding" in shown.stdout and "blocking: unmet acceptance" in shown.stdout

    def test_archiving_a_judgment_restores_legacy_triage(self, tmp_path):
        repo, env, _ = make_repo(tmp_path)
        root = tmp_path / "data"
        source = root / "closes.jsonl"
        source.write_text(
            json.dumps({"rounds": [{"fixed": [], "blocking": [], "noted": ["old claim"]}]}) + "\n"
        )
        path = tmp_path / "judgment.json"
        path.write_text(
            json.dumps(report(dropped=[{"finding": "old claim", "reason": "loud policy"}]))
        )
        judged = run(["judge", "--source", "closes.jsonl:1", "--report", str(path)], root)
        assert judged.returncode == 0, judged.stderr
        assert "Unresolved finding" not in sprint(repo, env, "start").stdout
        disposed = run(
            [
                "archive",
                "--ref",
                judged.stdout.strip(),
                "--disposition",
                "withdrawn: incorrect lead assumption",
            ],
            root,
        )
        assert disposed.returncode == 0, disposed.stderr
        assert "legacy/untriaged: old claim" in sprint(repo, env, "start").stdout

    @pytest.mark.parametrize(
        "flaw", ["missing-source", "unknown-finding", "missing-reason", "legacy-report"]
    )
    def test_unusable_judgment_refuses_without_recording(self, tmp_path, flaw):
        root = tmp_path / "data"
        root.mkdir()
        source = root / "closes.jsonl"
        source.write_text(
            json.dumps({"rounds": [{"fixed": [], "blocking": [], "noted": ["known"]}]}) + "\n"
        )
        body = report(dropped=[{"finding": "known", "reason": "loud design concern"}])
        if flaw == "unknown-finding":
            body["dropped"][0]["finding"] = "unknown"
        if flaw == "missing-reason":
            body["dropped"][0].pop("reason")
        if flaw == "legacy-report":
            body = {"fixed": [], "blocking": [], "noted": ["known"]}
        path = tmp_path / "judgment.json"
        path.write_text(json.dumps(body))
        chosen = "closes.jsonl:2" if flaw == "missing-source" else "closes.jsonl:1"
        result = run(["judge", "--source", chosen, "--report", str(path)], root)
        assert result.returncode == 2 and "refused" in result.stderr
        assert not (root / "work.md").exists()


class TestSlateRecordLookup:
    def test_slate_bundle_lookup_executes_against_its_data_root(self, tmp_path):
        import shlex
        import subprocess
        import sys

        from slate_review_helpers import SLATE_REVIEW, slate_repo, stub_slate_reviewer

        repo, env = slate_repo(tmp_path)
        stub_slate_reviewer(tmp_path)
        ref = debt(tmp_path / "data")
        shown = subprocess.run(
            [sys.executable, str(SLATE_REVIEW), "1", "--dry-run"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert shown.returncode == 0, shown.stderr
        lookup = next(
            (
                line.removeprefix("RECORD_LOOKUP: ")
                for line in shown.stdout.splitlines()
                if line.startswith("RECORD_LOOKUP: ")
            ),
            "",
        )
        assert lookup, shown.stdout
        result = subprocess.run(
            [*shlex.split(lookup), ref], cwd=repo, env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        assert "Claim: silent loss" in result.stdout and "Too big:" in result.stdout
