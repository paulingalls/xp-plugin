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
    from test_close_free import carded_free_patch

    repo, env, g = carded_free_patch(tmp_path)
    branch = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    key = branch.split("/", 1)[1]
    g("checkout", "-q", "main")
    write_plugin_source(repo)
    g("add", "-A")
    assert g("commit", "-qm", "fixture plugin source").returncode == 0
    g("checkout", "-q", branch)
    assert g("merge", "-q", "main").returncode == 0
    stub_claude(tmp_path)

    result = spawn(repo, env, key)
    assert result.returncode == 0, result.stderr
    handback = result.stdout.splitlines()[-1]
    assert handback.endswith("close.py free fix-typo review` from that worktree.")
    assert "plugins/xp-plugin" not in handback


def test_a_branch_lacking_the_plugin_keeps_the_installed_root(tmp_path):
    """The free branch is cut before the plugin reaches the default branch, so its
    worktree has no plugins/ at all — the arm where a layout-derived root is a path
    that does not exist rather than merely the wrong one."""
    from test_close_free import carded_free_patch

    repo, env, g = carded_free_patch(tmp_path)
    branch = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    key = branch.split("/", 1)[1]
    g("checkout", "-q", "main")
    write_plugin_source(repo)
    g("add", "-A")
    assert g("commit", "-qm", "fixture plugin source").returncode == 0
    g("checkout", "-q", branch)
    rec = stub_claude(tmp_path)

    result = spawn(repo, env, key)
    assert result.returncode == 0, result.stderr
    assert not (Path(env["XP_DATA"]) / "worktrees" / key / "plugins").exists()
    assert str(SPAWN.parent / "work.py") in json.loads(rec.read_text())["stdin"]
    assert result.stdout.splitlines()[-1].endswith(
        "Read it, then run `close.py free fix-typo review` from that worktree."
    )


def test_a_resume_keeps_the_installed_root_after_trunk_adopts_a_plugin(tmp_path):
    """A resume re-enters a tree cut BEFORE trunk adopted the plugin, so the repository
    now ships plugins/xp-plugin while the successor's own worktree still does not."""
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
