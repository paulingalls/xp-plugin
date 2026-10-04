"""Preview and execution select the same stage without changing evidence."""

import json

import pytest
from completed_executor_support import completed, roles
from plan_confirmation_support import events
from plan_review_install import installed_launch
from resume_preview_support import snapshot


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("invalidated", [False, True])
def test_completed_executor_preview_matches_live_resume(tmp_path, harness, invalidated):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch, harness=harness)
    if invalidated:
        tree = tmp_path / "data/worktrees/story-042"
        (tree / "src/thing.py").write_text("DONE = False\n")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    before = snapshot(tmp_path)
    count = len(events(seen))
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    assert snapshot(tmp_path) == before
    expected = "executor" if invalidated else "reviewer"
    assert f"Next stage: {expected}." in preview.stdout
    live = launch(repo, env, "resume", "story-042")
    assert live.returncode == 0, live.stderr
    assert roles(seen)[count:] == (["teammate", "reviewer"] if invalidated else [])


@pytest.mark.parametrize("damage", ["binding", "result", "evidence", "version", "repository"])
def test_invalid_checkpoint_preview_and_live_refuse_without_launch(tmp_path, damage):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    marker = tmp_path / "data/plans/story-042.handoff.json"
    state = json.loads(marker.read_text())
    if damage == "binding":
        state["checkpoint"]["story_id"] = "story-999"
    elif damage == "version":
        state["checkpoint"]["version"] = 1
    elif damage == "repository":
        state["checkpoint"]["repository"] = str(tmp_path / "another-project")
    elif damage == "result":
        state["checkpoint"]["results"]["executor"]["result"] = "imagined-success"
    else:
        state["checkpoint"]["results"]["executor"].pop("output")
    marker.write_text(json.dumps(state))
    saved = marker.read_bytes()
    count = len(events(seen))
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    live = launch(repo, env, "resume", "story-042")
    assert preview.returncode == live.returncode == 2
    assert len(events(seen)) == count
    assert marker.read_bytes() == saved
    assert "checkpoint" in preview.stderr and "checkpoint" in live.stderr
