"""Completed native harness consumers with real commits and review legs."""

import json
import subprocess

from plan_confirmation_support import consumer, events
from spawn_helpers import SPAWN, spawn


def completed(tmp_path, launch=spawn, harness="claude", implementation="complete"):
    repo, env, seen = consumer(
        tmp_path, harness=harness, initial_status="clean", initial_question=None, status="clean"
    )
    (tmp_path / "executor-stop").unlink()
    binary = tmp_path / "bin" / harness
    text = binary.read_text().replace(
        "'decision': 'confirm'", f"'decision': 'confirm', 'implementation': {implementation!r}"
    )
    text = text.replace("'summary': ''", "'summary': 'Actual code satisfies the final candidate.'")
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


def amendment(tmp_path, repo, env, launch=spawn, change=None):
    path = tmp_path / "data/plan.md"
    text = path.read_text()
    path.write_text(
        change(text)
        if change
        else text.replace("Verify: true", "Verify: true && test -f src/thing.py").replace(
            "Files: src/thing.py, src/other.py",
            "Files: src/thing.py, src/other.py, tests/evidence.py",
        )
    )
    result = launch(repo, env, "amend", "story-042", "--reason", "current evidence")
    assert result.returncode == 0, result.stderr


def state(tmp_path):
    return json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())


def git(tmp_path, *args):
    return subprocess.check_output(
        ["git", *args], cwd=tmp_path / "data/worktrees/story-042", text=True
    ).strip()


def roles(seen):
    return [event["role"] for event in events(seen)]


def rewrite_state(tmp_path, change):
    path = tmp_path / "data/plans/story-042.handoff.json"
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value))


def replacement(tmp_path):
    (tmp_path / "replace").touch()


def damage(tmp_path, kind):
    if kind in ("executor-failed", "tier-failed", "tier-skipped", "executor-absent"):
        stage = "executor" if kind.startswith("executor-") else "story-tier"
        result = kind.split("-", 1)[1]
        rewrite_state(
            tmp_path,
            lambda value: (
                value["stages"].pop(stage)
                if result == "absent"
                else value["stages"].update({stage: result})
            ),
        )
        return
    if kind == "missing-close-marker":
        (tmp_path / "data/markers/story-042.close.json").unlink()
        return
    if kind in ("assume-bound", "skip-bound"):
        import sys

        damage(tmp_path, "hidden")
        if kind == "skip-bound":
            git(tmp_path, "update-index", "--no-assume-unchanged", "src/thing.py")
            git(tmp_path, "update-index", "--skip-worktree", "src/thing.py")
        plan = state(tmp_path)["completion"]["acceptance"]["plan"]
        program = (
            f"import sys, json; from pathlib import Path; sys.path[:0] = "
            f"[{str(SPAWN.parent)!r}, {str(SPAWN.parent / 'spawn')!r}]; "
            "from plan_confirmation import repository_fingerprint; "
            f"print(json.dumps(repository_fingerprint(Path({plan!r}))))"
        )
        fingerprint = json.loads(
            subprocess.check_output(
                [sys.executable, "-c", program],
                cwd=tmp_path / "data/worktrees/story-042",
                text=True,
            )
        )
        rewrite_state(tmp_path, lambda value: value["completion"].update(fingerprint=fingerprint))
        return
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

    def alter(value):
        completion = value["completion"]
        if kind == "absent":
            del value["completion"]
        elif kind == "empty":
            value["completion"] = {}
        elif kind == "shape":
            value["completion"] = []
        elif kind == "version":
            completion["version"] = True
        elif kind == "card-shape":
            completion["card"] = None
        elif kind == "card":
            completion["card"] = completion["card"].replace("Context: demo.", "Context: unrelated.")
        elif kind in (
            "story_id",
            "repository",
            "head",
            "tree",
            "start_head",
            "plan",
            "findings",
        ):
            completion[kind] = "different"
        elif kind == "fingerprint":
            completion["fingerprint"]["identity"] = "different"
        elif kind == "credential":
            completion["credential"]["digest"] = "different"
        elif kind == "acceptance":
            completion["acceptance"]["digest"] = "different"
        elif kind == "review-evidence":
            completion["review_evidence"]["acceptance"] = {}
        elif kind == "forged-gate":
            completion["gates"]["tier"] = "echo forged"
        elif kind == "tier":
            completion["gates"]["tier"] = "EDIT-ME"
        else:
            raise AssertionError(kind)

    rewrite_state(tmp_path, alter)


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


def refusal_fault(diagnostic):
    import ast
    import re

    from plan_review_install import PLUGIN

    source = (PLUGIN / "scripts/spawn/completion.py").read_text()
    candidates = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if not isinstance(node.exc.func, ast.Name) or node.exc.func.id != "ValueError":
                continue
            value, replacement = node.exc.args[0], "pass"
        elif isinstance(node, ast.Return):
            value, replacement = node.value, 'return ""'
            if isinstance(value, ast.IfExp):
                value = value.body
        else:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:
            pattern, score = re.escape(value.value), 0
        elif isinstance(value, ast.JoinedStr):
            score = sum(isinstance(part, ast.FormattedValue) for part in value.values)
            pattern = "".join(
                re.escape(part.value) if isinstance(part, ast.Constant) else ".*?"
                for part in value.values
            )
        else:
            continue
        if re.search(pattern, diagnostic):
            candidates.append((score, ast.get_source_segment(source, node), replacement))
    assert candidates, diagnostic
    best = min(candidate[0] for candidate in candidates)
    matches = [candidate[1:] for candidate in candidates if candidate[0] == best]
    assert len(matches) == 1, matches
    return matches[0]
