"""Construct source motion inside real read-only CLI stages."""

import subprocess

from plan_confirmation_support import consumer, submodule_consumer
from spawn_helpers import set_system_md
from story_review_helpers import checkpoint, flow_repo, invoke


def plan_motion(tmp_path, launch, kind, role="plan-reviewer"):
    if kind.startswith("submodule"):
        repo, env, seen = submodule_consumer(tmp_path, "claude")
        path = "vendor/.xp/system.md"
        bootstrap = "git -c protocol.file.allow=always submodule update --init"
    else:
        repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
        (tmp_path / "executor-stop").unlink()
        path, bootstrap = ".xp/system.md", "true"
    if kind in ("dirty", "submodule-dirty"):
        bootstrap += f" && printf before >> {path}"
    if kind == "binary":
        path = "binary.bin"
        bootstrap += (
            " && printf '\\000\\377' > binary.bin && git add binary.bin && git commit -qm binary"
        )
    if kind == "arrangement":
        bootstrap += f" && printf before >> {path} && git add {path} && printf dirty >> {path}"
    if kind == "addition":
        path = "added.py"
        bootstrap += " && printf before > added.py && git add added.py && printf dirty >> added.py"
    if kind in ("hidden", "skip"):
        flag = "--skip-worktree" if kind == "skip" else "--assume-unchanged"
        prefix, tracked = (
            ("git -C vendor", ".xp/system.md") if kind.startswith("submodule") else ("git", path)
        )
        bootstrap += f" && {prefix} update-index {flag} {tracked}"
    set_system_md(repo, f"- Worktree bootstrap: `{bootstrap}`")
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
    binary = tmp_path / "bin/claude"
    action = f" open({path!r}, 'a').write('after')\n"
    if kind == "binary":
        action = f" open({path!r}, 'ab').write(b'\\x00\\xffafter')\n"
    if kind in ("index", "arrangement"):
        action += f" subprocess.run(['git', 'add', {path!r}], check=True)\n"
    if kind == "arrangement":
        action += f" open({path!r}, 'a').write('after')\n"
    if kind == "head":
        action += " subprocess.run(['git', 'commit', '-qam', 'reviewer edit'], check=True)\n"
    if kind == "submodule-gitlink":
        action = (
            " subprocess.run(['git', '-C', 'vendor', 'commit', '--allow-empty', '-qm', "
            "'gitlink motion'], check=True)\n"
            " subprocess.run(['git', 'add', 'vendor'], check=True)\n"
        )
    binary.write_text(
        binary.read_text()
        .replace(
            f"{'if' if role == 'planner' else 'elif'} role == {role!r}:",
            f"{'if' if role == 'planner' else 'elif'} role == {role!r}:\n" + action,
        )
        .replace(
            "human_question': 'Which lease value does the human authorize?'",
            "human_question': None",
        )
    )
    result = launch(repo, env, "story-042")
    assert result.returncode == 2, result.stderr
    from completed_executor_support import roles

    assert "teammate" not in roles(seen)
    tree = tmp_path / "data/worktrees/story-042"
    if kind == "submodule-gitlink":
        assert subprocess.check_output(["git", "diff", "--cached", "--", "vendor"], cwd=tree)
    else:
        assert (tree / path).read_bytes().endswith(b"after")


def review_motion(tmp_path, kind):
    repo, env, git, key, seen, _ = flow_repo(tmp_path)
    path = "src/thing.py"
    import os
    import shutil
    from pathlib import Path

    import pytest
    from plan_review_install import PLUGIN

    if kind.startswith("submodule"):
        dependency = tmp_path / "dependency"
        dependency.mkdir()
        subprocess.run(["git", "init", "-q", str(dependency)], env=env, check=True)
        (dependency / "source.py").write_text("before")
        subprocess.run(["git", "add", "."], cwd=dependency, env=env, check=True)
        subprocess.run(["git", "commit", "-qm", "dependency"], cwd=dependency, env=env, check=True)
        assert (
            git(
                "-c", "protocol.file.allow=always", "submodule", "add", str(dependency), "vendor"
            ).returncode
            == 0
        )
        assert git("commit", "-qam", "tracked dependency").returncode == 0
        path = "vendor/source.py"
    inherited = Path(os.environ.get("XP_FLOW_TEST_CLOSE", str(PLUGIN / "scripts/close.py")))
    installed = tmp_path / "review-plugin"
    shutil.copytree(inherited.parent.parent, installed)
    if kind == "binary":
        (repo / path).write_bytes(b"\x00\xffbefore")
        assert git("commit", "-qam", "binary source").returncode == 0
    if kind in ("dirty", "addition", "submodule-dirty", "arrangement"):
        path = "added.py" if kind == "addition" else path
        target = installed / "scripts/close/review_sequence.py"
        old = "    before = measure(story_id, card)"
        bootstrap = f"    Path({path!r}).write_text('before')\n"
        if kind in ("addition", "arrangement"):
            bootstrap += f"    close.git('add', {path!r})\n    Path({path!r}).write_text('dirty')\n"
        text = target.read_text()
        assert old in text
        target.write_text(text.replace(old, bootstrap + old))
    if kind in ("hidden", "skip"):
        flag = "--skip-worktree" if kind == "skip" else "--assume-unchanged"
        arguments = (
            ["-C", "vendor", "update-index", flag, "source.py"]
            if kind.startswith("submodule")
            else ["update-index", flag, path]
        )
        assert git(*arguments).returncode == 0
    binary = tmp_path / "bin/claude"
    action = f"\nPath({path!r}).write_text('after')\n"
    if kind == "binary":
        action = f"\nPath({path!r}).write_bytes(b'\\x00\\xffafter')\n"
    if kind in ("index", "arrangement"):
        action += f"subprocess.run(['git','add',{path!r}],check=True)\n"
    if kind == "arrangement":
        action += f"Path({path!r}).write_text('afterafter')\n"
    if kind == "head":
        action += "subprocess.run(['git','commit','-qam','reviewer edit'],check=True)\n"
    if kind == "submodule-gitlink":
        action = (
            "\nsubprocess.run(['git','-C','vendor','commit','--allow-empty','-qm',"
            "'gitlink motion'],check=True)\n"
            "subprocess.run(['git','add','vendor'],check=True)\n"
        )
    binary.write_text(
        binary.read_text().replace("report={'blocking':[]}", "report={'blocking':[]}" + action)
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
        result = invoke(repo, env, key)
    assert result.returncode == 2, result.stderr
    assert checkpoint(env, key)["status"] == "blocked"
    if kind == "submodule-gitlink":
        assert git("diff", "--cached", "--", "vendor").stdout
    else:
        assert (repo / path).read_bytes() == (
            b"afterafter"
            if kind == "arrangement"
            else b"\x00\xffafter"
            if kind == "binary"
            else b"after"
        )
    assert seen.read_text().splitlines() == ["solution"]
