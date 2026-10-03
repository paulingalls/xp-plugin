"""Open claims and collected tests have independent validation owners."""

import json
import shlex

import pytest
from sprint_helpers import CONFIG, make_repo, sprint
from test_secret_hooks import real_tools as real_tools
from work import entry_id


def claim(kind, name, command, extra=""):
    return f"## {kind} {name}\nClaim: {name}\nFalsifier: `{command}`\nFiles: a.py\n{extra}\n"


def counted(path):
    return f"printf x >> {shlex.quote(str(path))}"


@pytest.mark.parametrize("compact", [False, True])
def test_only_open_distinct_commands_run_without_rewriting_history(tmp_path, compact):
    from sprint_helpers import work

    config = CONFIG + "\ntier_coverage:\n  fast: absent\ntier_coverage_pins:\n  fast: stale\n"
    repo, env, _git = make_repo(tmp_path, config=config)
    paths = {name: tmp_path / name for name in ("shared", "retained", "resolved", "archived")}
    open_one = claim("debt", "first", counted(paths["shared"]), "Covered by: full\n")
    open_two = claim("debt", "second", counted(paths["shared"]))
    retained = claim("debt", "kept", counted(paths["retained"]))
    resolved = claim("bug", "fixed", "false")
    archived = claim("debt", "dropped", counted(paths["archived"]))
    text = open_one + open_two + retained + resolved + archived
    text += (
        f"## retained retention\nKeeps: {entry_id(retained)}\n"
        "Too big: separate design\nToo important: corruption\n\n"
    )
    text += (
        f"## resolved resolution\nResolves: {entry_id(resolved)}\n"
        f"Falsifier: `{counted(paths['resolved'])}; false`\nCovered by: none\n\n"
    )
    text += (
        f"## archived archive\nArchives: {entry_id(archived)}\n"
        "Disposition: dropped obsolete policy\n\n"
    )
    ledger = tmp_path / "data/work.md"
    ledger.write_text(text)
    if compact:
        assert work(repo, env, "compact").returncode == 0
    before = ledger.read_bytes()
    result = sprint(repo, env, "start")
    assert result.returncode == 0, result.stderr
    assert ledger.read_bytes() == before
    assert paths["shared"].read_text() == "x"
    assert paths["retained"].read_text() == "x"
    assert not paths["resolved"].exists() and not paths["archived"].exists()
    assert entry_id(open_one) in result.stdout and entry_id(retained) in result.stdout


def test_legacy_deferred_marker_does_not_replace_required_tier(tmp_path):
    from sprint_helpers import marker_path, record_reviews
    from test_sprint_tier_receipt import counted_repo, run_count, state

    repo, env, _git, events, _tier = counted_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    marker = marker_path(tmp_path)
    saved = state(tmp_path) | {"start_deferred_ids": {"obsolete": "malformed"}}
    marker.write_text(json.dumps(saved))
    result = sprint(repo, env, "land")
    assert result.returncode == 2 and "gh" in result.stderr
    assert run_count(events) == 1


@pytest.mark.parametrize("variant", ["githooks", "lefthook"])
def test_native_commit_and_push_keep_required_tier_checks(tmp_path, real_tools, variant):
    from test_secret_hooks import add_remote, git, remote_sha, wall_repo

    repo, env = wall_repo(tmp_path, real_tools, variant)
    fast_flag, story_flag = tmp_path / "red-fast", tmp_path / "red-story"
    config = repo / ".xp/config.yml"
    text = config.read_text().replace(
        "fast: true", f"fast: printf fast-check; test ! -e {fast_flag}"
    )
    config.write_text(
        text.replace("story: true", f"story: printf story-check; test ! -e {story_flag}")
    )
    assert git(repo, "add", "-A", env=env).returncode == 0
    assert git(repo, "commit", "-qm", "clean control", env=env).returncode == 0
    before = git(repo, "rev-parse", "HEAD", env=env).stdout
    fast_flag.touch()
    (repo / "change.txt").write_text("changed\n")
    git(repo, "add", "change.txt", env=env)
    red = git(repo, "commit", "-qm", "must refuse", env=env)
    assert red.returncode != 0 and "fast" in red.stdout + red.stderr
    assert git(repo, "rev-parse", "HEAD", env=env).stdout == before
    fast_flag.unlink()
    assert git(repo, "commit", "-qm", "clean after fix", env=env).returncode == 0
    add_remote(repo, env, tmp_path)
    story_flag.touch()
    red = git(repo, "push", "origin", "main", env=env)
    assert red.returncode != 0 and "story" in red.stdout + red.stderr
    assert not remote_sha(repo, env)
    story_flag.unlink()
    assert git(repo, "push", "-q", "origin", "main", env=env).returncode == 0
    assert remote_sha(repo, env) == git(repo, "rev-parse", "HEAD", env=env).stdout.strip()


def test_body_references_cannot_dispose_an_open_claim(tmp_path):
    repo, env, _git = make_repo(tmp_path)
    bug = claim("bug", "live", "false")
    mention = claim(
        "debt", "mention", "true", f"Resolves: {entry_id(bug)}\nArchives: {entry_id(bug)}\n"
    )
    ledger = tmp_path / "data/work.md"
    ledger.write_text(bug + mention)
    before = ledger.read_bytes()
    result = sprint(repo, env, "start")
    assert result.returncode == 2 and entry_id(bug) in result.stderr
    assert ledger.read_bytes() == before


def test_legacy_coverage_cycle_cannot_suppress_an_open_check(tmp_path):
    config = CONFIG.replace("tests:\n", "tests:\n  fast: true\n  story: true\n")
    config = config.replace(
        "reviewer: claude/opus", "reviewer: claude/opus\n  card-refresher: unused/harness"
    )
    config += (
        "tier_coverage:\n  fast: story\n  story: fast\n"
        "tier_coverage_pins:\n  fast: true\n  story: true\n"
    )
    repo, env, _git = make_repo(tmp_path, config=config)
    counter = tmp_path / "open"
    (tmp_path / "data/work.md").write_text(claim("debt", "legacy", counted(counter)))
    result = sprint(repo, env, "start")
    assert result.returncode == 0, result.stderr
    assert counter.read_text() == "x"
