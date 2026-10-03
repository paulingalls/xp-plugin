"""Completed native harness consumers with real commits and review legs."""

import subprocess

from plan_confirmation_support import consumer, events
from spawn_helpers import spawn


def completed(tmp_path, launch=spawn, harness="claude"):
    repo, env, seen = consumer(
        tmp_path, harness=harness, initial_status="clean", initial_question=None
    )
    (tmp_path / "executor-stop").unlink()
    binary = tmp_path / "bin" / harness
    text = binary.read_text()
    text = text.replace(
        "os.makedirs('src', exist_ok=True)",
        "os.makedirs('src', exist_ok=True)\n"
        " subprocess.run(['git', 'update-index', '--no-assume-unchanged', 'src/thing.py'])\n"
        " subprocess.run(['git', 'update-index', '--no-skip-worktree', 'src/thing.py'])",
    )
    text = text.replace(
        "open('src/thing.py', 'a').write('\\nDONE = True\\n')",
        "open('src/thing.py', 'a').write('\\nDONE = True\\nLEASE = ' + "
        "('17' if os.path.exists(" + repr(str(tmp_path / "value-change")) + ") else '1') + '\\n')",
    )
    text = text.replace(
        "event = {'role': role, 'prompt': prompt}",
        "event = {'role': role, 'prompt': prompt, 'source': __file__, "
        "'cwd': os.getcwd(), 'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], "
        "text=True).strip(), 'tree': subprocess.check_output(['git', 'rev-parse', "
        "'HEAD^{tree}'], text=True).strip()}",
    )
    binary.write_text(text)
    first = launch(repo, env, "story-042")
    assert first.returncode == 0, first.stderr
    return repo, env, seen


def git(tmp_path, *args):
    return subprocess.check_output(
        ["git", *args], cwd=tmp_path / "data/worktrees/story-042", text=True
    ).strip()


def roles(seen):
    return [event["role"] for event in events(seen)]


def damage(tmp_path, kind):
    tree = tmp_path / "data/worktrees/story-042"
    if kind in ("dirty", "staged", "untracked", "hidden", "ignored", "moved", "empty-commit"):
        path = tree / "src/thing.py"
        if kind == "hidden":
            git(tmp_path, "update-index", "--assume-unchanged", "src/thing.py")
        if kind in ("dirty", "staged", "hidden", "moved"):
            path.write_text(path.read_text() + "\nVALUE = 'changed'\n")
        elif kind in ("untracked", "ignored"):
            (tree / "runtime.cfg").write_text("preserved runtime")
            if kind == "ignored":
                exclude = subprocess.check_output(
                    ["git", "rev-parse", "--git-path", "info/exclude"], cwd=tree, text=True
                ).strip()
                with open(exclude, "a") as handle:
                    handle.write("\nruntime.cfg\n")
        if kind in ("staged", "moved"):
            git(tmp_path, "add", "src/thing.py")
        if kind in ("moved", "empty-commit"):
            git(tmp_path, "commit", "--allow-empty", "-qm", kind)
        return


def tier_consumer(tmp_path, command):
    repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    (tmp_path / "executor-stop").unlink()
    config = repo / ".xp/config.yml"
    config.write_text(config.read_text().replace("story: true", "story: " + command))
    subprocess.run(
        ["git", "commit", "-am", "tier variant"], cwd=repo, env=env, check=True, capture_output=True
    )
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
    return repo, env, seen


def hidden_handback(tmp_path):
    repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    (tmp_path / "executor-stop").unlink()
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src/thing.py").write_text("LEASE = 1\n")
    subprocess.run(["git", "add", "src/thing.py"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "tracked baseline"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)

    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "elif role == 'teammate':",
            "elif role == 'teammate':\n"
            " subprocess.run(['git', 'update-index', '--assume-unchanged', "
            "'src/thing.py'], check=True)\n"
            " open('src/thing.py', 'w').write('LEASE = 17\\n')\n"
            " open('src/other.py', 'w').write('OWN_COMMIT = True\\n')",
        )
    )
    return repo, env, seen
