"""Resume previews follow completion reuse without performing its gates."""

import pytest
from completed_executor_support import completed, damage, roles
from plan_confirmation_support import events
from plan_review_install import installed_launch
from resume_preview_support import snapshot


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("invalidated", [False, True])
def test_completed_executor_preview_matches_live_resume(tmp_path, harness, invalidated):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch, harness=harness)
    if invalidated:
        damage(tmp_path, "absent")
    before = snapshot(tmp_path)
    count = len(events(seen))
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    assert snapshot(tmp_path) == before
    if invalidated:
        assert "## Current plan review" in preview.stdout
    else:
        assert "executor: reuse" in preview.stdout
        assert "independent diff review" in preview.stdout
        assert "## Current plan review" not in preview.stdout
    live = launch(repo, env, "resume", "story-042")
    assert live.returncode == 0, live.stderr
    added = roles(seen)[count:]
    assert added == (["teammate", "reviewer"] if invalidated else ["reviewer"])


@pytest.mark.meta
def test_completed_preview_selection_fault(tmp_path):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    target = tmp_path / "cache/xp-plugin/fixture/scripts/spawn/execution.py"
    source = target.read_text()
    anchor = "            if reusable:"
    assert anchor in source
    target.write_text(source.replace(anchor, "            if False:"))
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    with pytest.raises(AssertionError):
        assert "executor: reuse" in preview.stdout
    count = len(events(seen))
    assert launch(repo, env, "resume", "story-042").returncode == 0
    assert roles(seen)[count:] == ["reviewer"]


@pytest.mark.parametrize("writer", [False, pytest.param(True, marks=pytest.mark.meta)])
def test_completed_preview_leaves_changed_gates_pending(tmp_path, writer):
    from completed_executor_support import amendment

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    observations = tmp_path / "gate-runs"
    gate = tmp_path / "gate.py"
    gate.write_text(f"with open({str(observations)!r}, 'a') as out: out.write('ran\\n')\n")
    amendment(
        tmp_path,
        repo,
        env,
        launch,
        change=lambda text: text.replace("Verify: true", f"Verify: true && python3 {gate}"),
    )
    target = tmp_path / "cache/xp-plugin/fixture/scripts/spawn/execution.py"
    source = target.read_text()
    anchor = "    if resuming:\n        from ready import credential"
    assert anchor in source
    target.write_text(source.replace(anchor, '    return stop("pause before reuse", 0)\n' + anchor))
    stopped = launch(repo, env, "resume", "story-042")
    assert stopped.returncode != 0 and "pause before reuse" in stopped.stderr
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    target.write_text(source)
    if writer:
        assert "card, preview=True" in source
        target.write_text(source.replace("card, preview=True", "card, preview=False"))
    before = snapshot(tmp_path)
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    if writer:
        assert observations.read_text().splitlines() == ["ran"]
        with pytest.raises(AssertionError):
            assert snapshot(tmp_path) == before
        return
    assert "changed Verify must pass" in preview.stdout
    assert snapshot(tmp_path) == before
    count = len(events(seen))
    live = launch(repo, env, "resume", "story-042")
    assert live.returncode == 0, live.stderr
    assert observations.read_text().splitlines() == ["ran", "ran"]
    assert roles(seen)[count:] == ["reviewer"]


@pytest.mark.parametrize("mutant", [False, pytest.param(True, marks=pytest.mark.meta)])
def test_integrated_preview_preserves_candidate_binding(tmp_path, mutant):
    import json
    from pathlib import Path

    from resume_preview_support import assert_refusal, preview_fixture

    repo, env, seen, launch = preview_fixture(tmp_path)
    receipt = tmp_path / "data/plans/story-042.round-1.acceptance.json"
    accepted = json.loads(receipt.read_text())
    Path(accepted["candidate"]).write_text("different candidate")
    if mutant:
        target = tmp_path / "cache/xp-plugin/fixture/scripts/spawn/execution.py"
        source = target.read_text()
        anchor = '            prior_binding(accepted, Path(accepted["plan"]))'
        assert anchor in source
        target.write_text(source.replace(anchor, "            pass"))
    before = events(seen)
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    live = launch(repo, env, "resume", "story-042")
    if mutant:
        assert preview.returncode == live.returncode == 0, (preview.stderr, live.stderr)
        with pytest.raises(AssertionError):
            assert_refusal(preview, live, seen, before)
    else:
        assert_refusal(preview, live, seen, before)
