"""The story worktree's external environment is discharged before removal."""

import time
from pathlib import Path

from close_helpers import close, worktree_land_setup
from spawn_helpers import make_repo as make_spawn_repo
from spawn_helpers import spawn, stub_claude


def land(tmp_path, **options):
    _repo, env, _g, tree, _branch = worktree_land_setup(tmp_path, **options)
    return tree, close(tree, env, "land", "--merge-mode", "local")


def test_teardown_runs_in_the_story_tree_before_forced_removal(tmp_path):
    sentinel = tmp_path / "teardown-cwd"
    command = f"pwd -P > {sentinel}; touch teardown.log"
    tree, result = land(tmp_path, teardown=f"`{command}`")
    assert result.returncode == 0, result.stderr
    assert Path(sentinel.read_text().strip()).resolve() == tree.resolve()
    assert not tree.exists(), "teardown dirt kept the worktree alive"


def test_a_failed_teardown_reports_but_does_not_block_removal(tmp_path):
    tree, result = land(tmp_path, teardown="`exit 7`")
    assert result.returncode == 3
    assert "Worktree teardown failed ('exit 7')" in result.stderr
    assert "worktree removed; inspect external state manually" in result.stderr
    assert "Re-run or resolve them" in result.stderr
    assert not tree.exists()


def test_an_unreadable_teardown_reports_but_does_not_block_removal(tmp_path):
    tree, result = land(tmp_path, teardown="run cleanup")
    assert result.returncode == 3
    assert "cannot read the Worktree teardown line" in result.stderr
    assert "worktree removed; inspect external state manually" in result.stderr
    assert not tree.exists()


def test_no_teardown_does_not_parse_or_run_bootstrap(tmp_path):
    sentinel = tmp_path / "wrong-field-ran"
    tree, result = land(tmp_path, bootstrap=f"`pwd -P > {sentinel}`")
    assert result.returncode == 0, result.stderr
    assert not sentinel.exists(), "teardown parsed the bootstrap command"
    assert not tree.exists()


def test_a_missing_system_file_is_the_no_teardown_arm(tmp_path):
    tree, result = land(tmp_path, system=False)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert not tree.exists()


def test_a_hung_teardown_is_killed_and_removal_continues(tmp_path):
    started = time.monotonic()
    tree, result = land(tmp_path, teardown="`sleep 30`", teardown_timeout=1)
    assert time.monotonic() - started < 5
    assert result.returncode == 3
    assert "Worktree teardown timed out after 1s ('sleep 30')" in result.stderr
    assert "worktree removed; inspect external state manually" in result.stderr
    assert not tree.exists()


def test_timeout_comes_from_the_post_merge_trunk_config(tmp_path):
    repo, env, g, tree, _branch = worktree_land_setup(
        tmp_path, teardown="`sleep 30`", teardown_timeout=60
    )
    config = repo / ".xp" / "config.yml"
    config.write_text(config.read_text().replace("teardown_timeout: 60", "teardown_timeout: 1"))
    g("add", str(config))
    g("commit", "-qm", "lower teardown timeout on trunk")
    started = time.monotonic()
    result = close(tree, env, "land", "--merge-mode", "local")
    assert time.monotonic() - started < 5
    assert result.returncode == 3
    assert "timed out after 1s" in result.stderr
    assert not tree.exists()


def test_a_malformed_timeout_warns_and_uses_the_default(tmp_path):
    tree, result = land(tmp_path, teardown="`true`", teardown_timeout="one minute")
    assert result.returncode == 0, result.stderr
    assert "teardown_timeout: 'one minute' is not a positive integer — used 60s" in result.stderr
    assert not tree.exists()


def test_a_malformed_timeout_is_irrelevant_without_a_teardown(tmp_path):
    tree, result = land(tmp_path, teardown_timeout="one minute")
    assert result.returncode == 0, result.stderr
    assert "teardown_timeout" not in result.stderr
    assert not tree.exists()


def test_the_general_parser_still_reads_bootstrap():
    from bookkeep import worktree_command

    assert worktree_command("Worktree bootstrap: `echo ok`", "bootstrap") == ("echo ok", "")


def spawn_refusal(tmp_path, teardown):
    repo, env, g = make_spawn_repo(tmp_path)
    g("checkout", "-q", "main")
    system = repo / ".xp" / "system.md"
    system.write_text("# System\n- Worktree bootstrap: none needed\n" + teardown)
    g("add", str(system))
    g("commit", "-qm", "configure teardown")
    g("checkout", "-q", "elsewhere")
    stub_claude(tmp_path, commit=False)
    return spawn(repo, env, "story-042")


def test_abandonment_names_teardown_only_in_the_discard_recovery(tmp_path):
    result = spawn_refusal(tmp_path, "- Worktree teardown: `docker compose down`\n")
    assert result.returncode == 2
    assert "or by running 'docker compose down' and then `git worktree remove" in result.stderr
    assert result.stderr.index("committing by hand") < result.stderr.index("docker compose down")


def test_abandonment_without_teardown_invents_no_hand_step(tmp_path):
    result = spawn_refusal(tmp_path, "")
    assert result.returncode == 2
    assert "Worktree teardown" not in result.stderr


def test_abandonment_reports_an_unreadable_teardown(tmp_path):
    result = spawn_refusal(tmp_path, "- Worktree teardown: run cleanup\n")
    assert result.returncode == 2
    assert "cannot read the Worktree teardown line" in result.stderr
