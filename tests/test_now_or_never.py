import json
import sys

import pytest
from bookkeep import render_prior_rounds
from close_helpers import WORK, close, make_repo, marker, stub_reviewer
from now_or_never_helpers import debt, report, write_report
from now_or_never_judgment_cases import (  # noqa: F401
    TestHistoryJudgment,
    TestSlateRecordLookup,
)
from now_or_never_legacy_cases import TestLegacyState  # noqa: F401
from now_or_never_release_cases import TestReleaseBoundaries, TestRoundAcceptance  # noqa: F401
from review_report import read_report
from sprint_helpers import make_repo as sprint_repo
from sprint_helpers import marker_path, sprint, staged_stub
from work_helpers import run


class TestReportAcceptance:
    @pytest.mark.parametrize("reason", [None, "", " ", 4])
    def test_drop_reason_is_required(self, tmp_path, reason):
        data = report(dropped=[{"finding": "loud oversized change", "reason": reason}])
        path = write_report(tmp_path, data)
        parsed, error = read_report(path)
        assert error and not parsed

    def test_valid_drop_is_preserved_without_display_caps(self, tmp_path):
        data = report(dropped=[{"finding": "f" * 900, "reason": "loud and outside concern"}])
        parsed, error = read_report(write_report(tmp_path, data))
        assert not error, error
        assert parsed == data

    @pytest.mark.parametrize("key", ["fixed", "blocking"])
    def test_structured_items_are_never_stringified(self, tmp_path, key):
        parsed, error = read_report(
            write_report(
                tmp_path,
                report(**{key: [{"finding": "lost structure"}]}),
            )
        )
        assert error and not parsed

    def test_new_round_cannot_certify_legacy_report(self, tmp_path):
        parsed, error = read_report(
            write_report(tmp_path, {"fixed": [], "blocking": [], "noted": ["old finding"]})
        )
        assert error and not parsed


class TestDebtAcceptance:
    @pytest.mark.parametrize("change", ["ref", "too_big", "too_important"])
    def test_debt_needs_usable_record_and_both_bars(self, tmp_path, monkeypatch, change):
        root = tmp_path / "data"
        ref = debt(root)
        monkeypatch.setenv("XP_DATA", str(root))
        item = {
            "finding": "silent loss",
            "ref": ref,
            "too_big": "separate design",
            "too_important": "corrupted record",
        }
        parsed, error = read_report(write_report(tmp_path, report(debt=[item])))
        assert not error and parsed["debt"] == [item]
        item[change] = "bad-id" if change == "ref" else ""
        parsed, error = read_report(write_report(tmp_path, report(debt=[item])))
        assert error and not parsed

    def test_disposed_reference_remains_historical_but_not_fresh(self, tmp_path, monkeypatch):
        root = tmp_path / "data"
        ref = debt(root)
        monkeypatch.setenv("XP_DATA", str(root))
        item = {
            "finding": "loss",
            "ref": ref,
            "too_big": "separate design",
            "too_important": "silent corruption",
        }
        path = write_report(tmp_path, report(debt=[item]))
        assert not read_report(path)[1]
        assert (
            run(
                ["archive", "--ref", ref, "--disposition", "dropped: concern retired"], root
            ).returncode
            == 0
        )
        assert read_report(path)[1]
        assert read_report(path, fresh=False)[0]["debt"] == [item]

    @pytest.mark.parametrize("field", ["Claim", "Files", "Falsifier"])
    def test_debt_reference_requires_usable_record_fields(self, tmp_path, monkeypatch, field):
        root = tmp_path / "data"
        ref = debt(root)
        monkeypatch.setenv("XP_DATA", str(root))
        item = {
            "finding": "loss",
            "ref": ref,
            "too_big": "design",
            "too_important": "silent corruption",
        }
        path = write_report(tmp_path, report(debt=[item]))
        assert not read_report(path)[1]
        record = root / "work.md"
        lines = [
            line for line in record.read_text().splitlines() if not line.startswith(field + ":")
        ]
        lines.insert(1, "Id: " + ref)
        if field == "Falsifier":
            lines.append("Falsifier: ` `")
        record.write_text("\n".join(lines) + "\n")
        assert read_report(path)[1]


class TestDispositionWalk:
    def test_story_round_to_next_bundle_and_land(self, tmp_path):
        repo, env, _ = make_repo(tmp_path)
        ref = debt(tmp_path / "data")
        dispositions = report(
            dropped=[{"finding": "loud oversized change", "reason": "announces itself"}],
            debt=[
                {
                    "finding": "loss",
                    "ref": ref,
                    "too_big": "design ruling",
                    "too_important": "silent corruption",
                }
            ],
        )
        stub_reviewer(tmp_path, report=dispositions)
        reviewed = close(repo, env, "review")
        assert reviewed.returncode == 0, reviewed.stderr
        assert marker(tmp_path)["rounds"][0]["dropped"] == dispositions["dropped"]
        prior = render_prior_rounds(marker(tmp_path)["rounds"])
        assert "announces itself" in prior and ref in prior and "design ruling" in prior
        stub_reviewer(tmp_path, report=report())
        assert close(repo, env, "review").returncode == 0
        landed = close(repo, env, "land")
        assert landed.returncode == 0, landed.stderr
        log = json.loads((tmp_path / "data" / "closes.jsonl").read_text())
        assert log["rounds"][0]["debt"] == dispositions["debt"]

    def test_complete_sprint_preserves_each_stage_disposition(self, tmp_path):
        repo, env, _ = sprint_repo(tmp_path)
        finder = {"finding": "candidate below bar", "reason": "loud"}
        verifier = {"finding": "refuted candidate", "reason": "covered by existing guard"}
        closer = {"finding": "unrelated expansion", "reason": "loud cross-concern"}
        staged_stub(
            tmp_path,
            find=report(blocking=["F"], dropped=[finder]),
            verify=report(blocking=["F"], dropped=[verifier]),
            fix=report(fixed=["F"]),
            close=report(dropped=[closer]),
        )
        result = sprint(repo, env, "review")
        assert result.returncode == 0, result.stderr
        recorded = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert recorded["dropped"] == [finder, verifier, closer]
        assert recorded["fixed"] == ["F"] and recorded["blocking"] == []

    def test_distinct_reasons_survive_incomplete_aggregation_and_caps(self, tmp_path):
        sys.path.insert(0, str(WORK.parent / "close"))
        from sprint_review_resume import record

        items = [{"finding": "f" * 900, "reason": str(i)} for i in range(25)]
        reports = [report(dropped=items), report(dropped=items)]
        kept = record(
            reports,
            ["find", "verify"],
            "stopped",
            "a",
            "a",
            ("fixed", "blocking", "dropped", "debt"),
        )
        assert kept["dropped"] == items
        assert "24" in render_prior_rounds([kept])


class TestSprintTriage:
    def test_salvaged_blocker_stays_visible_until_a_later_launch_reviews_it(self, tmp_path):
        from close_helpers import marker_file

        repo, env, _ = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=report())
        assert close(repo, env, "review").returncode == 0
        source = marker_file(tmp_path)
        state = json.loads(source.read_text())
        state["rounds"].insert(
            0, report(blocking=["salvaged silent loss"]) | {"salvaged": True, "round_file": 8}
        )
        source.write_text(json.dumps(state))
        refused = close(repo, env, "land")
        assert refused.returncode == 2 and "salvaged silent loss" in refused.stderr
        sprint_case = tmp_path / "sprint"
        sprint_case.mkdir()
        sprint_tree, sprint_env, _ = sprint_repo(sprint_case)
        source = sprint_case / "data/markers/story-042.json"
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps(state))
        shown = sprint(sprint_tree, sprint_env, "start")
        assert shown.returncode == 0, shown.stderr
        assert "blocking: salvaged silent loss" in shown.stdout
        state["rounds"].append(report() | {"round_file": 9})
        source.write_text(json.dumps(state))
        cleared = sprint(sprint_tree, sprint_env, "start")
        assert cleared.returncode == 0, cleared.stderr
        assert "blocking: salvaged silent loss" not in cleared.stdout

    def test_keep_restates_both_bars_and_drop_keeps_reason(self, tmp_path):
        ref = debt(tmp_path)
        result = run(
            [
                "keep",
                "--ref",
                ref,
                "--too-big",
                "design ruling",
                "--too-important",
                "silent corruption",
            ],
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
        text = (tmp_path / "work.md").read_text()
        assert f"Keeps: {ref}" in text and "Too big: design ruling" in text
        assert (
            run(
                ["keep", "--ref", ref, "--too-big", "", "--too-important", "silent corruption"],
                tmp_path,
            ).returncode
            == 2
        )
        assert run(["archive", "--ref", ref, "--disposition", ""], tmp_path).returncode == 2

    def test_start_emits_every_open_debt_and_legacy_finding(self, tmp_path):
        repo, env, _ = sprint_repo(tmp_path)
        ref = debt(tmp_path / "data")
        (tmp_path / "data" / "closes.jsonl").write_text(
            json.dumps(
                {
                    "story": "story-042",
                    "rounds": [{"fixed": [], "blocking": [], "noted": ["unjudged loss"]}],
                    "closed_at": "2000-01-01T00:00:00Z",
                }
            )
            + "\n"
        )
        run(["note", "discovery about our design"], tmp_path / "data")
        result = sprint(repo, env, "start")
        assert result.returncode == 0, result.stderr
        assert ref in result.stdout and "unjudged loss" in result.stdout
        assert "discovery about our design" in result.stdout
        assert "exceptional keep" in result.stdout

    def test_triage_exposes_unusable_debt_and_malformed_marker(self, tmp_path):
        repo, env, _ = sprint_repo(tmp_path)
        root = tmp_path / "data"
        ref = debt(root)
        work = root / "work.md"
        work.write_text(work.read_text().replace("Claim: ", f"Id: {ref}\nMissing claim: "))
        marker = root / "markers/story-099.json"
        marker.parent.mkdir(exist_ok=True)
        marker.write_text("{broken")
        result = sprint(repo, env, "start")
        assert result.returncode == 2, result.stderr
        assert f"Open debt {ref} (" in result.stdout
        assert f"Unusable debt {ref}:" in result.stdout
        assert str(marker) in result.stdout and "Unreadable" in result.stdout

    def test_slate_transports_budget_and_stub_verdict(self, tmp_path):
        """The stub supplies judgment; this checks budget/slate delivery and transport."""
        import subprocess

        from slate_review_helpers import SLATE_REVIEW, slate_repo, stub_slate_reviewer

        for count in (0, 2):
            case = tmp_path / str(count)
            case.mkdir()
            repo, env = slate_repo(case)
            plan = case / "data/plan.md"
            plan.write_text(
                "# plan\n### Sprint 1\n"
                + "".join(
                    f"#### story-{i} — item   [planned]\nContext: item.\n"
                    + ("Debt: existing record\n" if i < count else "")
                    + "Files: src/thing.py\nAC:\n- Given item, Then accepted.\nVerify: true\n"
                    for i in range(2)
                )
            )
            stub_slate_reviewer(case)
            binary = case / "bin/claude"
            body = binary.read_text()
            body = body.replace(
                "prompt = sys.stdin.read()",
                """prompt = sys.stdin.read()
budget = float(re.search(r'^debt_budget: (.+)$', prompt, re.M).group(1))
slate = prompt.split('## Full proposed slate', 1)[1].split('## Sprint capacity', 1)[0]
card_count = len(re.findall(r'^#### story-', slate, re.M))
debt_count = len(re.findall(r'^Debt:', slate, re.M))
verdict = 'RED' if debt_count / card_count > budget else 'GREEN'
""",
                1,
            )
            line = next(line for line in body.splitlines() if line.startswith("open(path.group"))
            body = body.replace(line, "open(path.group(1), 'w').write('## Slate — ' + verdict)")
            binary.write_text(body)
            result = subprocess.run(
                [sys.executable, str(SLATE_REVIEW), "1"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stderr
            kept = (case / "data/slate-reviews/sprint-1.round-1.md").read_text()
            assert ("## Slate — RED" if count else "## Slate — GREEN") in kept


class TestDecisionSites:
    def test_executor_handles_plan_findings_within_card_authority(self, tmp_path):
        from test_plan_findings_handoff import test_first_executor_reads_current_plan_findings

        test_first_executor_reads_current_plan_findings(tmp_path)
        events = [json.loads(line) for line in (tmp_path / "seen.jsonl").read_text().splitlines()]
        prompt = next(event["prompt"] for event in events if event["role"] == "teammate")
        assert "Fix authorized work" in prompt and "Escalate reserved choices" in prompt
        assert "one-line" in prompt and "both" in prompt and "real record reference" in prompt

    def test_plan_and_slate_keep_native_dispositions(self, tmp_path):
        import subprocess

        from slate_review_helpers import SLATE_REVIEW, slate_repo, stub_slate_reviewer
        from spawn_helpers import make_repo as plan_repo
        from test_plan_review import PLAN_REVIEW, stub_planner

        repo, env, _ = plan_repo(tmp_path)
        ref = debt(tmp_path / "data")
        summary = (
            "Dropped: oversized loud addition because announces itself. "
            f"Debt {ref}: separate design; silent loss. Reserved: ask lead."
        )
        native = {"status": "clean", "human_question": None, "reasons": [], "summary": summary}
        stub_planner(tmp_path, findings="```json\n" + json.dumps(native) + "\n```")
        draft = tmp_path / "draft.md"
        draft.write_text("# plan\n")
        result = subprocess.run(
            [sys.executable, str(PLAN_REVIEW), "story-042", str(draft)],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        kept = (tmp_path / "data/plans/story-042.round-1.md").read_text()
        assert summary in kept and '"status": "clean"' in kept
        other = tmp_path / "slate"
        other.mkdir()
        repo, env = slate_repo(other)
        markdown = (
            "## story-042 — GREEN\n"
            + summary
            + "\n## Slate — GREEN\n## Unresolved\nReserved: lead must choose scope.\n"
        )
        stub_slate_reviewer(other, findings=markdown)
        result = subprocess.run(
            [sys.executable, str(SLATE_REVIEW), "1"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert markdown in (other / "data/slate-reviews/sprint-1.round-1.md").read_text()


class TestRecordPolarity:
    def test_exception_metadata_does_not_change_falsifier_polarity(self, tmp_path):
        ref = debt(tmp_path)
        text = (tmp_path / "work.md").read_text()
        assert "Too big:" in text and "Too important:" in text
        guard = tmp_path / "debt-guard.json"
        guard.write_text('{"records": []}')
        command = next(
            line[len("Falsifier: `") : -1]
            for line in text.splitlines()
            if line.startswith("Falsifier: `")
        )
        args = ["--claim", "silent loss", "--falsifier", command, "--files", str(guard)]
        assert run(["debt", *args], tmp_path).returncode == 2
        assert run(["bug", *args], tmp_path).returncode == 0
        assert (
            run(
                ["resolve", "--ref", ref, "--falsifier", command, "--covered-by", "none"], tmp_path
            ).returncode
            == 2
        )


class TestPresentation:
    def test_session_subprocess_preserves_disposition_or_names_full_source(self, tmp_path):
        import subprocess

        repo, env, _ = make_repo(tmp_path)
        data = report(dropped=[{"finding": "loud addition", "reason": "crosses concern"}])
        (tmp_path / "data/closes.jsonl").write_text(
            json.dumps(
                {
                    "story": "story-042",
                    "title": "closed story",
                    "closed_at": "2026-01-01T00:00:00Z",
                    "rounds": [data],
                }
            )
            + "\n"
        )
        result = subprocess.run(
            [sys.executable, str(WORK.parent / "session_start.py"), "recover"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "loud addition" in result.stdout and "crosses concern" in result.stdout
        data["dropped"] *= 25
        (tmp_path / "data/closes.jsonl").write_text(
            json.dumps({"story": "story-042", "title": "closed story", "rounds": [data]}) + "\n"
        )
        result = subprocess.run(
            [sys.executable, str(WORK.parent / "session_start.py"), "recover"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "closes.jsonl" in result.stdout

    @pytest.mark.parametrize("length", [0, 1000])
    def test_sprint_pr_body_keeps_drop_reason_and_debt_bars(self, tmp_path, length):
        from sprint_release_body_cases import record_release, release_state, release_tools

        repo, env, g = sprint_repo(tmp_path)
        ref = debt(tmp_path / "data")
        dropped = [
            {
                "finding": "loud expansion" + "f" * length,
                "reason": "announces itself" + "r" * length,
            }
        ]
        kept = [
            {
                "finding": "loss" + "f" * length,
                "ref": ref,
                "too_big": "separate design" + "b" * length,
                "too_important": "silent corruption" + "i" * length,
            }
        ]
        record_release(tmp_path, release_state(repo, env, dropped=dropped, debt=kept))
        output = release_tools(tmp_path, env, g)
        result = sprint(repo, env, "land")
        assert result.returncode == 0, result.stderr
        body = json.loads(output.read_text())["body"]
        assert "announces itself" in body and ref in body
        assert "separate design" in body and "silent corruption" in body
        if length:
            assert "markers/sprint/2.json" in body
            assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["debt"] == kept

    def test_capped_story_points_to_its_physical_report_round(self, tmp_path):
        import re

        from bookkeep import render_merge_body

        raw = report(
            dropped=[
                {"finding": "long finding " * 100, "reason": "loud cross-concern policy " * 100}
            ]
        ) | {"round_file": 8}
        source = tmp_path / "reports/story-007.round-8.json"
        source.parent.mkdir()
        source.write_text(json.dumps(raw))
        body = render_merge_body([raw], "story-007", [])
        pointers = re.findall(r"in full at ([^)]+)", body)
        assert pointers
        for pointer in pointers:
            target = tmp_path / pointer
            assert target.is_file(), pointer
            assert json.loads(target.read_text()) == raw
