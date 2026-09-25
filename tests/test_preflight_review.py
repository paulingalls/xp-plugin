"""Preflight refusal precedes reviewer launch and recovery writes."""

import json
import subprocess

import pytest
from close_free_card_cases import carded_review
from close_helpers import close, free, launches, make_repo, marker_file, stub_reviewer
from test_close_repair import BROKEN_PATCH
from test_close_salvage import KILLED, dying_reviewer


def configure(repo, g):
    script = repo / "check-env"
    script.write_text(
        '#!/bin/sh\nif [ "${NEEDED_FOR_VERIFY:-}" != ready ]; then '
        'echo "missing NEEDED_FOR_VERIFY"; exit 7; fi\n'
    )
    script.chmod(0o755)
    config = repo / ".xp/config.yml"
    config.write_text("preflight: ./check-env\n" + config.read_text())
    assert g("add", "check-env", ".xp/config.yml").returncode == 0
    assert g("commit", "-qm", "check environment").returncode == 0


def assert_red(result):
    assert result.returncode == 2, result.stdout + result.stderr
    assert "missing NEEDED_FOR_VERIFY" in result.stdout
    assert result.stderr.splitlines()[-1].startswith("refused: preflight")


@pytest.mark.parametrize("noun", ["story", "free"])
def test_review_refuses_before_reviewer_and_preserves_artifacts(tmp_path, noun):
    if noun == "story":
        verify_ran = tmp_path / "verify-ran"
        gate = tmp_path / "verify-gate"
        gate.write_text(f"#!/bin/sh\ntouch {verify_ran}\n")
        gate.chmod(0o755)
        repo, env, g = make_repo(tmp_path, verify=str(gate))

        def run(environment, *args):
            return close(repo, environment, "review", *args)

        key = "story-042"
    else:
        repo, env, _g, _branch, key = carded_review(tmp_path)

        def g(*args):
            return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True)

        def run(environment, *args):
            return free(repo, environment, "fix-typo", "review", *args)

    configure(repo, g)
    stub_reviewer(tmp_path)
    marker = marker_file(tmp_path, key)
    marker.parent.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_bytes(b'{"rounds": []}')
    before = marker.read_bytes()
    receipt = tmp_path / "data/markers" / f"{key}.verify.json"
    receipt_before = receipt.read_bytes() if receipt.exists() else None
    round_n = len(json.loads(before)["rounds"]) + 1
    report = tmp_path / "data/reports" / f"{key}.round-{round_n}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(b"old report")
    assert_red(run(env))
    assert marker.read_bytes() == before
    assert (receipt.read_bytes() if receipt.exists() else None) == receipt_before
    if noun == "story":
        assert not verify_ran.exists()
    assert report.read_bytes() == b"old report"
    assert not (tmp_path / "data/markers" / f"{key}.review-launch").exists()
    expected_launches = 0 if noun == "story" else 1
    assert len(launches(tmp_path)) == expected_launches
    assert run(env | {"NEEDED_FOR_VERIFY": "ready"}).returncode == 0
    assert len(launches(tmp_path)) == expected_launches + 1
    if noun == "story":
        assert verify_ran.exists()


def test_salvage_red_keeps_set_aside_launch(tmp_path):
    repo, env, g = make_repo(tmp_path)
    configure(repo, g)
    stub_reviewer(tmp_path, exit_code=1)
    assert close(repo, env | {"NEEDED_FOR_VERIFY": "ready"}, "review").returncode == 2
    stub_reviewer(tmp_path)
    assert close(repo, env | {"NEEDED_FOR_VERIFY": "ready"}, "review").returncode == 0
    launch = tmp_path / "data/markers/story-042.round-2.launch"
    before = launch.read_bytes()
    marker = marker_file(tmp_path)
    state = marker.read_bytes() if marker.exists() else None
    assert_red(close(repo, env, "salvage"))
    assert launch.read_bytes() == before
    assert (marker.read_bytes() if marker.exists() else None) == state
    rescued = close(repo, env | {"NEEDED_FOR_VERIFY": "ready"}, "salvage")
    assert rescued.returncode == 0, rescued.stdout + rescued.stderr
    assert len(json.loads(marker.read_text())["rounds"]) == 2


def test_repair_red_keeps_verify_red_launch(tmp_path):
    gate = tmp_path / "verify-gate"
    gate.write_text("#!/bin/sh\nexit 1\n")
    gate.chmod(0o755)
    repo, env, g = make_repo(tmp_path, verify=str(gate))
    configure(repo, g)
    stub_reviewer(tmp_path, patch=BROKEN_PATCH)
    assert close(repo, env | {"NEEDED_FOR_VERIFY": "ready"}, "review").returncode == 2
    launch = tmp_path / "data/markers/story-042.review-launch"
    before = launch.read_bytes()
    gate.write_text("#!/bin/sh\ntouch '" + str(tmp_path / "verify-ran") + "'\nexit 0\n")
    assert_red(close(repo, env, "repair"))
    assert launch.read_bytes() == before
    assert not (tmp_path / "verify-ran").exists()
    (repo / "src/thing.py").write_text("A = 2\nbroken = True\n")
    assert g("commit", "-qam", "repair reviewed file").returncode == 0
    repaired = close(repo, env | {"NEEDED_FOR_VERIFY": "ready"}, "repair")
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert (tmp_path / "verify-ran").exists()


@pytest.mark.parametrize("leg", ["review", "salvage", "repair"])
def test_green_preflight_that_edits_tree_refuses_before_work(tmp_path, leg):
    gate = tmp_path / "verify-gate"
    gate.write_text("#!/bin/sh\nexit 1\n")
    gate.chmod(0o755)
    repo, env, g = make_repo(tmp_path, verify=str(gate) if leg == "repair" else "true")
    configure(repo, g)
    stub_reviewer(tmp_path, patch=BROKEN_PATCH if leg == "repair" else "")
    if leg == "repair":
        assert close(repo, env | {"NEEDED_FOR_VERIFY": "ready"}, "review").returncode == 2
    elif leg == "salvage":
        assert close(repo, env | {"NEEDED_FOR_VERIFY": "ready"}, "review").returncode == 0
        (tmp_path / "data/markers/story-042.review-launch").write_text("queued")
    script = repo / "check-env"
    script.write_text("#!/bin/sh\nprintf 'edit\\n' >> src/thing.py\n")
    assert g("commit", "-qam", "mutating preflight").returncode == 0
    marker = marker_file(tmp_path)
    before = marker.read_bytes() if marker.exists() else None
    launch = tmp_path / "data/markers/story-042.review-launch"
    launch_before = launch.read_bytes() if launch.exists() else None
    count = len(launches(tmp_path))
    result = close(repo, env, leg)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "preflight left the working tree dirty" in result.stderr
    assert (marker.read_bytes() if marker.exists() else None) == before
    assert (launch.read_bytes() if launch.exists() else None) == launch_before
    assert len(launches(tmp_path)) == count


def test_review_dry_run_previews_preflight_without_running(tmp_path):
    repo, env, g = make_repo(tmp_path)
    configure(repo, g)
    preview = close(repo, env, "review", "--dry-run")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert "would run preflight: ./check-env" in preview.stdout
    assert "missing NEEDED_FOR_VERIFY" not in preview.stdout
    assert launches(tmp_path) == []
    assert not (tmp_path / "data/markers/story-042.review-launch").exists()


def test_spawn_review_refusal_is_a_stop_not_harness_death(tmp_path):
    from spawn_helpers import make_repo as spawn_repo
    from spawn_helpers import spawn
    from test_spawn_stages import event_roles, stub_stages

    repo, env, g = spawn_repo(tmp_path, files="src/thing.py, src/other.py")
    assert g("checkout", "-q", "main").returncode == 0
    configure(repo, g)
    assert g("checkout", "-q", "elsewhere").returncode == 0
    events = stub_stages(tmp_path)
    stopped = spawn(repo, env, "story-042")
    handoff = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
    assert stopped.returncode == 2, stopped.stdout + stopped.stderr
    assert handoff["state"] == "STOPPED"
    assert "preflight" in handoff["why"]
    assert "DIED" not in stopped.stdout + stopped.stderr
    assert event_roles(events) == ["planner", "plan-reviewer", "teammate"]
    tree = tmp_path / "data/worktrees/story-042"
    assert close(tree, env | {"NEEDED_FOR_VERIFY": "ready"}, "review").returncode == 0
    assert event_roles(events)[-1] == "reviewer"


def test_salvage_preserves_preexisting_dirty_tree_diagnosis(tmp_path):
    repo, env, g = make_repo(tmp_path)
    configure(repo, g)
    dying_reviewer(tmp_path)
    assert close(repo, env | KILLED | {"NEEDED_FOR_VERIFY": "ready"}, "review").returncode == 2
    (repo / "dead-reviewer-work.py").write_text("uninspected = True\n")
    result = close(repo, env | {"NEEDED_FOR_VERIFY": "ready"}, "salvage")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "preflight left the working tree dirty" not in result.stderr
    assert "dead reviewer's uninspected work" in result.stderr


def test_salvage_dry_run_validates_and_previews_without_running(tmp_path):
    repo, env, g = make_repo(tmp_path)
    configure(repo, g)
    preview = close(repo, env, "salvage", "--dry-run")
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert "would run preflight: ./check-env" in preview.stdout
    assert "missing NEEDED_FOR_VERIFY" not in preview.stdout
    config = repo / ".xp/config.yml"
    config.write_text(config.read_text().replace("./check-env", "echo nope | cat", 1))
    assert g("commit", "-qam", "malformed preflight").returncode == 0
    refused = close(repo, env, "salvage", "--dry-run")
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert refused.stderr.splitlines()[-1].startswith("refused: preflight")
