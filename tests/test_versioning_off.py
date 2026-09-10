"""A project may ship through XP while another process owns its versions."""

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from close_free_card_cases import (
    add_free_card,
    checkout_free,
    commit_on_free,
    spawn_free,
)
from close_helpers import PLUGIN, free, free_repo, gh_calls
from sprint_helpers import CONFIG, make_repo, marker_path, sprint
from test_close_free_post_merge import TestFreeTeardown as _FreeTeardown
from test_sprint_land import record_release, release_state, release_tools

sys.path.insert(0, str(PLUGIN / "scripts" / "close"))
import release


def configure_off(repo, g, extra=""):
    config = repo / ".xp" / "config.yml"
    config.write_text(config.read_text() + "versioning: off\n" + extra)
    g("add", "-A")
    g("commit", "-qm", "disable XP versioning")


def nonsemver_only(g):
    for tag in g("tag", "--list").stdout.splitlines():
        g("tag", "-d", tag)
    g("tag", "release-2024-03")


def off_line(output):
    matches = [line for line in output.splitlines() if "versioning" in line.lower()]
    assert len(matches) == 1, output
    line = matches[0]
    lowered = line.lower()
    assert "off" in lowered and "no tag" in lowered
    assert "version_files" in line and "ignored" in lowered
    clause = re.search(
        r"^.*?\bversioning\b.*?\boff\b.*?\bno tag\b.*?\bversion_files\b.*?\bignored\b",
        line,
        re.IGNORECASE,
    )
    assert clause, line
    return clause.group(0)


def assert_no_release_promise(output):
    remainder = output
    if "versioning" in output.lower():
        remainder = remainder.replace(off_line(output), "", 1)
    remainder = remainder.lower()
    assert not re.search(r"\b(?:tag|tagged|tagging|version)\b|\bv\d+\.\d+", remainder), output


def preview_title(output, next_flag):
    command = next(line for line in output.splitlines() if line.startswith("gh pr create"))
    return command.split("--title ", 1)[1].split(f" {next_flag}", 1)[0]


def reviewed_free(tmp_path, value="off"):
    repo, env, g = free_repo(tmp_path)
    config = repo / ".xp" / "config.yml"
    config.write_text(config.read_text() + f"versioning: {value}\n")
    g("add", "-A")
    g("commit", "-qm", "configure versioning")
    g("push", "-q", "origin", "main")
    assert free(repo, env, "fix-typo", "start").returncode == 0
    branch, key = checkout_free(g)
    commit_on_free(repo, g)
    add_free_card(env, key)
    tree = spawn_free(repo, env, g, tmp_path, key)
    assert g("worktree", "remove", "--force", str(tree)).returncode == 0
    assert g("checkout", "-q", branch).returncode == 0
    reviewed = free(repo, env, "fix-typo", "review")
    assert reviewed.returncode == 0, reviewed.stderr + reviewed.stdout
    return repo, env, g, branch, key


@pytest.mark.slow
def test_sprint_land_off_titles_preview_and_real_with_the_sprint_branch(tmp_path):
    outputs = []
    for dry in (True, False):
        root = tmp_path / ("dry" if dry else "real")
        repo, env, g = make_repo(root, config=CONFIG + "versioning: off\n")
        nonsemver_only(g)
        record_release(root, release_state(repo, env))
        record = release_tools(root, env, g)

        result = sprint(repo, env, "land", *(("--dry-run",) if dry else ()))

        assert result.returncode == 0, result.stderr + result.stdout
        if dry:
            assert preview_title(result.stdout, "--body-file") == "release sprint-002"
        else:
            call = json.loads(record.read_text())["argv"]
            assert call[call.index("--title") + 1] == "release sprint-002"
        assert "release-2024-03" not in result.stdout + result.stderr
        assert_no_release_promise(result.stdout)
        outputs.append(result.stdout)
    assert off_line(outputs[0]) == off_line(outputs[1])


@pytest.mark.slow
def test_free_land_off_titles_preview_and_real_with_the_free_noun(tmp_path):
    outputs = []
    for dry in (True, False):
        root = tmp_path / ("dry" if dry else "real")
        repo, env, g, _branch, _key = reviewed_free(root)
        nonsemver_only(g)

        result = free(repo, env, "fix-typo", "land", *(("--dry-run",) if dry else ()))

        assert result.returncode == 0, result.stderr + result.stdout
        if dry:
            assert preview_title(result.stdout, "--body") == "free fix-typo"
        else:
            create = next(call for call in gh_calls(root) if call[:2] == ["pr", "create"])
            assert create[create.index("--title") + 1] == "free fix-typo"
        assert "release-2024-03" not in result.stdout + result.stderr
        assert_no_release_promise(result.stdout)
        outputs.append(result.stdout)
    assert off_line(outputs[0]) == off_line(outputs[1])


def test_free_start_off_uses_shipping_not_patch_tag_language(tmp_path):
    root = tmp_path / "started"
    repo, env, g = free_repo(root)
    configure_off(repo, g)
    preview = free(repo, env, "fix-typo", "start", "--dry-run")
    started = free(repo, env, "fix-typo", "start")
    g("checkout", "-qb", "other-work")
    refused = free(repo, env, "another-fix", "start")

    assert preview.returncode == started.returncode == 0
    assert refused.returncode == 2 and "ship now" in refused.stderr.lower()
    assert "release artifacts" in started.stdout.lower()
    assert off_line(preview.stdout) == off_line(started.stdout)
    for output in (preview.stdout, started.stdout, refused.stderr):
        assert "patch tag" not in output.lower()
        assert "release-2024-03" not in output
        assert_no_release_promise(output)


def test_unset_versioning_keeps_free_start_patch_release_language(tmp_path):
    repo, env, g = free_repo(tmp_path)
    started = free(repo, env, "fix-typo", "start")
    assert started.returncode == 0 and "Cut release artifacts" in started.stdout
    g("checkout", "-q", "story-042-branch")
    refused = free(repo, env, "another-fix", "start")
    assert refused.returncode == 2 and "patch tag" in refused.stderr


def lifecycle_recorder(tmp_path, exit_code=0):
    tmp_path.mkdir(parents=True, exist_ok=True)
    record = tmp_path / "lifecycle.jsonl"
    script = tmp_path / "lifecycle.py"
    script.write_text(
        f"import json, sys\nopen({str(record)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"raise SystemExit({exit_code})\n"
    )
    return shlex.join([sys.executable, str(script)]), record


def test_sprint_post_merge_off_runs_lifecycle_clears_record_and_cuts_no_tag(tmp_path):
    outputs = []
    for dry in (True, False):
        root = tmp_path / ("dry" if dry else "real")
        command, record = lifecycle_recorder(root)
        config = CONFIG + f"versioning: off\nlifecycle_command: {command}\n"
        repo, env, g = make_repo(root, config=config)
        nonsemver_only(g)
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
        before = g("tag", "--list").stdout

        result = sprint(repo, env, "post-merge", *(("--dry-run",) if dry else ()))

        assert result.returncode == 0, result.stderr + result.stdout
        assert g("tag", "--list").stdout == before
        branch_record = root / "data" / "sprint_branch"
        if dry:
            assert branch_record.exists() and not record.exists()
        else:
            assert not branch_record.exists()
            assert [json.loads(line) for line in record.read_text().splitlines()] == [
                ["sprint-close", "2"]
            ]
        outputs.append(result.stdout)
        assert_no_release_promise(result.stdout)
    assert off_line(outputs[0]) == off_line(outputs[1])


def test_sprint_post_merge_off_keeps_branch_record_when_lifecycle_refuses(tmp_path):
    command, record = lifecycle_recorder(tmp_path, exit_code=1)
    config = CONFIG + f"versioning: off\nlifecycle_command: {command}\n"
    repo, env, g = make_repo(tmp_path, config=config)
    nonsemver_only(g)
    g("checkout", "-q", "main")
    g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
    before = g("tag", "--list").stdout

    result = sprint(repo, env, "post-merge")

    assert result.returncode == 2
    assert g("tag", "--list").stdout == before
    assert (tmp_path / "data" / "sprint_branch").read_text().strip() == "sprint-002"
    assert [json.loads(line) for line in record.read_text().splitlines()] == [["sprint-close", "2"]]


def test_sprint_post_merge_off_on_trunk_without_the_merge_refuses(tmp_path):
    command, record = lifecycle_recorder(tmp_path)
    config = CONFIG + f"versioning: off\nlifecycle_command: {command}\n"
    repo, env, g = make_repo(tmp_path, config=config)
    g("checkout", "-q", "main")

    result = sprint(repo, env, "post-merge")

    assert result.returncode == 2 and not record.exists()
    assert (tmp_path / "data" / "sprint_branch").read_text().strip() == "sprint-002"
    assert "merged" in result.stderr and not re.search(r"\btag", result.stderr)


@pytest.mark.slow
def test_free_post_merge_off_retires_card_worktree_branches_and_markers_without_a_tag(tmp_path):
    helper = _FreeTeardown()
    root = tmp_path / "real"
    repo, env, g, tree, spawned_branch, branch, key = helper.spawned(root)
    configure_off(repo, g)
    nonsemver_only(g)
    before = g("tag", "--list").stdout

    result = free(repo, env, "fix-typo", "post-merge")

    assert result.returncode == 0, result.stderr + result.stdout
    assert g("tag", "--list").stdout == before
    assert "[done]" in (Path(env["XP_DATA"]) / "plan.md").read_text()
    branches = g("branch", "--format=%(refname:short)").stdout.splitlines()
    assert not tree.exists() and spawned_branch not in branches and branch not in branches
    markers = Path(env["XP_DATA"]) / "markers"
    assert not any(key in path.name for path in markers.rglob("*"))
    off_line(result.stdout)
    assert_no_release_promise(result.stdout)


@pytest.mark.slow
def test_free_post_merge_off_preview_keeps_every_artifact_and_cuts_no_tag(tmp_path):
    helper = _FreeTeardown()
    repo, env, g, tree, spawned_branch, branch, key = helper.spawned(tmp_path)
    configure_off(repo, g)
    nonsemver_only(g)
    before = g("tag", "--list").stdout

    result = free(repo, env, "fix-typo", "post-merge", "--dry-run")

    assert result.returncode == 0, result.stderr + result.stdout
    assert g("tag", "--list").stdout == before and tree.exists()
    assert "[in-progress]" in (Path(env["XP_DATA"]) / "plan.md").read_text()
    branches = g("branch", "--format=%(refname:short)").stdout.splitlines()
    assert spawned_branch in branches and branch in branches
    assert any(key in path.name for path in (Path(env["XP_DATA"]) / "markers").rglob("*"))
    off_line(result.stdout)
    assert_no_release_promise(result.stdout)


def direct_release_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = lambda *args: subprocess.run(  # noqa: E731
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / ".xp").mkdir()
    (repo / ".xp" / "config.yml").write_text(
        "versioning: off\nversion_files: does-not-exist.json\n"
    )
    git("add", "-A")
    git("commit", "-qm", "release tree")
    git("tag", "release-2024-03")
    monkeypatch.chdir(repo)
    return git


def test_off_never_calls_version_files_and_reports_it_ignored(tmp_path, monkeypatch, capsys):
    git = direct_release_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(release, "version_files", lambda: pytest.fail("consulted version_files"))
    before = git("tag", "--list").stdout

    assert release.cmd_post_merge("fixture", retire_sprint=False, dry_run=True) == 0
    preview = capsys.readouterr().out
    assert release.cmd_post_merge("fixture", retire_sprint=False) == 0
    real = capsys.readouterr().out

    assert git("tag", "--list").stdout == before
    assert off_line(preview) == off_line(real)
    assert_no_release_promise(preview)
    assert_no_release_promise(real)


def test_post_merge_off_wrong_branch_refusal_does_not_promise_a_tag(tmp_path, monkeypatch, capsys):
    direct_release_repo(tmp_path, monkeypatch)
    subprocess.run(["git", "checkout", "-qb", "other"], check=True, capture_output=True)

    assert release.cmd_post_merge("fixture", retire_sprint=False) == 2

    refusal = capsys.readouterr().err.lower()
    assert "merged sha" in refusal and " tag " not in f" {refusal} "


@pytest.mark.parametrize("value", ["", "on", "false", "OFF"], ids=["empty", "on", "false", "case"])
def test_invalid_versioning_value_is_neither_enabled_nor_off(tmp_path, monkeypatch, value):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".xp").mkdir()
    (repo / ".xp" / "config.yml").write_text(f"versioning: {value}\n")
    monkeypatch.chdir(repo)
    enabled, refusal = release.versioning_mode()
    assert enabled is False
    assert "off" in refusal and (value or "empty") in refusal


@pytest.mark.slow
def test_each_version_aware_route_reads_invalid_versioning(tmp_path):
    value = "on"
    cases = []

    start_repo, start_env, start_git = free_repo(tmp_path / "start")
    (start_repo / ".xp" / "config.yml").write_text(f"versioning: {value}\n")
    start_git("add", "-A")
    start_git("commit", "-qm", "invalid versioning")
    cases.append(free(start_repo, start_env, "fix-typo", "start"))
    assert not start_git(
        "for-each-ref", "--format=%(refname:short)", "refs/heads/*/free-*"
    ).stdout.strip()

    free_repo_, free_env, free_git, _branch, _key = reviewed_free(tmp_path / "land")
    config = free_repo_ / ".xp" / "config.yml"
    config.write_text(config.read_text().replace("versioning: off", f"versioning: {value}"))
    free_git("add", "-A")
    free_git("commit", "-qm", "invalid versioning")
    reviewed = free(free_repo_, free_env, "fix-typo", "review")
    assert reviewed.returncode == 0, reviewed.stderr + reviewed.stdout
    cases.append(free(free_repo_, free_env, "fix-typo", "land"))
    assert not gh_calls(tmp_path / "land")

    sprint_repo, sprint_env, sprint_git = make_repo(
        tmp_path / "sprint-land", config=CONFIG + f"versioning: {value}\n"
    )
    record_release(tmp_path / "sprint-land", release_state(sprint_repo, sprint_env))
    release_tools(tmp_path / "sprint-land", sprint_env, sprint_git)
    sprint_marker = marker_path(tmp_path / "sprint-land").read_bytes()
    sprint_tags = sprint_git("tag", "--list").stdout
    cases.append(sprint(sprint_repo, sprint_env, "land", "--dry-run"))
    cases.append(sprint(sprint_repo, sprint_env, "land"))
    assert marker_path(tmp_path / "sprint-land").read_bytes() == sprint_marker
    assert sprint_git("tag", "--list").stdout == sprint_tags
    assert not gh_calls(tmp_path / "sprint-land")

    command, lifecycle = lifecycle_recorder(tmp_path / "sprint-post")
    post_config = CONFIG + f"versioning: {value}\nlifecycle_command: {command}\n"
    post_repo, post_env, post_git = make_repo(tmp_path / "sprint-post", config=post_config)
    post_git("checkout", "-q", "main")
    post_git("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
    sprint_tags = post_git("tag", "--list").stdout
    cases.append(sprint(post_repo, post_env, "post-merge"))
    assert post_git("tag", "--list").stdout == sprint_tags
    assert (tmp_path / "sprint-post" / "data" / "sprint_branch").exists()
    assert not lifecycle.exists()

    free_post_repo, free_post_env, free_post_git, branch, _ = reviewed_free(tmp_path / "free-post")
    free_post_git("checkout", "-q", "main")
    free_post_git("merge", "-q", "--no-ff", branch, "-m", "release")
    config = free_post_repo / ".xp" / "config.yml"
    config.write_text(config.read_text().replace("versioning: off", f"versioning: {value}"))
    free_post_git("add", "-A")
    free_post_git("commit", "-qm", "invalid versioning")
    free_tags = free_post_git("tag", "--list").stdout
    cases.append(free(free_post_repo, free_post_env, "fix-typo", "post-merge"))
    assert free_post_git("tag", "--list").stdout == free_tags
    assert "[in-progress]" in (Path(free_post_env["XP_DATA"]) / "plan.md").read_text()
    assert branch in free_post_git("branch", "--format=%(refname:short)").stdout.splitlines()

    assert all(case.returncode == 2 for case in cases)
    for case in cases:
        assert "versioning" in case.stderr and "off" in case.stderr


def test_uncommenting_the_template_line_beside_version_files_turns_versioning_off(
    tmp_path, monkeypatch
):
    lines = (PLUGIN / "templates" / "config.yml").read_text().splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("# version_files:"))
    assert [line for line in lines if "versioning:" in line] == [lines[index - 1]]
    (tmp_path / ".xp").mkdir()
    (tmp_path / ".xp" / "config.yml").write_text(lines[index - 1].removeprefix("# ") + "\n")
    monkeypatch.chdir(tmp_path)
    assert release.versioning_mode() == (False, "")
