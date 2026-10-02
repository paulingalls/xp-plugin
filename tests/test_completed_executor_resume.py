"""Completion credentials authorize reuse only on their bound implementation."""

import json

import pytest
from completed_executor_support import (
    amendment,
    completed,
    damage,
    git,
    replacement,
    rewrite_state,
    roles,
    state,
)
from plan_confirmation_support import events
from plan_review_install import installed_launch
from spawn_helpers import spawn


def test_completed_evidence_amendment_reuses_executor(tmp_path):
    repo, env, seen = completed(tmp_path)
    head, tree = git(tmp_path, "rev-parse", "HEAD"), git(tmp_path, "rev-parse", "HEAD^{tree}")
    amendment(tmp_path, repo, env)
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen) == [
        "planner",
        "plan-reviewer",
        "teammate",
        "reviewer",
        "plan-reviewer",
        "reviewer",
    ]
    assert git(tmp_path, "rev-parse", "HEAD") == head
    assert git(tmp_path, "rev-parse", "HEAD^{tree}") == tree
    assert state(tmp_path)["state"] == "FINISHED"


def test_tier_motion_cannot_mint_executor_completion(tmp_path):
    from completed_executor_support import consumer

    repo, env, _ = consumer(tmp_path, initial_status="clean", initial_question=None)
    (tmp_path / "executor-stop").unlink()
    config = repo / ".xp/config.yml"
    config.write_text(
        config.read_text().replace("story: true", "story: git commit --allow-empty -qm tier-motion")
    )
    import subprocess

    subprocess.run(
        ["git", "commit", "-am", "moving tier"], cwd=repo, env=env, check=True, capture_output=True
    )
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
    result = spawn(repo, env, "story-042")
    assert result.returncode != 0
    assert "completion" not in state(tmp_path)


def test_reuse_preserves_commit_attribution(tmp_path):
    repo, env, _ = completed(tmp_path)
    original = state(tmp_path)["completion"]
    commits = git(tmp_path, "log", "--format=%H", f"{original['start_head']}..HEAD")
    assert commits.splitlines() == [original["head"]]
    amendment(tmp_path, repo, env)
    assert spawn(repo, env, "resume", "story-042").returncode == 0
    assert state(tmp_path)["completion"] == original
    close = json.loads((tmp_path / "data/markers/story-042.close.json").read_text())
    assert close["rounds"][-1]["reviewed_head"] == original["head"]


def test_confirmed_plan_with_incomplete_implementation_runs_executor(tmp_path):
    repo, env, seen = completed(tmp_path, implementation="requires-execution")
    before = git(tmp_path, "rev-parse", "HEAD")
    assert "LEASE = 1" in (tmp_path / "data/worktrees/story-042/src/thing.py").read_text()
    (tmp_path / "value-change").touch()
    amendment(
        tmp_path,
        repo,
        env,
        change=lambda text: text.replace("Then Z", "Then lease is 17").replace(
            "Verify: true",
            'Verify: true && python3 -c "import runpy; '
            "assert runpy.run_path('src/thing.py')['LEASE'] == 17\"",
        ),
    )
    assert spawn(repo, env, "resume", "story-042").returncode == 0
    assert roles(seen).count("planner") == 1
    assert roles(seen).count("teammate") == 2
    assert git(tmp_path, "rev-parse", "HEAD") != before
    assert "LEASE = 17" in (tmp_path / "data/worktrees/story-042/src/thing.py").read_text()


@pytest.mark.parametrize("implementation", ["missing", None, "invalid", False, [], {}])
def test_missing_or_invalid_implementation_never_reuses(tmp_path, implementation):
    repo, env, seen = completed(tmp_path, implementation=implementation)
    if implementation == "missing":
        binary = tmp_path / "bin/claude"
        binary.write_text(binary.read_text().replace(", 'implementation': 'missing'", ""))
    amendment(tmp_path, repo, env)
    result = spawn(repo, env, "resume", "story-042")
    if implementation == "missing":
        assert result.returncode == 0, result.stderr
        assert roles(seen).count("teammate") == 2
    else:
        assert result.returncode != 0 and state(tmp_path)["state"] == "STOPPED"
        assert roles(seen).count("reviewer") == 1


@pytest.mark.parametrize(
    "kind",
    [
        "executor-failed",
        "tier-failed",
        "tier-skipped",
        "executor-absent",
        "missing-close-marker",
        "dirty",
        "staged",
        "untracked",
        "hidden",
        "ignored",
        "moved",
        "empty-commit",
        "absent",
        "empty",
        "shape",
        "version",
        "story_id",
        "repository",
        "head",
        "tree",
        "start_head",
        "card",
        "card-shape",
        "plan",
        "findings",
        "fingerprint",
        "credential",
        "acceptance",
        "review-evidence",
        "tier",
    ],
)
def test_completion_refusal_boundary(tmp_path, kind):
    repo, env, seen = completed(tmp_path)
    damage(tmp_path, kind)
    replacement(tmp_path)
    amendment(tmp_path, repo, env)
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen).count("teammate") == 2
    assert state(tmp_path)["state"] == "FINISHED"
    if kind in ("dirty", "staged", "hidden", "moved"):
        assert (
            "VALUE = 'changed'" in (tmp_path / "data/worktrees/story-042/src/thing.py").read_text()
        )
    if kind in ("untracked", "ignored"):
        assert (
            tmp_path / "data/worktrees/story-042/runtime.cfg"
        ).read_text() == "preserved runtime"


@pytest.mark.parametrize("kind", ["STOPPED", "FINISHED"])
def test_legacy_handback_runs_executor(tmp_path, kind):
    repo, env, seen = completed(tmp_path)
    rewrite_state(tmp_path, lambda value: (value.pop("completion"), value.update(state=kind)))
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen).count("teammate") == 2


def test_changed_gate_runs_on_candidate(tmp_path):
    repo, env, seen = completed(tmp_path)
    before = git(tmp_path, "rev-parse", "HEAD")
    amendment(
        tmp_path,
        repo,
        env,
        change=lambda text: text.replace(
            "Verify: true",
            'Verify: true && python3 -c "import sys; from pathlib import Path; '
            "sys.stderr.write('NEW-GATE-DIAGNOSTIC'); "
            "assert Path('src/required.py').exists()\"",
        ),
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0
    assert roles(seen).count("teammate") == 1
    assert roles(seen).count("reviewer") == 1
    assert git(tmp_path, "rev-parse", "HEAD") == before
    logs = list((tmp_path / "data/logs/verify").glob("*/*stderr*"))
    assert any("NEW-GATE-DIAGNOSTIC" in path.read_text() for path in logs)
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "os.makedirs('src', exist_ok=True)",
            "os.makedirs('src', exist_ok=True)\n open('src/required.py', 'w').write('repaired')",
        )
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen).count("teammate") == 2


@pytest.mark.parametrize("motion", ["tree", "completion", "card", "credential", "findings", "plan"])
def test_motion_invalidates_completed_confirmation(tmp_path, motion):
    repo, env, seen = completed(tmp_path)
    amendment(tmp_path, repo, env)
    target = {
        "tree": tmp_path / "data/worktrees/story-042/src/thing.py",
        "completion": tmp_path / "data/plans/story-042.handoff.json",
        "card": tmp_path / "data/plan.md",
        "credential": tmp_path / "data/markers/story-042.ready.json",
        "findings": tmp_path / "data/plans/story-042.round-1.md",
        "plan": tmp_path / "data/plans/story-042.plan.md",
    }[motion]
    binary = tmp_path / "bin/claude"
    injected = f"  open({str(target)!r}, 'a').write('motion')\n"
    if motion == "plan":
        injected = "  open(draft, 'a').write('authorized edit without a reason')\n"
    binary.write_text(
        binary.read_text().replace(" if confirming:\n", " if confirming:\n" + injected)
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0
    assert roles(seen).count("teammate") == 1
    assert roles(seen).count("reviewer") == 1


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_installed_completed_amendment_walk(tmp_path, harness):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch, harness)
    first_head = git(tmp_path, "rev-parse", "HEAD")
    amendment(tmp_path, repo, env, launch)
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert git(tmp_path, "rev-parse", "HEAD") == first_head
    assert roles(seen).count("teammate") == 1
    assert launch(repo, env, "resume", "story-042").returncode == 0
    assert roles(seen).count("teammate") == 1
    binary = tmp_path / "bin" / harness
    binary.write_text(
        binary.read_text().replace(
            "'implementation': 'complete'", "'implementation': 'requires-execution'"
        )
    )
    assert "LEASE = 1" in (tmp_path / "data/worktrees/story-042/src/thing.py").read_text()
    (tmp_path / "value-change").touch()
    amendment(
        tmp_path,
        repo,
        env,
        launch,
        lambda text: text.replace("Then Z", "Then lease is 17").replace(
            "Verify: true",
            'Verify: true && python3 -c "import runpy; '
            "assert runpy.run_path('src/thing.py')['LEASE'] == 17\"",
        ),
    )
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert git(tmp_path, "rev-parse", "HEAD") != first_head
    assert "LEASE = 17" in (tmp_path / "data/worktrees/story-042/src/thing.py").read_text()
    assert "cache/xp-plugin/fixture/scripts/spawn.py" in result.args[1]
    assert roles(seen).count("teammate") == 2
    assert roles(seen).count("planner") == 1
    assert roles(seen).count("reviewer") == 4
    confirmations = [event for event in events(seen) if event.get("kind") == "confirmation"]
    assert len(confirmations) == 2


def test_accepted_reviewer_edit_proceeds_once(tmp_path):
    repo, env, seen = completed(tmp_path)
    amendment(tmp_path, repo, env)
    binary = tmp_path / "bin/claude"
    reason = "Feedback checks the implemented source before reuse."
    edit = (
        "  candidate = re.search(r'^CARD_CANDIDATE_PATH: (.+)$', prompt, re.M).group(1)\n"
        "  candidate_text = open(candidate).read()\n"
        "  open(candidate, 'w').write(candidate_text.replace('Files: src/thing.py, src/other.py', "
        "'Files: src/thing.py, src/other.py, tests/probe.py'))\n"
        f"  open(draft, 'a').write('Reason: {reason}\\n')\n"
        f"  verdict['status'] = 'edited'; verdict['reasons'] = [{reason!r}]\n"
    )
    binary.write_text(
        binary.read_text().replace(
            "  if verdict['status'] != 'clean':", edit + "  if verdict['status'] != 'clean':"
        )
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen).count("planner") == roles(seen).count("teammate") == 1
    assert len([event for event in events(seen) if event.get("kind") == "confirmation"]) == 1
    assert "tests/probe.py" in events(seen)[-1]["prompt"]
    assert (
        state(tmp_path)["completion"]["plan"]
        != (tmp_path / "data/plans/story-042.plan.md").read_text()
    )


def test_reuse_keeps_review_and_post_review_verify(tmp_path):
    repo, env, seen = completed(tmp_path)
    gate = tmp_path / "gate.py"
    output = tmp_path / "gates.jsonl"
    gate.write_text(
        "import json, os, subprocess\n"
        f"with open({str(output)!r}, 'a') as out:\n"
        " out.write(json.dumps({'cwd': os.getcwd(), 'head': "
        "subprocess.check_output(['git', 'rev-parse', 'HEAD'], "
        "text=True).strip()}) + '\\n')\n"
    )
    amendment(
        tmp_path,
        repo,
        env,
        change=lambda text: text.replace("Verify: true", f"Verify: true && python3 {gate}"),
    )
    head = git(tmp_path, "rev-parse", "HEAD")
    assert spawn(repo, env, "resume", "story-042").returncode == 0
    observations = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(observations) == 2
    assert all(observation["head"] == head for observation in observations)
    assert roles(seen).count("teammate") == 1
    assert roles(seen).count("reviewer") == 2
    receipt = json.loads((tmp_path / "data/markers/story-042.verify.json").read_text())
    assert receipt["head"] == head


@pytest.mark.parametrize("failure", ["human", "blocking", "reviewer", "post-verify"])
def test_reuse_failures_keep_diagnostic_evidence(tmp_path, failure):
    repo, env, seen = completed(tmp_path)
    amendment(tmp_path, repo, env)
    binary = tmp_path / "bin/claude"
    text = binary.read_text()
    if failure == "human":
        text = text.replace(
            "'implementation': 'complete'",
            "'implementation': 'complete', 'human_question': 'Reserved value?' ",
        )
    elif failure == "blocking":
        text = text.replace('"blocking":[]', '"blocking":["Actual blocker"]')
    elif failure == "reviewer":
        text = text.replace("elif role == 'reviewer':", "elif role == 'reviewer':\n sys.exit(1)")
    else:
        trigger = tmp_path / "post-review-red"
        gate = tmp_path / "post.py"
        gate.write_text(
            "from pathlib import Path\n"
            f"assert not Path({str(trigger)!r}).exists(), 'POST-REVIEW-DIAGNOSTIC'\n"
        )
        amendment(
            tmp_path,
            repo,
            env,
            change=lambda card: card.replace("Verify: true", f"Verify: true && python3 {gate}"),
        )
        text = text.replace(
            "elif role == 'reviewer':",
            f"elif role == 'reviewer':\n open({str(trigger)!r}, 'w').write('review ran')",
        )
    binary.write_text(text)
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0
    assert state(tmp_path)["state"] == "STOPPED"
    assert roles(seen).count("teammate") == 1
    if failure == "blocking":
        result = spawn(repo, env, "resume", "story-042")
        assert result.returncode != 0
        assert roles(seen).count("teammate") == 2
    if failure == "post-verify":
        assert "POST-REVIEW-DIAGNOSTIC" in result.stderr
        assert list((tmp_path / "data/logs/verify").glob("*/*stderr*"))


FAULTS = [
    "executor-failed",
    "tier-failed",
    "story_id",
    "repository",
    "card",
    "credential",
    "plan",
    "findings",
    "review-evidence",
    "version",
    "forged-gate",
    "fingerprint",
    "empty-commit",
    "ignored",
    "assume-bound",
    "skip-bound",
    "missing-close-marker",
]


@pytest.mark.parametrize("kind", FAULTS)
def test_reuse_guard_detects_its_fault(tmp_path, kind):
    from completed_executor_support import refusal_fault

    def guarantee(directory, mutation=None):
        directory.mkdir()
        launch = installed_launch(directory, mutation, "scripts/spawn/completion.py")
        repo, env, seen = completed(directory, launch)
        damage(directory, kind)
        result = launch(repo, env, "resume", "story-042")
        assert result.returncode == 0, result.stderr
        return roles(seen).count("teammate"), result.stderr

    count, diagnostic = guarantee(tmp_path / "normal")
    assert count == 2
    harmful, _ = guarantee(tmp_path / "fault", refusal_fault(diagnostic))
    with pytest.raises(AssertionError):
        assert harmful == 2
    assert harmful == 1


def test_review_patch_does_not_advance_executor_completion(tmp_path):
    import difflib

    repo, env, seen = completed(tmp_path)
    original = state(tmp_path)["completion"]
    source = tmp_path / "data/worktrees/story-042/src/thing.py"
    before = source.read_text()
    patch = "diff --git a/src/thing.py b/src/thing.py\n" + "".join(
        difflib.unified_diff(
            before.splitlines(True),
            (before + "PATCHED = True\n").splitlines(True),
            "a/src/thing.py",
            "b/src/thing.py",
        )
    )
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "elif role == 'reviewer':",
            "elif role == 'reviewer':\n "
            "pth = re.search(r'^PATCH_PATH: (.+)$', prompt, re.M).group(1)\n "
            + f"open(pth, 'w').write({patch!r})",
        )
    )
    amendment(tmp_path, repo, env)
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen).count("teammate") == 1
    assert git(tmp_path, "rev-parse", "HEAD") != original["head"]
    assert state(tmp_path)["completion"] == original
    receipt = json.loads((tmp_path / "data/markers/story-042.verify.json").read_text())
    assert receipt["head"] == git(tmp_path, "rev-parse", "HEAD")
    assert "PATCHED = True" in source.read_text()
    binary.write_text(
        binary.read_text().replace(f"open(pth, 'w').write({patch!r})", "open(pth, 'w').write('')")
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen).count("teammate") == 2


@pytest.mark.parametrize("command", ["false", "EDIT-ME", "missing-tier-binary", "touch tier-dirt"])
def test_non_green_tier_cannot_publish_completion(tmp_path, command):
    from completed_executor_support import tier_consumer

    repo, env, _ = tier_consumer(tmp_path, command)
    result = spawn(repo, env, "story-042")
    assert "completion" not in state(tmp_path)
    assert result.returncode == (0 if command == "EDIT-ME" else 2)


def test_failed_successor_does_not_retain_completion(tmp_path):
    repo, env, seen = completed(tmp_path, implementation="requires-execution")
    amendment(tmp_path, repo, env)
    binary = tmp_path / "bin/claude"
    text = binary.read_text()
    binary.write_text(
        text.replace(
            "print(json.dumps({'type':'result'",
            "if role == 'teammate': sys.exit(1)\nprint(json.dumps({'type':'result'",
        )
    )
    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode != 0
    assert "completion" not in state(tmp_path)
    assert roles(seen).count("teammate") == 2
    binary.write_text(text)
    assert spawn(repo, env, "resume", "story-042").returncode == 0
    assert roles(seen).count("teammate") == 3


def test_hidden_uncommitted_executor_bytes_cannot_certify(tmp_path):
    from completed_executor_support import hidden_handback

    repo, env, _ = hidden_handback(tmp_path)
    result = spawn(repo, env, "story-042")
    assert (tmp_path / "data/worktrees/story-042").exists(), result.stderr
    assert "LEASE = 1" in git(tmp_path, "show", "HEAD:src/thing.py")
    assert "LEASE = 17" in (tmp_path / "data/worktrees/story-042/src/thing.py").read_text()
    assert result.returncode != 0
    assert "completion" not in state(tmp_path)
