import json

import pytest
from spawn_helpers import make_repo, spawn
from spawn_stages_support import stub_stages
from test_card_update_contract import CHANGES, REASON, edited_stages


def test_failed_planned_launch_can_amend_captured_card(tmp_path):
    repo, env, _ = make_repo(tmp_path, status="planned", files="src/thing.py, src/other.py")
    first = spawn(repo, env, "story-042")
    assert first.returncode == 2 and "not on PATH" in first.stderr
    marker = tmp_path / "data/markers/story-042.ready.json"
    before = marker.read_bytes()
    card = tmp_path / "data/plan.md"
    assert "[planned]" in card.read_text()
    card.write_text(
        card.read_text().replace(
            "Context: demo.", "Context: demo.\nDecision: lead changes the reserved choice."
        )
    )
    events = stub_stages(tmp_path)
    refused = spawn(repo, env, "story-042")
    assert refused.returncode == 2 and "amend" in refused.stderr
    assert marker.read_bytes() == before
    amended = spawn(repo, env, "amend", "story-042", "--reason", "lead changes reserved choice")
    assert amended.returncode == 0, amended.stderr
    assert "[planned]" in card.read_text()
    launched = spawn(repo, env, "story-042")
    assert launched.returncode == 0, launched.stdout + launched.stderr
    stages = [json.loads(line) for line in events.read_text().splitlines()]
    assert [stage["role"] for stage in stages] == [
        "planner",
        "plan-reviewer",
        "teammate",
        "reviewer",
    ]
    assert "Decision: lead changes the reserved choice." in stages[0]["prompt"]


def test_planned_multifile_launch_uses_current_source(tmp_path):
    repo, env, git = make_repo(tmp_path, status="planned", files="src/thing.py, src/other.py")
    (repo / "src").mkdir()
    (repo / "src/thing.py").write_text('STORAGE = "local"\n')
    git("add", "-A")
    git("commit", "-qm", "actual source")
    git("checkout", "main")
    git("merge", "elsewhere")
    card = tmp_path / "data/plan.md"
    card.write_text(card.read_text().replace("Context: demo.", "Context: storage is remote."))
    events = stub_stages(tmp_path)
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            " open(p.group(1).strip(), 'a').write('# execution plan\\nred then green\\n')",
            " source = open('src/thing.py').read()\n"
            " open(p.group(1).strip(), 'w').write('# current implementation\\n' + source)",
        )
    )
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stdout + result.stderr
    stages = [json.loads(line) for line in events.read_text().splitlines()]
    assert [s["role"] for s in stages] == ["planner", "plan-reviewer", "teammate", "reviewer"]
    assert 'STORAGE = "local"' in (tmp_path / "data/plans/story-042.plan.md").read_text()
    assert str(tmp_path / "data/plans/story-042.plan.md") in stages[2]["prompt"]
    assert not (tmp_path / "data/card-refreshes").exists()


@pytest.mark.parametrize("status", ["clean", "edited"])
@pytest.mark.parametrize("motion", [False, True])
def test_reviewed_edits_reach_executor_once(tmp_path, status, motion):
    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    changes = [CHANGES["ac"], CHANGES["single"]] if motion else []
    events = edited_stages(tmp_path, changes)
    binary = tmp_path / "bin/claude"
    text = binary.read_text().replace('"status": "edited"', f'"status": "{status}"')
    text = text.replace(
        f" with open(p.group(1), 'a') as f: f.write({REASON!r} + '\\n')",
        " with open(p.group(1), 'a') as f: f.write('Use the measured declaration.\\n')"
        if motion
        else "",
    )
    binary.write_text(text)
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stdout + result.stderr
    stages = [json.loads(line) for line in events.read_text().splitlines()]
    assert [s["role"] for s in stages] == ["planner", "plan-reviewer", "teammate", "reviewer"]
    for _, new in changes:
        assert new in stages[2]["prompt"]
    assert REASON not in (tmp_path / "data/plans/story-042.plan.md").read_text()
    findings = json.loads((tmp_path / "data/plans/story-042.round-1.md").read_text())
    assert REASON in findings["reasons"]


@pytest.mark.parametrize("missing_baseline", [False, True])
def test_active_run_cannot_reset_approved_card(tmp_path, missing_baseline):
    repo, env, _ = make_repo(tmp_path, status="planned", files="src/thing.py, src/other.py")
    seen = stub_stages(tmp_path, blocking_diff=True)
    assert spawn(repo, env, "story-042").returncode != 0
    marker = tmp_path / "data/markers/story-042.ready.json"
    before = marker.read_bytes()
    if missing_baseline:
        marker.unlink()
    card = tmp_path / "data/plan.md"
    card.write_text(card.read_text().replace("[in-progress]", "[planned]"))
    for args in [("ready", "story-042"), ("story-042",)]:
        result = spawn(repo, env, *args)
        assert result.returncode == 2
        assert "already spawned" in result.stderr or "resume" in result.stderr
        if missing_baseline:
            assert not marker.exists()
        else:
            assert marker.read_bytes() == before
    assert [json.loads(line)["role"] for line in seen.read_text().splitlines()] == [
        "planner",
        "plan-reviewer",
        "teammate",
        "reviewer",
    ]


@pytest.mark.parametrize(
    "fault", ["missing", "unreadable", "malformed", "empty", "ambiguous", "stale"]
)
def test_missing_or_unreadable_verdict_never_launches_executor(tmp_path, fault):
    from test_card_update_contract import spawn_with_hook

    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = edited_stages(tmp_path, [CHANGES["ac"]])
    code = f"""
original = plan_review.run_foreground
def damage(*args):
    result = original(*args)
    record = plan_acceptance.latest(args[0])
    path = Path(record['findings'])
    body = path.read_text()
    fault = {fault!r}
    if fault == 'missing': path.unlink()
    elif fault == 'unreadable': path.unlink(); path.mkdir()
    elif fault == 'malformed': path.write_text('{{')
    elif fault == 'empty': path.write_text('')
    elif fault == 'ambiguous': path.write_text(body + '\\n' + body)
    else: path.write_text(body.replace('REVIEWED', 'old') + 'stale round')
    return result
plan_review.run_foreground = damage
"""
    result = spawn_with_hook(repo, env, code)
    assert result.returncode != 0, result.stdout + result.stderr
    assert [json.loads(line)["role"] for line in events.read_text().splitlines()] == [
        "planner",
        "plan-reviewer",
    ]


def test_execution_notes_remain_visible_without_amendment(tmp_path):
    repo, env, _ = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = edited_stages(tmp_path, [CHANGES["ac"]])
    binary = tmp_path / "bin/claude"
    text = binary.read_text().replace(
        "'result':'done'", "'result':'ordinary implementation observation'"
    )
    text = text.replace(
        "elif role == 'reviewer':\n",
        "elif role == 'reviewer':\n"
        " p = re.search(r'^EXECUTOR_LOG: (.+)$', prompt, re.M); assert p\n"
        " notes = open(p.group(1)).read()\n"
        " assert 'ordinary implementation observation' in notes\n"
        f" open({str(tmp_path / 'observed-notes')!r}, 'w').write(notes)\n",
    )
    binary.write_text(text)
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ordinary implementation observation" in (tmp_path / "observed-notes").read_text()
    credential = json.loads((tmp_path / "data/markers/story-042.ready.json").read_text())
    assert not credential.get("amendments")
    assert [json.loads(line)["role"] for line in events.read_text().splitlines()].count(
        "plan-reviewer"
    ) == 1
