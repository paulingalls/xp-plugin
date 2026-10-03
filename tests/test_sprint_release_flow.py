"""Integration review hands one committed correction back to the lead."""

import json

import pytest
from sprint_helpers import (
    bundles,
    head,
    launches,
    make_repo,
    marker_path,
    sprint,
    staged_stub,
)


def test_clean_integration_skips_fixer_and_closer(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    staged_stub(tmp_path)
    before = head(repo, env)

    result = sprint(repo, env, "review")

    assert result.returncode == 0, result.stderr
    assert not bundles(tmp_path, "fix") and not bundles(tmp_path, "close")
    assert head(repo, env) == before
    assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["blocking"] == []


def test_remaining_integration_problem_returns_to_lead_without_relaunch(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    staged_stub(
        tmp_path,
        find={"blocking": ["candidate"]},
        verify={
            "actionable": [],
            "blocking": ["reserved release choice"],
        },
    )

    result = sprint(repo, env, "review")

    assert result.returncode == 2, result.stdout
    assert "lead" in result.stderr
    assert not bundles(tmp_path, "fix") and not bundles(tmp_path, "close")
    count = len(launches(tmp_path))
    retry = sprint(repo, env, "review")
    assert retry.returncode == 2
    assert len(launches(tmp_path)) == count
    assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["blocking"] == [
        "reserved release choice"
    ] * len(bundles(tmp_path, "verify"))


def test_integration_fix_commits_once_and_gets_narrow_close(tmp_path):
    repo, env, g = make_repo(tmp_path)
    events = tmp_path / "hook-events"
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text(f"#!/bin/sh\necho commit >> '{events}'\n")
    hook.chmod(0o755)
    before = head(repo, env)
    staged_stub(
        tmp_path,
        patches=[("fix", "src.py", "C = 3")],
        find={"blocking": ["missing C"]},
        verify={"actionable": ["missing C"], "blocking": []},
        fix={"blocking": [], "fixed": ["missing C"]},
    )

    result = sprint(repo, env, "review")

    assert result.returncode == 0, result.stderr
    assert events.read_text().splitlines() == ["commit"]
    assert len(bundles(tmp_path, "fix")) == len(bundles(tmp_path, "close")) == 1
    assert g("rev-list", "--count", f"{before}..HEAD").stdout.strip() == "1"
    closing = bundles(tmp_path, "close")[0]
    assert f"{before}..{head(repo, env)}" in closing and "missing C" in closing


def test_close_presents_delivered_scope_and_current_obligations(tmp_path):
    from sprint_helpers import PLAN, work

    plan = PLAN.replace(
        "#### story-043", "#### story-044 — unused   [retired]\nVerify: true\n#### story-043"
    )
    repo, env, _g = make_repo(tmp_path, plan=plan)
    root = tmp_path / "data"
    merge = head(repo, env)
    (root / "closes.jsonl").write_text(
        json.dumps(
            {
                "story": "story-042",
                "merge_sha": merge,
                "title": "done thing",
                "rounds": [],
            }
        )
        + "\n"
    )
    assert (
        work(
            repo, env, "debt", "--claim", "current debt", "--falsifier", "true", "--files", "src.py"
        ).returncode
        == 0
    )
    assert work(repo, env, "note", "current discovery").returncode == 0
    staged_stub(tmp_path)

    result = sprint(repo, env, "review")

    assert result.returncode == 0, result.stderr
    body = bundles(tmp_path, "find")[0]
    assert f"delivered at {merge}" in body
    assert "story-044 — unused — retired" in body
    assert "story-043 — also done — missing close evidence" in body
    assert "current debt" in body
    assert "story-099" not in body


def test_post_merge_validates_actual_shipping_tree(tmp_path):
    from sprint_helpers import CONFIG, record_reviews

    events = tmp_path / "tier-events"
    config = CONFIG.replace("full: true", f"full: git rev-parse HEAD^{{tree}} >> '{events}'")
    repo, env, g = make_repo(tmp_path, config=config)
    record_reviews(tmp_path, repo, env)
    g("checkout", "-q", "main")
    assert g("merge", "--no-ff", "sprint-002", "-m", "merge release").returncode == 0
    (repo / "src.py").write_text("ACTUAL_MERGED_TREE = 1\n")
    assert g("commit", "-qam", "trunk correction").returncode == 0
    shipping = g("rev-parse", "HEAD^{tree}").stdout.strip()

    result = sprint(repo, env, "post-merge")

    assert result.returncode == 0, result.stderr
    assert events.read_text().splitlines() == [shipping]
    state = json.loads(marker_path(tmp_path).read_text())
    assert state["full_tier"]["tree"] == shipping
    assert (tmp_path / "data/releases/sprint-2.json").is_file()


def test_prepared_pr_is_not_a_released_sprint(tmp_path):
    from test_sprint_tier_receipt import add_origin

    repo, env, g = make_repo(tmp_path)
    add_origin(tmp_path, repo, env, g)
    (tmp_path / "data/closes.jsonl").write_text("")
    staged_stub(tmp_path)
    assert sprint(repo, env, "review").returncode == 0
    gh = tmp_path / "bin/gh"
    event = tmp_path / "pr-created"
    gh.write_text(f"#!/bin/sh\necho pr > '{event}'\necho https://example.test/pr/1\n")
    gh.chmod(0o755)
    prepared = sprint(repo, env, "land")
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr

    assert event.exists()
    locator = json.loads(marker_path(tmp_path).read_text())["prepared_pr"]
    assert locator["url"] == "https://example.test/pr/1"
    assert locator["head"] == head(repo, env)
    assert locator["tree"] == g("rev-parse", "HEAD^{tree}").stdout.strip()
    assert not (tmp_path / "data/releases/sprint-2.json").exists()
    assert (tmp_path / "data/sprint_branch").exists()
    assert not g("tag", "--list", "v0.3.0").stdout
    g("checkout", "-q", "main")
    before = marker_path(tmp_path).read_bytes()
    refused = sprint(repo, env, "post-merge")
    assert refused.returncode == 2 and "merged" in refused.stderr
    assert marker_path(tmp_path).read_bytes() == before
    assert not g("tag", "--list", "v0.3.0").stdout
    assert g("merge", "--no-ff", "sprint-002", "-m", "actual merge").returncode == 0
    assert sprint(repo, env, "post-merge").returncode == 0
    assert (tmp_path / "data/releases/sprint-2.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        "equal-tree",
        "changed-tree",
        "changed-command",
        "changed-legs",
        "missing",
        "unreadable",
        "latest-failure",
    ],
)
def test_shipping_receipt_reuse_requires_matching_tree_and_commands(tmp_path, change):
    from sprint_helpers import CONFIG, record_reviews

    events = tmp_path / "tier-events"
    command = f"git rev-parse HEAD^{{tree}} >> '{events}'"
    repo, env, g = make_repo(tmp_path, config=CONFIG.replace("full: true", f"full: {command}"))
    record_reviews(tmp_path, repo, env)
    assert sprint(repo, env, "land").returncode == 2
    assert events.is_file()
    state = json.loads(marker_path(tmp_path).read_text())
    measured_head = state["full_tier"]["head"]
    if change == "missing":
        state.pop("full_tier")
    elif change == "unreadable":
        state["full_tier"] = "corrupt receipt"
    elif change == "latest-failure":
        state["full_tier_history"].append(dict(state["full_tier_history"][-1], outcome="failed"))
    marker_path(tmp_path).write_text(json.dumps(state))
    g("checkout", "-q", "main")
    assert g("merge", "--no-ff", "sprint-002", "-m", "merged release").returncode == 0
    assert head(repo, env) != measured_head
    if change == "changed-tree":
        (repo / "src.py").write_text("CHANGED_SHIPPING_TREE = 1\n")
        assert g("commit", "-qam", "trunk correction").returncode == 0
    elif change in ("changed-command", "changed-legs"):
        config = repo / ".xp/config.yml"
        config.write_text(config.read_text().replace(command, command + " && true"))
        if change == "changed-legs":
            config.write_text(
                config.read_text() + f"full_legs:\n  checks: {command}\n  final: true\n"
            )
        assert g("commit", "-qam", "new shipping command").returncode == 0

    result = sprint(repo, env, "post-merge")

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(events.read_text().splitlines()) == (1 if change == "equal-tree" else 2)
    assert events.read_text().splitlines()[-1] == g("rev-parse", "HEAD^{tree}").stdout.strip()
    assert json.loads(marker_path(tmp_path).read_text())["full_tier"]["reused"] == (
        change == "equal-tree"
    )


def _concurrent_publication(tmp_path, close=None):
    import subprocess
    import sys
    import time

    from sprint_helpers import CLOSE, CONFIG, record_reviews

    ready, proceed = tmp_path / "ready", tmp_path / "proceed"
    lifecycle = tmp_path / "lifecycle.py"
    lifecycle.write_text(
        "import pathlib, time\n"
        f"pathlib.Path({str(ready)!r}).touch()\n"
        f"while not pathlib.Path({str(proceed)!r}).exists(): time.sleep(.01)\n"
    )
    repo, env, g = make_repo(
        tmp_path, config=CONFIG + f"lifecycle_command: {sys.executable} {lifecycle}\n"
    )
    record_reviews(tmp_path, repo, env)
    g("checkout", "-q", "main")
    assert g("merge", "--no-ff", "sprint-002", "-m", "release").returncode == 0
    process = subprocess.Popen(
        [sys.executable, str(close or CLOSE), "sprint", "2", "post-merge"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 60
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "publisher did not reach lifecycle pause"
        scripts = (close or CLOSE).parent
        write = (
            "import sys; from pathlib import Path; "
            f"sys.path[:0] = [{str(scripts)!r}, {str(scripts / 'close')!r}]; "
            "from sprint_state import write_sprint_state; "
            f"write_sprint_state(Path({str(marker_path(tmp_path))!r}), "
            "{'rounds': [{'blocking': ['CONCURRENT BLOCKER']}]})"
        )
        writer = subprocess.run(
            [sys.executable, "-c", write], cwd=repo, env=env, capture_output=True, text=True
        )
        assert writer.returncode == 0, writer.stderr
        proceed.touch()
        stdout, stderr = process.communicate(timeout=60)
        assert process.returncode == 2, "publisher accepted stale authority: " + stdout + stderr
        assert "authority changed" in stderr
        assert g("tag", "--list", "v0.3.0").stdout == ""
        assert not (tmp_path / "data/releases/sprint-2.json").exists()
        assert (tmp_path / "data/sprint_branch").exists()
        assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["blocking"] == [
            "CONCURRENT BLOCKER"
        ]
    finally:
        proceed.touch()
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_post_merge_rejects_concurrent_authority_change(tmp_path):
    _concurrent_publication(tmp_path)


def test_guard_rejects_target_defect(tmp_path):
    import shutil

    import pytest
    from sprint_helpers import PLUGIN

    candidate = tmp_path / "candidate"
    shutil.copytree(PLUGIN, candidate)
    guard = candidate / "scripts/close/shipping.py"
    text = guard.read_text()
    target = "if json.dumps(current, sort_keys=True) != authority:"
    assert target in text
    guard.write_text(text.replace(target, "if False:"))
    with pytest.raises(AssertionError, match="publisher accepted stale authority"):
        _concurrent_publication(tmp_path, candidate / "scripts/close.py")
    assert (tmp_path / "data/releases/sprint-2.json").is_file()
    assert not (tmp_path / "data/sprint_branch").exists()
    import subprocess

    tag = subprocess.check_output(
        ["git", "tag", "--list", "v0.3.0"], cwd=tmp_path / "repo", text=True
    )
    assert tag.strip() == "v0.3.0"


@pytest.mark.parametrize("fault", ["red", "interrupt", "dirty", "head", "owner", "history"])
def test_shipping_refusals_preserve_release_state(tmp_path, fault):
    from sprint_helpers import CONFIG, record_reviews

    root = tmp_path / "data"
    action = {
        "red": "false",
        "interrupt": "kill -TERM $$",
        "dirty": "echo dirty >> src.py",
        "head": "echo changed >> src.py && git commit -qam moved",
        "owner": f"echo sprint-999 > '{root / 'sprint_branch'}'",
        "history": "true",
    }[fault]
    repo, env, g = make_repo(tmp_path, config=CONFIG.replace("full: true", f"full: {action}"))
    record_reviews(tmp_path, repo, env)
    if fault == "history":
        state = json.loads(marker_path(tmp_path).read_text())
        state["full_tier_history"] = "unreadable history"
        marker_path(tmp_path).write_text(json.dumps(state))
    g("checkout", "-q", "main")
    assert g("merge", "--no-ff", "sprint-002", "-m", "release").returncode == 0

    result = sprint(repo, env, "post-merge")

    assert result.returncode == 2, result.stdout + result.stderr
    assert not g("tag", "--list", "v0.3.0").stdout
    assert not (root / "releases/sprint-2.json").exists()
    assert (root / "sprint_branch").exists()
    assert marker_path(tmp_path).exists()
    if fault == "history":
        assert json.loads(marker_path(tmp_path).read_text())["full_tier_history"] == (
            "unreadable history"
        )
    elif fault == "dirty":
        assert "dirty" in (repo / "src.py").read_text()
    elif fault == "owner":
        assert (root / "sprint_branch").read_text().strip() == "sprint-999"


def test_shipping_validation_persistence_refusal_prevents_publication(tmp_path):
    import subprocess
    import sys

    from sprint_helpers import CLOSE, CONFIG, record_reviews

    events = tmp_path / "checks-ran"
    command = f"echo checked >> '{events}'"
    repo, env, g = make_repo(tmp_path, config=CONFIG.replace("full: true", f"full: {command}"))
    record_reviews(tmp_path, repo, env)
    g("checkout", "-q", "main")
    assert g("merge", "--no-ff", "sprint-002", "-m", "release").returncode == 0
    before = marker_path(tmp_path).read_bytes()
    program = f"""
import sys
sys.path[:0] = [{str(CLOSE.parent)!r}, {str(CLOSE.parent / "close")!r}]
import close, sprint_state
def refuse(*args, **kwargs):
    raise OSError('constructed persistence failure')
sprint_state.append_tier_evidence = refuse
sys.argv = ['close.py', 'sprint', '2', 'post-merge']
raise SystemExit(close.main())
"""
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == 2 and "constructed persistence failure" in result.stderr
    assert events.read_text().splitlines() == ["checked"]
    assert marker_path(tmp_path).read_bytes() == before
    assert not g("tag", "--list", "v0.3.0").stdout
    assert not (tmp_path / "data/releases/sprint-2.json").exists()
    assert (tmp_path / "data/sprint_branch").exists()


@pytest.mark.parametrize("versioned", [True, False])
def test_shipping_rechecks_release_branch_after_lifecycle(tmp_path, versioned):
    import sys

    from sprint_helpers import CONFIG, record_reviews

    hook = tmp_path / "advance-branch.py"
    hook.write_text(
        "import subprocess\n"
        "def git(*args):\n"
        "    return subprocess.check_output(['git', *args], text=True).strip()\n"
        "tree = git('rev-parse', 'sprint-002^{tree}')\n"
        "parent = git('rev-parse', 'sprint-002')\n"
        "commit = git('commit-tree', tree, '-p', parent, '-m', 'new sprint work')\n"
        "git('update-ref', 'refs/heads/sprint-002', commit)\n"
    )
    config = CONFIG + f"lifecycle_command: {sys.executable} {hook}\n"
    if not versioned:
        config += "versioning: off\n"
    repo, env, g = make_repo(tmp_path, config=config)
    record_reviews(tmp_path, repo, env)
    g("checkout", "-q", "main")
    assert g("merge", "--no-ff", "sprint-002", "-m", "release").returncode == 0
    before = head(repo, env)

    result = sprint(repo, env, "post-merge")

    assert g("merge-base", "--is-ancestor", "sprint-002", "HEAD").returncode != 0
    assert head(repo, env) == before
    assert result.returncode == 2, result.stdout + result.stderr
    assert "branch" in result.stderr
    assert not g("tag", "--list", "v0.3.0").stdout
    assert not (tmp_path / "data/releases/sprint-2.json").exists()
    assert (tmp_path / "data/sprint_branch").exists()
