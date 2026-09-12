import json
import subprocess
import sys

from spawn_helpers import SPAWN, make_repo, seed_refresh_receipt, spawn

CLEAN = {"fixed": [], "blocking": [], "noted": []}


def stub_stages(tmp_path, blocking_plan=False, blocking_diff=False, unreadable_plan=False):
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir(exist_ok=True)
    events = tmp_path / "events.jsonl"
    if unreadable_plan:
        findings = '```json\n{"status":\n```'  # a verdict the harness cannot READ
    elif blocking_plan:
        findings = json.dumps({"status": "blocked", "question": "choose"})
    else:
        findings = json.dumps({"status": "clean", "reasons": []})
    report = {"fixed": [], "blocking": ["cannot land"], "noted": []} if blocking_diff else CLEAN
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, re, subprocess, sys\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
        ' print(\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\'); sys.exit()\n'
        "prompt = sys.stdin.read(); role = os.environ['XP_ROLE']\n"
        f"events = {str(events)!r}\n"
        "with open(events, 'a') as f:\n"
        " f.write(json.dumps({'role': role, 'argv': sys.argv[1:], 'prompt': prompt}) + '\\n')\n"
        "if role == 'planner':\n"
        " p = re.search(r'^PLAN_PATH: (.+)$', prompt, re.M); assert p\n"
        " open(p.group(1).strip(), 'a').write('# execution plan\\nred then green\\n')\n"
        "elif role == 'plan-reviewer':\n"
        " p = re.search(r'^FINDINGS_PATH: (.+)$', prompt, re.M); assert p\n"
        f" open(p.group(1).strip(), 'w').write({findings!r})\n"
        "elif role == 'teammate':\n"
        " os.makedirs('src', exist_ok=True)\n"
        " open('src/thing.py', 'a').write('\\nDONE = True\\n')\n"
        " subprocess.run(['git', 'add', '-A'], check=True)\n"
        " subprocess.run(['git', 'commit', '-qm', 'executor work'], check=True)\n"
        "elif role == 'reviewer':\n"
        " p = re.search(r'^REPORT_PATH: (.+)$', prompt, re.M); assert p\n"
        f" report = {report!r}\n"
        " open(p.group(1).strip(), 'w').write(json.dumps(report))\n"
        "print(json.dumps({'type':'result','subtype':'success','result':'done'}))\n"
    )
    binary.chmod(0o755)
    return events


def event_roles(path):
    return [json.loads(line)["role"] for line in path.read_text().splitlines()]


def prompt_for(path, role):
    events = map(json.loads, path.read_text().splitlines())
    return next(e["prompt"] for e in events if e["role"] == role)


def model_of(event):
    return event["argv"][event["argv"].index("--model") + 1]


def spawn_amending_after_plan_review(repo, env):
    scripts = SPAWN.parent
    program = f"""
import os, subprocess, sys
from pathlib import Path
sys.path[:0] = [{str(scripts)!r}, {str(scripts / "spawn")!r}]
import plan_review
run_foreground = plan_review.run_foreground
def amend_after_review(*args):
    result = run_foreground(*args)
    if result[0] == 0:
        plan = Path(os.environ["XP_DATA"]) / "plan.md"
        plan.write_text(plan.read_text().replace("Then Z", "Then MID-REVIEW-AMENDMENT"))
        command = [{sys.executable!r}, {str(SPAWN)!r}, "amend", "story-042", "--reason", "late"]
        amended = subprocess.run(command, capture_output=True)
        assert amended.returncode == 0, amended.stdout + amended.stderr
    return result
plan_review.run_foreground = amend_after_review
import spawn
sys.argv = ["spawn.py", "story-042"]
raise SystemExit(spawn.main())
"""
    return subprocess.run(
        [sys.executable, "-c", program],
        cwd=repo,
        env=dict(env, XP_SPAWN_TEST="1"),
        capture_output=True,
        text=True,
    )


class TestSpawnStages:
    def test_each_story_launch_uses_its_own_configured_model(self, tmp_path):
        repo, env, g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        config = repo / ".xp/config.yml"
        config.write_text(
            "roles:\n"
            "  planner: claude/planner-only\n"
            "  executor: claude/executor-only\n"
            "  reviewer: claude/reviewer-only\n"
            "  plan-reviewer: claude/plan-reviewer-only\n"
            "tests:\n  story: true\n"
        )
        assert g("commit", "-aqm", "distinct role models").returncode == 0
        assert g("branch", "-f", "main", "HEAD").returncode == 0
        events = stub_stages(tmp_path)
        result = spawn(repo, env, "story-042")
        assert result.returncode == 0, result.stderr
        assert {
            event["role"]: model_of(event)
            for event in map(json.loads, events.read_text().splitlines())
        } == {
            "planner": "planner-only",
            "plan-reviewer": "plan-reviewer-only",
            "teammate": "executor-only",
            "reviewer": "reviewer-only",
        }

    def test_multifile_runs_the_four_roles_in_order_and_records_the_close_round(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        events = stub_stages(tmp_path)
        result = spawn(repo, env, "story-042")
        assert result.returncode == 0, result.stderr
        assert event_roles(events) == ["planner", "plan-reviewer", "teammate", "reviewer"]
        logs = tmp_path / "data/logs"
        assert {path.name for path in logs.glob("story-042*.log")} == {
            "story-042-planner.log",
            "story-042-plan-reviewer.log",
            "story-042-executor.log",
            "story-042-reviewer.log",
        }
        handoff = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
        assert handoff["stages"] == {
            "planner": "ran",
            "plan-reviewer": "ran",
            "executor": "ran",
            "reviewer": "ran",
        }
        close = json.loads((tmp_path / "data/markers/story-042.close.json").read_text())
        assert close["shown_sha"] == close["reviewed_head"]
        assert "planner=ran · plan-reviewer=ran · executor=ran · reviewer=ran" in result.stdout

    def test_the_plan_review_is_spawns_own_and_the_executor_launches_none(self, tmp_path):
        """AC2, and the ONLY thing that separates this card from the defect it names:
        the stage running is not the property — the property is that it ran here,
        and that no brief hands an agent a review to wait on across a turn."""
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        events = stub_stages(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        detached = tmp_path / "data/logs/story-042-plan-review.log"
        assert not detached.exists(), f"the plan review was detached: {detached} is its log"
        for role in ("planner", "teammate"):
            brief = prompt_for(events, role)
            assert "plan_review.py" not in brief, f"the {role} brief hands it a review to launch"

    def test_a_config_predating_roles_planner_still_stages_one(self, tmp_path):
        """A deliberately constructed legacy config has no planner seat; refusing
        it would strand existing multi-file projects."""
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        cfg = repo / ".xp/config.yml"
        cfg.write_text(cfg.read_text().replace("  planner: claude/haiku/low\n", ""))
        subprocess.run(["git", "commit", "-aqm", "older config"], cwd=repo, env=env, check=True)
        events = stub_stages(tmp_path)
        result = spawn(repo, env, "story-042")
        assert result.returncode == 0, result.stderr
        assert event_roles(events) == ["planner", "plan-reviewer", "teammate", "reviewer"]
        planner = next(json.loads(ln) for ln in events.read_text().splitlines())
        assert "sonnet" in " ".join(planner["argv"]), "the fallback is roles.executor, not reviewer"

    def test_a_malformed_planner_refuses_before_any_stage_launch(self, tmp_path):
        repo, env, g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        config = repo / ".xp/config.yml"
        config.write_text(
            config.read_text().replace("planner: claude/haiku/low", "planner: claude")
        )
        assert g("commit", "-aqm", "malformed planner").returncode == 0
        events = stub_stages(tmp_path)
        result = spawn(repo, env, "story-042")
        assert result.returncode == 2
        assert "roles.planner" in result.stderr and "planner: claude/sonnet/medium" in result.stderr
        assert not events.exists(), "an agent launched before the malformed role was refused"

    def test_a_card_planner_override_beats_the_new_project_default(self, tmp_path):
        repo, env, g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        config = repo / ".xp/config.yml"
        config.write_text(
            config.read_text()
            .replace("claude/haiku/low", "claude/project-planner")
            .replace("claude/sonnet/medium", "claude/project-executor")
            .replace("  reviewer: claude/opus\n", "  reviewer: claude/project-reviewer\n")
        )
        plan = tmp_path / "data/plan.md"
        plan.write_text(
            plan.read_text().replace("Executor:", "Planner: claude/card-planner\nExecutor:")
        )
        seed_refresh_receipt(repo, env)
        amended = spawn(repo, env, "amend", "story-042", "--reason", "exercise planner override")
        assert amended.returncode == 0, amended.stderr
        assert g("commit", "-aqm", "distinct project roles").returncode == 0
        assert g("branch", "-f", "main", "HEAD").returncode == 0
        events = stub_stages(tmp_path)
        result = spawn(repo, env, "story-042")
        assert result.returncode == 0, result.stderr
        models = {
            event["role"]: model_of(event)
            for event in map(json.loads, events.read_text().splitlines())
        }
        assert models["planner"] == "card-planner"
        assert models["teammate"] == "project-executor"
        assert models["reviewer"] == "project-reviewer"

    def test_single_file_distinguishes_skipped_planning_from_ran_stages(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        events = stub_stages(tmp_path)
        result = spawn(repo, env, "story-042")
        assert result.returncode == 0, result.stderr
        assert event_roles(events) == ["teammate", "reviewer"]
        state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
        assert state["stages"] == {
            "planner": "skipped",
            "plan-reviewer": "skipped",
            "executor": "ran",
            "reviewer": "ran",
        }
        assert "planner=skipped" in result.stdout, result.stdout

    def test_a_blocking_plan_stops_before_executor(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        events = stub_stages(tmp_path, blocking_plan=True)
        result = spawn(repo, env, "story-042")
        assert result.returncode != 0
        assert event_roles(events) == ["planner", "plan-reviewer"]
        # A human-only question is the plan review WORKING. Reporting it as a death
        # is this card's own context — "a correct refusal naming the wrong cause" —
        # and it is what sends the lead to the harness log instead of the question.
        assert "DIED" not in result.stderr, result.stderr
        assert "blocked for the human: choose" in result.stderr, result.stderr
        # Was "planner=ran and no plan-reviewer entry: the stage that stopped is the
        # one the line OMITS". That made absence carry the meaning, which is
        # constraint 15 and the release blocker this now fixes: a plan review that
        # blocked read identically to one that never ran, and resume therefore
        # skipped replanning and re-reviewed the same draft forever.
        assert "stages: planner=ran · plan-reviewer=blocked" in result.stdout, result.stdout

    def test_a_stop_before_any_stage_says_none_reached_rather_than_nothing(self, tmp_path):
        """Constraint 15 the other way: no stages line at all is how "the executor
        never got a reviewed plan" reads exactly like "the run was fine"."""
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        binary = tmp_path / "bin" / "claude"
        stub_stages(tmp_path)
        binary.write_text(binary.read_text().replace("if role == 'planner':", "if False:"))
        result = spawn(repo, env, "story-042")
        assert result.returncode != 0
        assert "stages: none reached" in result.stdout, result.stdout

    def test_resume_refuses_a_marker_whose_stage_state_is_not_ran_or_skipped(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        stub_stages(tmp_path, blocking_plan=True)
        assert spawn(repo, env, "story-042").returncode != 0
        marker = tmp_path / "data/plans/story-042.handoff.json"
        state = json.loads(marker.read_text())
        state["stages"]["planner"] = "half"
        marker.write_text(json.dumps(state))
        result = spawn(repo, env, "resume", "story-042")
        assert result.returncode == 2, result.stderr
        assert "invalid stage state" in result.stderr, result.stderr

    def test_blocking_diff_review_is_a_stopped_not_finished_handback(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        events = stub_stages(tmp_path, blocking_diff=True)
        result = spawn(repo, env, "story-042")
        assert result.returncode != 0
        assert event_roles(events) == ["teammate", "reviewer"]
        state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
        assert state["state"] == "STOPPED" and state["stages"]["reviewer"] == "ran"

    def test_a_blocked_plan_review_replans_on_resume_instead_of_re_reviewing(self, tmp_path):
        """Release blocker found by story-102's round-2 reviewer. `planner` is marked
        "ran" BEFORE the plan review runs, so a block leaves it set and every resume
        skips replanning and re-reviews the IDENTICAL draft — blocking again, forever.
        Constructs the stall rather than observing it: the same stub blocks both times,
        so a green here means the planner was re-run and the draft is new."""
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        events = stub_stages(tmp_path, blocking_plan=True)
        stopped = spawn(repo, env, "story-042")
        assert stopped.returncode != 0, stopped.stdout
        handoff = tmp_path / "data/plans/story-042.handoff.json"
        state = json.loads(handoff.read_text())
        assert state["stages"]["plan-reviewer"] == "blocked", (
            "a plan review that blocked is recorded the same way as one that never ran"
        )
        assert "blocked" in state["why"] and "failed" not in state["why"], state["why"]
        handoff.write_text(json.dumps({**json.loads(handoff.read_text()), "state": "STOPPED"}))
        spawn(repo, env, "resume", "story-042")
        assert event_roles(events).count("planner") == 2, (
            "resume re-reviewed the same draft instead of replanning: " + str(event_roles(events))
        )
        assert event_roles(events).count("plan-reviewer") == 2, (
            "resume skipped review after replanning: " + str(event_roles(events))
        )

    def test_an_unreadable_plan_review_reuses_the_draft_on_resume(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        events = stub_stages(tmp_path, unreadable_plan=True)
        stopped = spawn(repo, env, "story-042")
        assert stopped.returncode != 0, stopped.stdout + stopped.stderr
        handoff = tmp_path / "data/plans/story-042.handoff.json"
        state = json.loads(handoff.read_text())
        assert state["stages"]["plan-reviewer"] == "failed"
        # inheritance() hands the successor `why` and never `stages`, so the two
        # states have to stay apart THERE too (constraint 15).
        assert "failed" in state["why"] and "blocked" not in state["why"], state["why"]
        draft = tmp_path / "data/plans/story-042.plan.md"
        first_draft = draft.read_bytes()
        state["state"] = "STOPPED"
        handoff.write_text(json.dumps(state))

        stub_stages(tmp_path)
        resumed = spawn(repo, env, "resume", "story-042")
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert event_roles(events).count("planner") == 1
        assert event_roles(events).count("plan-reviewer") == 2
        assert draft.read_bytes() == first_draft

    def test_amendments_replan_the_current_card_once_before_the_executor(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        events = stub_stages(tmp_path, blocking_diff=True)
        assert spawn(repo, env, "story-042").returncode != 0

        handoff = tmp_path / "data/plans/story-042.handoff.json"
        legacy = json.loads(handoff.read_text())
        legacy.pop("plan_reviewed_card")
        handoff.write_text(json.dumps(legacy))
        seen = len(event_roles(events))
        assert spawn(repo, env, "resume", "story-042").returncode != 0
        assert event_roles(events)[seen:] == ["teammate", "reviewer"]

        plan = tmp_path / "data/plan.md"
        plan.write_text(plan.read_text().replace("Then Z", "Then FIRST-AMENDMENT"))
        assert spawn(repo, env, "amend", "story-042", "--reason", "first change").returncode == 0
        plan.write_text(plan.read_text().replace("FIRST-AMENDMENT", "FINAL-AMENDMENT"))
        assert spawn(repo, env, "amend", "story-042", "--reason", "second change").returncode == 0

        seen = len(event_roles(events))
        assert spawn(repo, env, "resume", "story-042").returncode != 0
        resumed = [json.loads(line) for line in events.read_text().splitlines()[seen:]]
        assert [event["role"] for event in resumed] == [
            "planner",
            "plan-reviewer",
            "teammate",
            "reviewer",
        ]
        assert "Then FINAL-AMENDMENT" in resumed[1]["prompt"]

        seen += len(resumed)
        assert spawn(repo, env, "resume", "story-042").returncode != 0
        assert event_roles(events)[seen:] == ["teammate", "reviewer"]
        assert event_roles(events).count("planner") == 2
        assert event_roles(events).count("plan-reviewer") == 2

        plan.write_text(plan.read_text().replace("FINAL-AMENDMENT", "LATER-AMENDMENT"))
        assert spawn(repo, env, "amend", "story-042", "--reason", "later change").returncode == 0
        seen = len(event_roles(events))
        assert spawn(repo, env, "resume", "story-042").returncode != 0
        assert event_roles(events)[seen:] == ["planner", "plan-reviewer", "teammate", "reviewer"]

    def test_an_amendment_before_the_review_is_recorded_replans_on_resume(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        events = stub_stages(tmp_path, blocking_diff=True)
        assert spawn_amending_after_plan_review(repo, env).returncode != 0
        seen = len(event_roles(events))
        assert spawn(repo, env, "resume", "story-042").returncode != 0
        assert event_roles(events)[seen:][:2] == ["planner", "plan-reviewer"]

    def test_an_amended_single_file_resume_keeps_both_plan_stages_skipped(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        events = stub_stages(tmp_path, blocking_diff=True)
        assert spawn(repo, env, "story-042").returncode != 0
        plan = tmp_path / "data/plan.md"
        plan.write_text(plan.read_text().replace("Then Z", "Then AMENDED"))
        amended = spawn(repo, env, "amend", "story-042", "--reason", "single-file change")
        assert amended.returncode == 0
        seen = len(event_roles(events))
        assert spawn(repo, env, "resume", "story-042").returncode != 0
        assert event_roles(events)[seen:] == ["teammate", "reviewer"]
        state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
        assert state["stages"]["planner"] == "skipped"
        assert state["stages"]["plan-reviewer"] == "skipped"

    def test_an_amendment_before_the_first_spawn_plans_once(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        plan = tmp_path / "data/plan.md"
        plan.write_text(plan.read_text().replace("Then Z", "Then AMENDED"))
        amended = spawn(repo, env, "amend", "story-042", "--reason", "pre-spawn change")
        assert amended.returncode == 0
        events = stub_stages(tmp_path, blocking_diff=True)
        assert spawn(repo, env, "story-042").returncode != 0
        assert spawn(repo, env, "resume", "story-042").returncode != 0
        assert event_roles(events).count("planner") == 1
        assert event_roles(events).count("plan-reviewer") == 1
