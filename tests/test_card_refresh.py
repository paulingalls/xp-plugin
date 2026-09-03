"""Card refresh rewrites one card's stale claims against HEAD before `ready`
mints its digest, and refuses every motion outside that card.

Extracted from test_slate_review_prose.py at the Sprint-17 close (constraint 8:
525 lines against the 500 cap). Same helpers, same fixtures — the seam is the
artifact under test, refresh here and the slate review there.
"""

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from close import story_card
from slate_review_helpers import (
    PLUGIN,
    card_refresh,
    receipt_of,
    refresh_repo,
    stub_card_refresher,
)
from spawn_helpers import spawn
from work import card_digest

CORRECTED = "Context: demo, and src/thing.py is 12 lines at HEAD, not 40."
HANDOFF_DIRECT = f"""
import sys
sys.path[:0] = [{str(PLUGIN / "scripts")!r}, {str(PLUGIN / "scripts" / "spawn")!r}]
from pathlib import Path
import slate_review
from work import chdir_repo_root
chdir_repo_root()
sys.exit(slate_review._refresh_handoff(sys.argv[1], Path("absent.md")))
"""


def git_out(repo, env, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True
    ).stdout.strip()


def test_card_refresh_rewrites_the_card_and_ready_digests_the_rewrite(tmp_path):
    """AC1 walked end to end. The receipt must pin the card as REWRITTEN: taken
    before the edit it matches nothing the lead will ever spawn, and `ready`
    would then refuse the very card the refresh had just corrected."""
    repo, env, _g, plan = refresh_repo(tmp_path)
    launch = stub_card_refresher(tmp_path, correction=CORRECTED)
    stale = story_card(plan.read_text(), "story-042")[0]

    result = card_refresh(repo, env)
    assert result.returncode == 0, result.stdout + result.stderr

    prompt = json.loads(launch.read_text())["prompt"]
    assert "You are not a review" in prompt
    assert f"PLAN_PATH: {plan.resolve()}" in prompt
    assert "story-042 — demo story" in prompt and "story-043" not in prompt
    assert "# XP Values" in prompt and "# Judgment" in prompt
    assert "CONSTRAINT-SENTINEL" in prompt and "Worktree bootstrap" in prompt

    fresh = story_card(plan.read_text(), "story-042")[0]
    assert CORRECTED in fresh and "Context: demo." not in fresh
    receipt = json.loads(receipt_of(env).read_text())
    assert receipt["digest"] == card_digest(fresh)
    assert receipt["digest"] != card_digest(stale), "the receipt pinned the pre-refresh card"
    assert receipt["changed"] is True
    assert receipt["head"] == git_out(repo, env, "rev-parse", "HEAD")

    minted = spawn(repo, env, "ready", "story-042")
    assert minted.returncode == 0, minted.stderr
    assert receipt["digest"] in minted.stdout, "ready digested text the refresh never saw"


def test_a_refresh_that_finds_nothing_stale_still_records_that_it_ran(tmp_path):
    """AC5, constraint 15: "ran and found the card correct" and "never ran" are
    two states, and the lead reads them off ONE surface — stdout — because the
    runner is detached, so the child's own print lands in the child's log."""
    repo, env, _g, plan = refresh_repo(tmp_path)
    before = plan.read_text()
    stub_card_refresher(tmp_path, findings="nothing stale\n")
    result = card_refresh(repo, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert plan.read_text() == before
    assert json.loads(receipt_of(env).read_text())["changed"] is False
    assert "already correct" in result.stdout and "CHANGED" not in result.stdout
    assert str(receipt_of(env)) in result.stdout
    assert spawn(repo, env, "ready", "story-042").returncode == 0

    # the same tree with the receipt taken away is the OTHER state, and neither
    # leg may spell the two the same way
    receipt_of(env).unlink()
    plan.write_text(before.replace("[ready]", "[planned]"))
    never = spawn(repo, env, "ready", "story-042")
    assert never.returncode == 2 and "no card refresh has run" in never.stderr


def test_a_refresh_whose_receipt_never_landed_refuses_instead_of_claiming_success(tmp_path):
    """The one state the detached child can leave that LOOKS like success: the
    incomplete marker cleared and no receipt written. Without the refusal the
    lead is told the refresh ran and `ready` then says none has."""
    repo, env, _g, _plan = refresh_repo(tmp_path)
    stub_card_refresher(tmp_path, correction=CORRECTED)
    assert card_refresh(repo, env).returncode == 0
    direct = lambda: subprocess.run(  # noqa: E731
        [sys.executable, "-c", HANDOFF_DIRECT, "story-042"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert direct().returncode == 0, "the fixture no longer reaches the success arm"
    receipt_of(env).unlink()
    refused = direct()
    assert refused.returncode == 2, refused.stdout
    assert "recorded no receipt" in refused.stderr, refused.stderr
    receipt_of(env).write_text("{}")  # present but carrying no verdict
    assert direct().returncode == 2


@pytest.mark.parametrize(
    ("knob", "expected"),
    [
        ({"sibling": True}, "outside its own card"),
        ({"status": "ready"}, "never its lifecycle state"),
    ],
)
def test_a_refresher_that_moves_anything_but_its_own_card_is_refused(tmp_path, knob, expected):
    """AC6. The plan lives OUTSIDE the repo, so tree_state sees neither motion —
    story-091's guard for the slate reviewer does not reach a single card."""
    repo, env, _g, plan = refresh_repo(tmp_path)
    original = plan.read_text()
    stub_card_refresher(tmp_path, correction=CORRECTED, **knob)
    result = card_refresh(repo, env)
    assert result.returncode == 2, result.stdout
    assert expected in result.stdout + result.stderr
    assert "outside the repo" in result.stderr and "no git diff" in result.stderr
    # Own card restored; motion OUTSIDE it is left and named instead of reverted.
    # Reverting it silently destroys a concurrent lane's write in the same window —
    # the Sprint-17 sprint-review blocking finding, and bug 5a1abadb's race.
    card_now, _ = story_card(plan.read_text(), "story-042")
    card_was, _ = story_card(original, "story-042")
    assert card_now == card_was, "the refused refresh left its own card corrupted"
    if knob.get("sibling"):
        assert "changed too" in result.stderr, "unattributable motion was left but not named"
    else:
        assert plan.read_text() == original
    assert not receipt_of(env).exists(), "a refused refresh must not mint a receipt"
    assert spawn(repo, env, "ready", "story-042").returncode == 2


def test_a_story_id_cannot_escape_the_refresh_data_root(tmp_path):
    repo, env, _g, plan = refresh_repo(tmp_path)
    hostile = "../../victim/target"
    plan.write_text(plan.read_text().replace("story-042", hostile, 1))
    result = card_refresh(repo, env, hostile)
    assert result.returncode == 2 and "safe story id" in result.stderr
    assert not (tmp_path / "victim").exists(), "the refresh wrote outside XP_DATA"

    import ready

    quoted = "story-'quoted"
    command = ready.refresh_instruction(quoted).removeprefix("Run `").removesuffix("`.")
    assert shlex.split(command)[-2:] == [quoted, "--refresh"]


def test_a_refresher_that_writes_in_the_repository_is_refused(tmp_path):
    repo, env, _g, _plan = refresh_repo(tmp_path)
    stub_card_refresher(tmp_path, correction=CORRECTED, repo_file=str(repo / "stray.py"))
    result = card_refresh(repo, env)
    assert result.returncode == 2, result.stdout
    assert "changed the repository" in result.stdout + result.stderr
    assert not receipt_of(env).exists()


def test_the_refresh_is_never_called_a_review_on_any_surface_it_names(tmp_path, monkeypatch):
    """Its own module says refresh's state, log and print text must never say the
    word, and no assertion on printed text reaches the LOG FILE NAME, which the
    shared lifecycle derived as `<id>-refresh-review.log`. All three kinds here,
    because the fix has to leave the two names every note and marker cites."""
    import slate_review as runner

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))

    class Launched:
        pid = 4321

        def poll(self):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen", lambda argv, **kw: Launched())
    logs = {}
    for identifier, kind in (("7", "slate"), ("story-042", "plan"), ("story-042", "refresh")):
        runner._detach(identifier, kind, tmp_path / "f.md", ["slate_review.py", identifier])
        logs[kind] = Path(json.loads(runner.review_marker(identifier, kind).read_text())["log"])
    assert logs["slate"].name == "7-slate-review.log"
    assert logs["plan"].name == "story-042-plan-review.log"
    assert logs["refresh"].name == "story-042-card-refresh.log"
    assert "review" not in logs["refresh"].name
    assert "CARD REFRESH DID NOT COMPLETE" in runner._marker_state("story-042", "refresh")["state"]
    quoted = "story-'quoted"
    runner._detach(quoted, "refresh", tmp_path / "f.md", ["slate_review.py", quoted, "--refresh"])
    action = runner._marker_state(quoted, "refresh")["next"].removeprefix("run ")
    assert shlex.split(action.split(" again", 1)[0]) == [
        "python3",
        "slate_review.py",
        quoted,
        "--refresh",
    ]


class TestRefreshRestoreIsCardScoped:
    """Sprint-17 sprint-review blocking finding. plan.md is PROJECT-GLOBAL and the
    refresher runs detached for minutes; a rejection that rewrites the whole
    pre-run snapshot silently reverts whatever another lane wrote in that window.
    Bug 5a1abadb measured this concurrency; plan_review.py was fixed to TOLERATE
    it, and this path was overwriting it under a refusal that blames the refresher
    and says no git diff will show the edit."""

    def test_a_rejection_restores_the_card_and_not_a_concurrent_lanes_write(self, tmp_path):
        """CONSTRUCTS the race rather than observing it: the stub edits story-043
        DURING its run — the same window another lane writes in, and indistinguishable
        from it at the seam — while tripping the status guard on its own card. The
        refusal must still fire, story-042 must be restored, and story-043's text
        must survive. Whole-file restore fails the third assertion."""
        from slate_review_helpers import card_refresh, refresh_repo, stub_card_refresher

        repo, env, _g, plan = refresh_repo(tmp_path)
        stub_card_refresher(tmp_path, status="in-progress", sibling=True)
        result = card_refresh(repo, env)
        assert result.returncode != 0, result.stdout
        assert "[in-progress]" not in plan.read_text(), "story-042's status was not restored"
        assert "MEDDLED" in plan.read_text(), (
            "the rejection reverted a write it did not make and cannot see: "
            "plan.md is project-global and this restore is not scoped to its own card"
        )
