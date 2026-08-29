"""The story worktree's external environment is discharged before removal."""

import os
import signal
import subprocess
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
    # Constraint 2: assert the EVENT, and keep the clock as a generous hang guard
    # only. The stderr line below is the real proof — it can only be written by the
    # kill path, and a teardown allowed to run would take 30s and never emit it.
    # The bound was tuned 5 -> 20 chasing xdist load and still red at 20.06s; a
    # third guess at machine speed is the wall-clock trap, so it beats `sleep 30`
    # by a wide margin instead. It asserts AFTER the event, or a slow machine
    # reports a timing miss while saying nothing about the mechanism.
    started = time.monotonic()
    tree, result = land(tmp_path, teardown="`sleep 30`", teardown_timeout=1)
    assert result.returncode == 3
    assert "Worktree teardown timed out after 1s ('sleep 30')" in result.stderr
    assert time.monotonic() - started < 120
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


def test_the_handback_guard_survives_a_teammate_written_non_utf8_system(tmp_path):
    """spawn's THIRD reader of this file. It parses the teardown line only to
    enrich the handback refusal, so a decode error there costs the whole guard:
    the teammate's uncommitted work goes unreported and spawn dies rc 1 instead."""
    from spawn import unclean_teammate_result

    _repo, _env, g = make_repo(tmp_path)
    tree = tmp_path / "wt"
    g("worktree", "add", "-q", str(tree), "main")
    (tree / ".xp" / "system.md").write_bytes(b"**Worktree teardown**: `true` caf\xe9\n")
    (tree / "left-behind.txt").write_text("uncommitted\n")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tree, capture_output=True, text=True
    ).stdout.strip()

    err = unclean_teammate_result(tree, (head, ""), "story-042")
    assert "left work uncommitted" in err and "left-behind.txt" in err
    assert "Could not read" in err


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


def test_a_second_line_for_one_label_is_refused_naming_both():
    """Bug 90fcd7d4, hit during story-029's AC8 walk. The shipped template's
    bootstrap line is an unreadable PLACEHOLDER on purpose, and appending below a
    commented block is the ordinary way people edit a scaffolded file — so the
    real command sits two rows under the placeholder that wins, and the consumer
    is refused over a line they never wrote. Refuse rather than pick: last-wins
    would guess, and the two orderings mean opposite things to different people.
    """
    from bookkeep import worktree_command

    doc = "**Worktree bootstrap**: <one backticked command>\n- Worktree bootstrap: `make dev`\n"
    command, problem = worktree_command(doc, "bootstrap")
    assert command == "", f"a duplicated label must not silently pick one: {command!r}"
    assert "twice" in problem or "more than once" in problem, problem
    assert "<one backticked command>" in problem and "make dev" in problem, (
        f"the refusal must name BOTH lines, or it sends the reader to the wrong one: {problem!r}"
    )


def test_one_label_twice_is_refused_even_when_both_lines_are_readable():
    """The duplicate is the defect, not the unreadability — two valid commands is
    the case where silently running the first is most expensive."""
    from bookkeep import worktree_command

    command, problem = worktree_command(
        "- Worktree teardown: `docker compose down`\n- Worktree teardown: `make clean`\n",
        "teardown",
    )
    assert command == "", command
    assert "docker compose down" in problem and "make clean" in problem, problem


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
