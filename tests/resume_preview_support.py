"""Installed resume previews compared with live launches and complete state."""

import json
import re


def compare_prompt(repo, env, seen, launch):
    from plan_confirmation_support import events

    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    live = launch(repo, env, "resume", "story-042")
    assert live.returncode == 0, live.stderr
    event = next(e for e in events(seen) if e["role"] == "teammate")
    prompt = event["prompt"]
    assert "## Current plan review\n" in preview.stdout, "Current plan review missing from preview"
    assert preview.stdout.endswith(prompt + "\n")
    assert preview.stdout.splitlines()[1].split(" ", 1)[1] == " ".join(event["argv"])
    assert re.search(r"profile: total \d+ tokens", preview.stdout).group() in live.stdout


def preview_fixture(tmp_path, **kwargs):
    from plan_confirmation_support import consumer
    from plan_review_install import installed_launch

    repo, env, seen = consumer(tmp_path, initial_question=None, **kwargs)
    binary = tmp_path / "bin" / kwargs.get("harness", "claude")
    binary.write_text(
        binary.read_text().replace(
            "event = {'role': role, 'prompt': prompt}",
            "event = {'role': role, 'prompt': prompt, 'argv': sys.argv[1:]}",
        )
    )
    launch = installed_launch(tmp_path)
    stopped = launch(repo, env, "story-042")
    assert stopped.returncode != 0 and "Traceback" not in stopped.stderr, stopped.stderr
    (tmp_path / "executor-stop").unlink()
    return repo, env, seen, launch


def snapshot(root):
    import stat

    result = {}
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        contents = (
            path.readlink()
            if path.is_symlink()
            else (path.read_bytes() if stat.S_ISREG(mode) else None)
        )
        result[str(path.relative_to(root))] = (
            mode,
            contents,
            path.lstat().st_mtime_ns,
            path.lstat().st_ctime_ns,
        )
    return result


def restorable(tmp_path):
    path = tmp_path / "data/plans/story-042.handoff.json"
    state = json.loads(path.read_text())
    state.pop("plan_review_identity")
    state["stages"]["plan-reviewer"] = "failed"
    path.write_text(json.dumps(state))


def damage_findings(tmp_path, damage):
    path = tmp_path / "data/plans/story-042.round-1.md"
    if damage == "missing":
        path.unlink()
    elif damage == "unreadable":
        path.chmod(0)
    elif damage == "empty":
        path.write_text("")
    elif damage == "non-utf8":
        path.write_bytes(b"\xff")
    elif damage == "changed":
        path.write_text(path.read_text() + "changed")
    elif damage == "plan":
        path.with_name("story-042.plan.md").write_text("changed plan")
    elif damage == "stale":
        old = path.with_name("story-042.round-2.md")
        old.write_text(json.dumps(dict(status="clean", human_question=None, reasons=[])))
        marker = path.with_name("story-042.handoff.json")
        state = json.loads(marker.read_text())
        state["plan_review_findings"] = str(old)
        marker.write_text(json.dumps(state))


def assert_refusal(preview, live, seen, before):
    from plan_confirmation_support import events

    assert preview.returncode != 0, preview.stdout
    assert live.returncode != 0, live.stdout
    reason = preview.stderr.strip()
    assert reason in live.stderr, (reason, live.stderr)
    assert events(seen) == before
