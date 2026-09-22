"""Local card refresh when a newly declared path has no code at HEAD."""

import json

from close import story_card
from slate_review_helpers import card_refresh, receipt_of, refresh_repo, stub_card_refresher
from spawn_helpers import spawn
from work import card_digest


def test_new_absent_declared_path_remints_without_agent(tmp_path):
    repo, env, _g, plan = refresh_repo(tmp_path)
    launch = stub_card_refresher(tmp_path, findings="nothing stale\n")
    assert card_refresh(repo, env).returncode == 0
    plan.write_text(
        plan.read_text().replace("Files: src/thing.py", "Files: src/thing.py, src/new.py")
    )
    launch.unlink()

    reminted = card_refresh(repo, env)

    receipt = json.loads(receipt_of(env).read_text())
    card = story_card(plan.read_text(), "story-042")[0]
    assert reminted.returncode == 0, reminted.stderr
    assert not launch.exists()
    assert receipt["files"] == {"src/thing.py": None, "src/new.py": None}
    assert receipt["digest"] == card_digest(card)
    assert "spawn.py ready story-042" in reminted.stdout
    assert spawn(repo, env, "ready", "story-042").returncode == 0


def test_local_remint_preserves_the_head_that_was_read(tmp_path):
    repo, env, g, plan = refresh_repo(tmp_path)
    launch = stub_card_refresher(tmp_path, findings="nothing stale\n")
    assert card_refresh(repo, env).returncode == 0
    original_head = json.loads(receipt_of(env).read_text())["head"]
    (repo / "unrelated.md").write_text("new unrelated code\n")
    assert g("add", "unrelated.md").returncode == 0
    assert g("commit", "-qm", "unrelated path").returncode == 0
    current_head = g("rev-parse", "HEAD").stdout.strip()
    assert current_head != original_head
    plan.write_text(plan.read_text().replace("Context: demo.", "Context: lead correction."))
    launch.unlink()

    reminted = card_refresh(repo, env)

    receipt = json.loads(receipt_of(env).read_text())
    assert reminted.returncode == 0, reminted.stderr
    assert not launch.exists()
    assert receipt["head"] == original_head
    assert receipt["digest"] == card_digest(story_card(plan.read_text(), "story-042")[0])
