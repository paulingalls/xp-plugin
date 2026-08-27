"""story-059: self-hosting spawn executes the plugin tree under review."""

import json
from pathlib import Path

from spawn_helpers import SPAWN, make_repo, spawn, stub_claude


def test_consuming_project_keeps_installed_root_and_output(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    assert not (repo / "plugins" / "xp-plugin").exists()
    rec = stub_claude(tmp_path)
    result = spawn(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    assert str(SPAWN.parent / "work.py") in json.loads(rec.read_text())["stdin"]
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


def test_self_hosting_commands_execute_and_disclose_worktree_root(tmp_path):
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
    worktree_plugin = tree / "plugins" / "xp-plugin"
    assert (tree / "executed-plugin-script").read_text() == str(
        (worktree_plugin / "scripts" / "work.py").resolve()
    )
    handback = result.stdout.splitlines()[-1]
    assert "for every close.py leg" in handback
    assert f"python3 {worktree_plugin}/scripts/close.py story story-042 review" in handback
    assert "xp-plugin 9.8.7" in handback


def test_self_hosting_free_leg_still_names_the_worktree_it_must_run_from(tmp_path):
    """`close.py free` reads its branch off HEAD and spawn moves the lead to trunk,
    so the long spelling drops the lead onto a checkout that refuses the leg."""
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
    assert "for every close.py leg" in handback
    assert handback.endswith("close.py free fix-typo review` from that worktree.")
