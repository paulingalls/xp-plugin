"""The story worktree's external environment is discharged before removal."""

import os
import signal
import time
from contextlib import suppress
from pathlib import Path

from close_helpers import close, make_repo, worktree_land_setup
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
    # The bound has to beat `sleep 30`, not time a land: at 5s it red under
    # xdist load on a machine where a land alone takes four.
    started = time.monotonic()
    tree, result = land(tmp_path, teardown="`sleep 30`", teardown_timeout=1)
    assert time.monotonic() - started < 20
    assert result.returncode == 3
    assert "Worktree teardown timed out after 1s ('sleep 30')" in result.stderr
    assert "worktree removed; inspect external state manually" in result.stderr
    assert not tree.exists()


def test_the_timeout_kill_reaches_the_teardown_s_own_children(tmp_path):
    """Killing only the shell orphans whatever it started — and a teardown that
    backgrounds work is exactly the shape that holds an environment open."""
    pidfile = tmp_path / "child.pid"
    # Its stdio is closed off deliberately: an orphan holding close.py's inherited
    # pipe would hang this test instead of failing it, hiding the property asked here.
    spinner = "sh -c 'while :; do sleep 0.2; done' >/dev/null 2>&1"
    tree, result = land(
        tmp_path, teardown=f"`{spinner} & echo $! > {pidfile}; sleep 30`", teardown_timeout=1
    )
    assert result.returncode == 3
    pid = int(pidfile.read_text())
    try:
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"the teardown's child {pid} outlived the timeout kill")
    finally:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    assert not tree.exists()


def test_a_teardown_that_raises_still_removes_the_worktree(tmp_path, monkeypatch):
    """By here the merge has landed, so a traceback is the one refusal nothing
    can absorb: it strands the tree AND the branch delete, marker cleanup and
    close log after it. Measured instance: a .xp/system.md that is not UTF-8."""
    from bookkeep import remove_story_worktree

    repo, _env, g = make_repo(tmp_path)
    tree = tmp_path / "wt"
    g("worktree", "add", "-q", str(tree), "main")
    (tree / ".xp" / "system.md").write_bytes(b"**Worktree teardown**: `true` caf\xe9\n")
    monkeypatch.chdir(repo)
    failed = remove_story_worktree(str(tree))
    assert not tree.exists(), "a raising teardown kept the worktree alive"
    assert "Worktree teardown could not run" in failed[0]
    assert "worktree removed; inspect external state manually" in failed[0]


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
    assert time.monotonic() - started < 20
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
    assert "or by `git worktree remove" in result.stderr, "a teardown nobody owes"
    assert "add --force" not in result.stderr
    assert "Worktree teardown" not in result.stderr


def test_abandonment_reports_an_unreadable_teardown(tmp_path):
    result = spawn_refusal(tmp_path, "- Worktree teardown: run cleanup\n")
    assert result.returncode == 2
    assert "cannot read the Worktree teardown line" in result.stderr
