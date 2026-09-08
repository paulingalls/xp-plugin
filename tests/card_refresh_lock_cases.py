"""Locked card-refresh cases collected through test_card_refresh.py."""

import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
from close import story_card
from slate_review_helpers import (
    PLUGIN,
    SLATE_REVIEW,
    card_refresh,
    receipt_of,
    refresh_repo,
    stub_card_refresher,
)
from spawn_helpers import spawn
from work import card_digest

CORRECTED = "Context: demo, and src/thing.py is 12 lines at HEAD, not 40."
SCRIPTS = PLUGIN / "scripts"
HOLDER = """
import pathlib, sys, time
sys.path.insert(0, {scripts!r})
from work import edit_plan
acquired, release = map(pathlib.Path, sys.argv[1:])
def mutate(text):
    acquired.write_text("held")
    while not release.exists(): time.sleep(0.01)
    return text.replace("Context: untouched", "Context: HOLDER-WRITE", 1)
edit_plan(mutate)
"""
FLIP_HOLDER = """
import pathlib, sys, time
sys.path.insert(0, {scripts!r})
from work import edit_plan, flip_status
acquired, release = map(pathlib.Path, sys.argv[1:])
def mutate(text):
    acquired.write_text("held")
    while not release.exists(): time.sleep(0.01)
    return flip_status(text, "#### story-043 ", "planned", "ready")
edit_plan(mutate)
"""


def await_path(path, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"event was never written: {path}")


def await_log_state(path, choices, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = path.read_text(errors="replace") if path.exists() else ""
        if found := next((choice for choice in choices if choice in text), ""):
            return found
        time.sleep(0.01)
    raise AssertionError(f"log recorded none of {choices}: {path}")


def refresh_process(repo, env):
    return subprocess.Popen(
        [sys.executable, str(SLATE_REVIEW), "story-042", "--refresh"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_a_locked_sibling_flip_and_refresher_correction_both_survive(tmp_path):
    repo, env, _g, plan = refresh_repo(tmp_path)
    read, release = tmp_path / "read", tmp_path / "release"
    stub_card_refresher(
        tmp_path,
        correction=CORRECTED,
        read_event=str(read),
        release_event=str(release),
    )
    refresh = refresh_process(repo, env)
    await_path(read)
    held, flip_release = tmp_path / "flip-held", tmp_path / "flip-release"
    flip = subprocess.Popen(
        [
            sys.executable,
            "-c",
            FLIP_HOLDER.format(scripts=str(SCRIPTS)),
            held,
            flip_release,
        ],
        cwd=repo,
        env=env,
    )
    await_path(held)
    release.write_text("apply")
    time.sleep(0.1)
    assert refresh.poll() is None, "the helper never contended with the locked flip"
    flip_release.write_text("flip")
    out, err = refresh.communicate(timeout=30)
    assert flip.wait(30) == 0, "the same-run locked control never flipped"
    assert refresh.returncode == 0, out + err
    assert "changed too" not in out + err, "a lane's locked flip was reported as outside motion"
    final = plan.read_text()
    assert CORRECTED in story_card(final, "story-042")[0]
    assert story_card(final, "story-043")[1] == "ready"


def test_card_restore_waits_for_the_plan_lock_and_preserves_the_holder_write(tmp_path):
    repo, env, _g, plan = refresh_repo(tmp_path)
    agent_read, agent_release = tmp_path / "agent-read", tmp_path / "agent-release"
    lock_acquired, lock_release = tmp_path / "lock-acquired", tmp_path / "lock-release"
    stub_card_refresher(
        tmp_path,
        correction=CORRECTED,
        direct_plan=True,
        read_event=str(agent_read),
        release_event=str(agent_release),
    )
    refresh = refresh_process(repo, env)
    await_path(agent_read)
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER.format(scripts=str(SCRIPTS)), lock_acquired, lock_release],
        cwd=repo,
        env=env,
    )
    await_path(lock_acquired)
    agent_release.write_text("done")
    marker = Path(env["XP_DATA"]) / "markers/story-042.card-refresh-incomplete"
    log = Path(json.loads(marker.read_text())["log"])
    state = await_log_state(log, ("plan lock held", "Restored the card"))
    assert state == "plan lock held", "restore bypassed the live plan lock"
    lock_release.write_text("done")
    out, err = refresh.communicate(timeout=30)
    assert holder.wait(30) == 0 and refresh.returncode == 2, out + err
    final = plan.read_text()
    assert CORRECTED not in story_card(final, "story-042")[0]
    assert "HOLDER-WRITE" in story_card(final, "story-043")[0]


def test_a_helper_refusal_names_a_refresh_retry_that_succeeds(tmp_path):
    repo, env, _g, plan = refresh_repo(tmp_path)
    card, status = story_card(plan.read_text(), "story-042")
    candidate = tmp_path / "candidate.md"
    candidate.write_text(card.replace("[planned]", "[done]"))
    refused = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "work.py"),
            "edit-card",
            "story-042",
            "--digest",
            card_digest(card),
            "--status",
            status,
            str(candidate.resolve()),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 2
    assert "card refresh story-042" in refused.stderr
    command = re.search(r"Run `([^`]+)`\.", refused.stderr).group(1)
    stub_card_refresher(tmp_path, correction=CORRECTED)
    retried = subprocess.run(
        shlex.split(command), cwd=repo, env=env, capture_output=True, text=True, timeout=30
    )
    assert retried.returncode == 0, retried.stdout + retried.stderr
    assert json.loads(receipt_of(env).read_text())["changed"] is True
    assert spawn(repo, env, "ready", "story-042").returncode == 0


def test_a_refresher_that_writes_the_plan_instead_of_its_candidate_is_refused(tmp_path):
    repo, env, _g, _plan = refresh_repo(tmp_path)
    stub_card_refresher(tmp_path, correction=CORRECTED, direct_plan=True)
    result = card_refresh(repo, env)
    assert result.returncode == 2
    assert "wrote plan.md directly" in result.stderr and "--refresh" in result.stderr, (
        result.stdout + result.stderr
    )
    assert not receipt_of(env).exists()
    assert spawn(repo, env, "ready", "story-042").returncode == 2


def test_unattributable_sibling_motion_is_reported_without_blocking_the_refresh(tmp_path):
    repo, env, _g, plan = refresh_repo(tmp_path)
    stub_card_refresher(tmp_path, correction=CORRECTED, sibling=True)
    result = card_refresh(repo, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "changed too" in result.stdout + result.stderr
    assert CORRECTED in story_card(plan.read_text(), "story-042")[0]
    assert "MEDDLED" in story_card(plan.read_text(), "story-043")[0]


@pytest.mark.parametrize(
    ("knob", "expected"),
    [
        ({"skip_apply": True}, "did not apply it"),
        ({"extra_card": "#### story-099 — squatter   [planned]\nContext: x\n"}, "unparsable"),
    ],
)
def test_a_candidate_that_never_reaches_the_plan_is_refused(tmp_path, knob, expected):
    """The two ways the handoff breaks without either side erroring: the refresher
    edits its card and forgets PLAN_EDIT_COMMAND, or submits text the locked helper
    refuses. Both leave plan and receipt agreeing that no refresh ran."""
    repo, env, _g, plan = refresh_repo(tmp_path)
    before = plan.read_text()
    stub_card_refresher(tmp_path, correction=CORRECTED, **knob)
    result = card_refresh(repo, env)
    said = result.stdout + result.stderr
    assert result.returncode == 2, said
    assert expected in said and "--refresh" in said, said
    assert plan.read_text() == before
    assert not receipt_of(env).exists()
    assert spawn(repo, env, "ready", "story-042").returncode == 2
