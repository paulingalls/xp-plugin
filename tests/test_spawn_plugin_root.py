"""Spawn executes the installed plugin, independent of consumer layout."""

import json
from pathlib import Path

from spawn_helpers import SPAWN, make_repo, spawn, stub_claude


def test_consuming_project_keeps_installed_root_and_output(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    assert not (repo / "plugins" / "xp-plugin").exists()
    rec = stub_claude(tmp_path)
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    launched = json.loads(rec.read_text())
    assert str(SPAWN.parent / "work.py") in launched["stdin"]
    assert launched["env"]["XP_HARNESS"] == "claude"
    # nothing NEW printed, not just the right last line: a root or version disclosure
    # leaking anywhere into a consuming project's console is the design's failure arm.
    assert "xp-plugin" not in result.stdout + result.stderr
    assert result.stdout.splitlines()[-1].endswith(
        "Read it, then run `close.py story story-042 review`."
    )


def write_plugin_source(repo):
    """A tree that ships plugins/xp-plugin; work.py names the copy that ran."""
    plugin = repo / "plugins" / "xp-plugin"
    scripts = plugin / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "spawn.py").write_text("# source-tree sentinel\n")
    (scripts / "close.py").write_text("# source-tree sentinel\n")
    (scripts / "work.py").write_text(
        "from pathlib import Path\n"
        "Path('executed-plugin-script').write_text(str(Path(__file__).resolve()))\n"
    )
    manifest = plugin / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir()
    manifest.write_text('{"version": "9.8.7"}\n')


def test_a_consumer_plugin_tree_does_not_replace_the_installed_root(tmp_path):
    repo, env, g = make_repo(tmp_path)
    g("checkout", "-q", "main")
    write_plugin_source(repo)
    g("add", "-A")
    assert g("commit", "-qm", "fixture plugin source").returncode == 0
    g("checkout", "-q", "elsewhere")
    stub_claude(tmp_path, execute_escalation=True)

    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    tree = Path(env["XP_DATA"]) / "worktrees" / "story-042"
    assert not (tree / "executed-plugin-script").exists()
    handback = result.stdout.splitlines()[-1]
    assert handback.endswith("Read it, then run `close.py story story-042 review`.")


def test_a_free_consumer_plugin_tree_keeps_the_installed_root(tmp_path):
    from test_close_free import KEY, carded_free_patch

    repo, env, g = carded_free_patch(tmp_path)
    branch = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    g("checkout", "-q", "main")
    write_plugin_source(repo)
    g("add", "-A")
    assert g("commit", "-qm", "fixture plugin source").returncode == 0
    g("checkout", "-q", branch)
    assert g("merge", "-q", "main").returncode == 0
    stub_claude(tmp_path)

    result = spawn(repo, env, KEY)
    assert result.returncode == 0, result.stderr
    handback = result.stdout.splitlines()[-1]
    assert handback.endswith("close.py free fix-typo review` from that worktree.")
    assert "plugins/xp-plugin" not in handback


def test_a_branch_lacking_the_plugin_keeps_the_installed_root(tmp_path):
    """`free start` cuts off the DEFAULT branch and the integration target may be the
    sprint branch, so the target is not the ref the worktree comes from. Asking it
    hands the executor — and every close leg — a path its own worktree does not have."""
    from test_close_free import KEY, carded_free_patch

    repo, env, g = carded_free_patch(tmp_path)
    branch = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    g("checkout", "-q", "main")
    write_plugin_source(repo)
    g("add", "-A")
    assert g("commit", "-qm", "fixture plugin source").returncode == 0
    g("checkout", "-q", branch)
    rec = stub_claude(tmp_path)

    result = spawn(repo, env, KEY)
    assert result.returncode == 0, result.stderr
    assert not (Path(env["XP_DATA"]) / "worktrees" / KEY / "plugins").exists()
    assert str(SPAWN.parent / "work.py") in json.loads(rec.read_text())["stdin"]
    assert result.stdout.splitlines()[-1].endswith(
        "Read it, then run `close.py free fix-typo review` from that worktree."
    )


def test_resume_asks_the_stopped_branch_not_the_moved_integration_target(tmp_path):
    """A resume re-enters an EXISTING tree, so the integration target is not where that
    tree came from either: a trunk that adopts the plugin after the stop would hand the
    successor — and every close leg — a path its own worktree has never had."""
    from test_spawn_resume import stopped_story

    repo, env, g, tree, _marker = stopped_story(tmp_path)
    g("checkout", "-q", "main")
    write_plugin_source(repo)
    g("add", "-A")
    assert g("commit", "-qm", "trunk adopts the plugin after the stop").returncode == 0
    g("checkout", "-q", "elsewhere")
    rec = stub_claude(tmp_path)
    rec.unlink()  # else the stopped spawn's own record answers for the resume's

    result = spawn(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert not (tree / "plugins").exists()
    assert str(SPAWN.parent / "work.py") in json.loads(rec.read_text())["stdin"]
    assert result.stdout.splitlines()[-1].endswith(
        "Read it, then run `close.py story story-042 review`."
    )
