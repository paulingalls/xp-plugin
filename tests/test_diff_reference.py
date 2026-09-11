import subprocess

import pytest
from close import build_bundle
from close_free_card_cases import add_free_card, checkout_free, commit_on_free
from close_helpers import close, free, free_repo, launches, make_repo
from diff_reference_helpers import named_diff_argv, named_section, read_named_diff
from sprint_bundle import build as build_sprint_bundle
from sprint_helpers import (
    bundles,
    head,
    sprint,
    stage_key,
    staged_stub,
)
from sprint_helpers import (
    make_repo as make_sprint_repo,
)


def git_stdout(repo, env, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True
    ).stdout


def assert_reference(bundle, title, repo, env, expected_base, expected_head):
    body = named_section(bundle, title)
    diff_range = f"{expected_base}..{expected_head}"
    assert f"Base: {expected_base}" in body
    assert f"Head: {expected_head}" in body
    assert f"Range: {diff_range}" in body
    assert f"git diff {diff_range}" in body
    assert f"git diff {diff_range} -- <path>" in body
    assert git_stdout(repo, env, "log", "--format=%H%x09%s", diff_range).rstrip() in body
    assert (
        git_stdout(
            repo,
            env,
            "-c",
            "core.quotepath=off",
            "diff",
            "--numstat",
            "--no-renames",
            diff_range,
        ).rstrip()
        in body
    )
    assert "diff --git" not in body and "@@" not in body
    assert read_named_diff(bundle, title, repo, env) == git_stdout(repo, env, "diff", diff_range)


@pytest.mark.slow
def test_story_free_and_every_sprint_stage_name_bounded_pinned_ranges(tmp_path):
    story_root = tmp_path / "story"
    story_root.mkdir()
    repo, env, g = make_repo(story_root)
    g("config", "diff.renames", "true")
    g("checkout", "-q", "main")
    old = repo / "src" / "rename-me.py"
    old.write_text("\n".join(f"UNCHANGED_{i} = {i}" for i in range(10)) + "\n")
    g("add", old.relative_to(repo))
    g("commit", "-qm", "add rename source")
    g("checkout", "-q", "story-042-branch")
    g("rebase", "main")
    nested = repo / "src" / ("deep-directory-" * 8) / "renamed.py"
    nested.parent.mkdir(parents=True)
    g("mv", old.relative_to(repo), nested.relative_to(repo))
    unicode_path = repo / "src" / "é.py"
    unicode_path.write_text("SOURCE-BODY-SENTINEL = 'UNICODE_PATH_SENTINEL'\n")
    g("add", "-A")
    g("commit", "-qm", "rename a long path")
    expected_head = head(repo, env)
    expected_base = git_stdout(repo, env, "merge-base", "main", "HEAD").strip()
    assert close(repo, env, "review").returncode == 0
    story_bundle = launches(story_root)[0]["stdin"]
    assert_reference(story_bundle, "Cumulative diff", repo, env, expected_base, expected_head)
    body = named_section(story_bundle, "Cumulative diff")
    assert "SOURCE-BODY-SENTINEL" not in body
    numstat = git_stdout(
        repo,
        env,
        "-c",
        "core.quotepath=off",
        "diff",
        "--numstat",
        "--no-renames",
        f"{expected_base}..{expected_head}",
    )
    for line in numstat.splitlines():
        path = line.split("\t", 2)[2]
        assert path in body
        assert git_stdout(repo, env, "diff", f"{expected_base}..{expected_head}", "--", path)

    free_root = tmp_path / "free"
    free_root.mkdir()
    free_work, free_env, free_git = free_repo(free_root)
    assert free(free_work, free_env, "diff-ref", "start").returncode == 0
    _branch, key = checkout_free(free_git)
    commit_on_free(free_work, free_git)
    add_free_card(free_env, key)
    preview = free(free_work, free_env, "diff-ref", "review", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    free_base = git_stdout(free_work, free_env, "merge-base", "main", "HEAD").strip()
    assert_reference(
        preview.stdout, "Cumulative diff", free_work, free_env, free_base, head(free_work, free_env)
    )

    sprint_root = tmp_path / "sprint"
    sprint_root.mkdir()
    sprint_repo, sprint_env, _sprint_git = make_sprint_repo(sprint_root)
    staged_stub(
        sprint_root,
        patches=[("fix", "src.py", "FIXER-SENTINEL = 1")],
        find={"fixed": [], "blocking": ["candidate"], "noted": []},
        verify={"fixed": [], "blocking": ["candidate"], "noted": []},
        fix={"fixed": ["candidate"], "blocking": [], "noted": []},
    )
    sprint_base = git_stdout(sprint_repo, sprint_env, "merge-base", "main", "HEAD").strip()
    assert sprint(sprint_repo, sprint_env, "review").returncode == 0
    launched = launches(sprint_root)
    assert {stage_key(item["stdin"]).split("-", 1)[0] for item in launched} == {
        "find",
        "verify",
        "fix",
        "close",
    }
    for item in launched:
        bundle = item["stdin"]
        argv = named_diff_argv(bundle, "Cumulative sprint diff")
        assert argv[2].startswith(sprint_base + "..")
        assert_reference(
            bundle,
            "Cumulative sprint diff",
            sprint_repo,
            sprint_env,
            sprint_base,
            argv[2].split("..", 1)[1],
        )


def story_bundle_size(tmp_path, body):
    repo, env, _g = make_repo(tmp_path)
    target = repo / "src" / "thing.py"
    target.write_text(body)
    git_stdout(repo, env, "add", "-A")
    git_stdout(repo, env, "commit", "-m", "sized change")
    assert close(repo, env, "review").returncode == 0
    return len(launches(tmp_path)[0]["stdin"])


def test_a_200kb_change_does_not_grow_the_bundle_by_1kb(tmp_path):
    small = tmp_path / "small"
    large = tmp_path / "large"
    small.mkdir()
    large.mkdir()
    small_size = story_bundle_size(small, "A = 'one line'\n")
    large_size = story_bundle_size(large, "A = '" + "x" * 200_000 + "'\n")
    assert large_size - small_size < 1_000


def test_story_command_reads_the_fork_point_diff(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    expected_base = git_stdout(repo, env, "merge-base", "main", "HEAD").strip()
    expected_head = head(repo, env)
    expected = git_stdout(repo, env, "diff", f"{expected_base}..{expected_head}")
    assert close(repo, env, "review").returncode == 0
    assert read_named_diff(launches(tmp_path)[0]["stdin"], "Cumulative diff", repo, env) == expected


def test_sprint_command_reads_the_cumulative_diff(tmp_path):
    repo, env, _g = make_sprint_repo(tmp_path)
    expected_base = git_stdout(repo, env, "merge-base", "main", "HEAD").strip()
    expected = git_stdout(repo, env, "diff", f"{expected_base}..HEAD")
    assert sprint(repo, env, "review").returncode == 0
    assert (
        read_named_diff(bundles(tmp_path, "find")[0], "Cumulative sprint diff", repo, env)
        == expected
    )


def test_sprint_command_reads_only_the_recorded_round_delta(tmp_path):
    repo, env, g = make_sprint_repo(tmp_path)
    assert sprint(repo, env, "review").returncode == 0
    shown = head(repo, env)
    target = repo / "src.py"
    target.write_text(target.read_text() + "ROUND_2 = 1\n")
    g("add", "src.py")
    g("commit", "-qm", "round two")
    expected = git_stdout(repo, env, "diff", f"{shown}..HEAD")
    staged_stub(tmp_path)
    split = len(launches(tmp_path))
    assert sprint(repo, env, "review").returncode == 0
    bundle = launches(tmp_path)[split]["stdin"]
    actual = read_named_diff(bundle, "The delta since the last recorded round", repo, env)
    assert actual == expected
    assert "+ROUND_2" in actual and "+B = 'SPRINT-ONLY-SENTINEL'" not in actual


def test_fixer_keeps_its_launch_range_and_closer_names_the_fix(tmp_path):
    repo, env, _g = make_sprint_repo(tmp_path)
    pre_fix_head = head(repo, env)
    base = git_stdout(repo, env, "merge-base", "main", "HEAD").strip()
    expected = git_stdout(repo, env, "diff", f"{base}..{pre_fix_head}")
    staged_stub(
        tmp_path,
        patches=[("fix", "src.py", "FIXER-SENTINEL = 1")],
        find={"fixed": [], "blocking": ["candidate"], "noted": []},
        verify={"fixed": [], "blocking": ["candidate"], "noted": []},
        fix={"fixed": ["candidate"], "blocking": [], "noted": []},
    )
    assert sprint(repo, env, "review").returncode == 0
    fix_bundle = next(b for b in bundles(tmp_path) if stage_key(b) == "fix")
    close_bundle = next(b for b in bundles(tmp_path) if stage_key(b) == "close")
    fix_argv = named_diff_argv(fix_bundle, "Cumulative sprint diff")
    close_argv = named_diff_argv(close_bundle, "Cumulative sprint diff")
    assert fix_argv[2].endswith(".." + pre_fix_head)
    assert close_argv[2].endswith(".." + head(repo, env))
    fix_diff = read_named_diff(fix_bundle, "Cumulative sprint diff", repo, env)
    close_diff = read_named_diff(close_bundle, "Cumulative sprint diff", repo, env)
    assert fix_diff == expected and "FIXER-SENTINEL" not in fix_diff
    assert "FIXER-SENTINEL" in close_diff


def test_an_empty_range_says_it_holds_no_changes_without_a_command(tmp_path, monkeypatch):
    repo, env, _g = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    same = head(repo, env)
    story = build_bundle("card", same, tmp_path / "story-report")
    sprint_bundle = build_sprint_bundle(
        "2", "cards", same, tmp_path / "sprint-report", "charter", [], [], ""
    )
    for bundle, title in (
        (story, "Cumulative diff"),
        (sprint_bundle, "Cumulative sprint diff"),
    ):
        body = named_section(bundle, title)
        assert f"Base: {same}" in body and f"Head: {same}" in body
        assert "holds no changes" in body
        with pytest.raises(AssertionError, match="expected one pinned diff command"):
            named_diff_argv(bundle, title)
