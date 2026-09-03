import json
import subprocess

from spawn_helpers import make_repo, spawn

CLEAN = {"fixed": [], "blocking": [], "noted": []}


def stub_stages(tmp_path, blocking_plan=False, blocking_diff=False):
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir(exist_ok=True)
    events = tmp_path / "events.jsonl"
    plan = (
        {"status": "blocked", "question": "choose"}
        if blocking_plan
        else {
            "status": "clean",
            "reasons": [],
        }
    )
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
        " open(p.group(1).strip(), 'w').write('# execution plan\\nred then green\\n')\n"
        "elif role == 'plan-reviewer':\n"
        " p = re.search(r'^FINDINGS_PATH: (.+)$', prompt, re.M); assert p\n"
        f" open(p.group(1).strip(), 'w').write({json.dumps(plan)!r})\n"
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


class TestSpawnStages:
    def test_multifile_runs_the_four_roles_in_order_and_records_the_close_round(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        events = stub_stages(tmp_path)
        result = spawn(repo, env, "story-042")
        assert result.returncode == 0, result.stderr
        assert event_roles(events) == ["planner", "plan-reviewer", "teammate", "reviewer"]
        handoff = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
        assert handoff["stages"] == {
            "planner": "ran",
            "plan-reviewer": "ran",
            "executor": "ran",
            "reviewer": "ran",
        }
        close = json.loads((tmp_path / "data/markers/story-042.close.json").read_text())
        assert close["shown_sha"] == close["reviewed_head"]

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
        """No config we have shipped carries roles.planner — the scaffold's does
        not — so a refusal there strands every multi-file card in every existing
        project, which is the one path the field report came from."""
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

    def test_a_blocking_plan_stops_before_executor(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
        events = stub_stages(tmp_path, blocking_plan=True)
        result = spawn(repo, env, "story-042")
        assert result.returncode != 0
        assert event_roles(events) == ["planner", "plan-reviewer"]

    def test_blocking_diff_review_is_a_stopped_not_finished_handback(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        events = stub_stages(tmp_path, blocking_diff=True)
        result = spawn(repo, env, "story-042")
        assert result.returncode != 0
        assert event_roles(events) == ["teammate", "reviewer"]
        state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
        assert state["state"] == "STOPPED" and state["stages"]["reviewer"] == "ran"
