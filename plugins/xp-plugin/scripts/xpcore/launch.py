"""Launch a headless agent: build its argv, stream it live, tee it verbatim to a log."""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from xpcore import config, gitx

INSTALL = {"claude": "https://claude.com/product/claude-code", "codex": "npm i -g @openai/codex"}
SANDBOXES = {
    "danger-full-access": "no OS confinement; network, docker and nested harnesses reachable",
    "workspace-write": "no outbound network (DNS, loopback, docker); --add-dir grants paths only",
}
# Headless claude kills backgrounded tasks at exit, and its default Bash bound
# (2 minutes) kills a project's long test command mid-run.
CLAUDE_ENV = {
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
    "BASH_DEFAULT_TIMEOUT_MS": str(4 * 3600 * 1000),
    "BASH_MAX_TIMEOUT_MS": str(4 * 3600 * 1000),
}
LIVE: set[subprocess.Popen] = set()


def missing_harness(harness: str) -> str:
    if shutil.which(harness):
        return ""
    return (
        f"{harness} is not on PATH; install it ({INSTALL.get(harness, harness)}) or change the role"
    )


def agent_argv(harness: str, model: str, effort: str, sandbox: str = "") -> list[str]:
    if harness == "claude":
        # Bypass even for reviewers: under acceptEdits headless claude denies Bash and
        # out-of-tree writes, then exits 0 with nothing written. stream-json needs --verbose.
        argv = ["claude", "-p", "--plugin-dir", str(config.plugin_root())]
        argv += ["--dangerously-skip-permissions", "--output-format", "stream-json", "--verbose"]
        return argv + ["--model", model] + (["--effort", effort] if effort else [])
    if harness != "codex":
        config.refuse(f"unknown harness {harness!r}; use claude or codex in the role")
    argv = ["codex", "exec", "--json"]
    # The plugin's env (XP_ROLE, XP_STORY_ID) must reach the agent's shell, and any of
    # these three ~/.codex/config.toml keys can strip it. Default excludes stay: they
    # drop *KEY*/*SECRET*/*TOKEN*, none of which we need.
    for pin in ("inherit=all", "exclude=[]", "include_only=[]"):
        argv += ["-c", f"shell_environment_policy.{pin}"]
    argv += ["--sandbox", sandbox or "danger-full-access", "--add-dir", str(config.data_root())]
    argv += ["-m", model]
    if effort:  # codex has no effort flag; the config key is the only spelling
        argv += ["-c", f"model_reasoning_effort={effort}"]
    return [*argv, "-"]  # `-` reads the prompt from stdin, keeping it out of `ps`


def codex_widening(cwd: Path) -> list[str]:
    """A linked worktree keeps its refs and objects in the main repo's git dir, outside
    the workspace codex may write, so committing there needs that dir granted too."""
    try:
        common = gitx.common_dir(cwd)
    except gitx.GitError:
        return []
    return [] if common.is_relative_to(Path(cwd).resolve()) else ["--add-dir", str(common)]


def sandbox_line(argv: list[str]) -> str:
    """Read back off the argv actually launched, so the printed posture cannot drift from it."""
    if "--sandbox" not in argv:
        return ""
    posture = argv[argv.index("--sandbox") + 1]
    return f"codex sandbox: {posture}: {SANDBOXES.get(posture, 'as codex defines it')}"


def event(line: str) -> dict | None:
    try:
        evt = json.loads(line)
    except ValueError:
        return None
    return evt if isinstance(evt, dict) else None


def parse_claude(line: str) -> tuple[str | None, dict | None]:
    """(compact echo, the terminal result event if this is it) for one stream-json line."""
    if (evt := event(line)) is None:
        return None, None
    kind = evt.get("type", "?")
    if kind in ("assistant", "user"):
        blocks = (evt.get("message") or {}).get("content") or []
        return (
            f"[{kind}] {','.join(b.get('type', '?') for b in blocks if isinstance(b, dict))}",
            None,
        )
    if kind == "result":
        status = "error" if evt.get("is_error") else "ok"
        ms, cost = evt.get("duration_ms"), evt.get("total_cost_usd")
        extra = f" {evt.get('num_turns', '?')} turns"
        extra += f" {ms / 1000:.0f}s" if isinstance(ms, int | float) else ""
        extra += f" ${cost:.2f}" if isinstance(cost, int | float) else ""
        return f"[result] {status}{extra}", evt
    return f"[{kind}] {evt.get('subtype', '')}".rstrip(), None


def parse_codex(line: str) -> tuple[str | None, dict | None]:
    """Codex has no result envelope: the last completed agent_message is the answer."""
    if (evt := event(line)) is None:
        return None, None
    item = evt.get("item") if isinstance(evt.get("item"), dict) else {}
    done = evt.get("type") == "item.completed" and item.get("type") == "agent_message"
    return f"[{evt.get('type', '?')}] {item.get('type', '')}".rstrip(), evt if done else None


PARSERS: dict[str, Callable[[str], tuple[str | None, dict | None]]] = {
    "claude": parse_claude,
    "codex": parse_codex,
}


def result_text(harness: str, result: dict) -> str:
    if harness == "claude":
        return str(result.get("result", ""))
    return str((result.get("item") or {}).get("text", ""))


def session_id(harness: str, line: str) -> str:
    evt = event(line) or {}
    return str(evt.get("session_id" if harness == "claude" else "thread_id") or "")


def transcript_path(harness: str, cwd: Path, session: str) -> str:
    """A pointer at the harness's own, richer transcript. Codex names its file after a
    start time we never see, and may not have written it yet, so a miss names the search."""
    home = Path.home()
    if harness == "claude":
        slug = "-" + str(Path(cwd).resolve()).lstrip("/").replace("/", "-").replace(".", "-")
        return str(home / ".claude" / "projects" / slug / f"{session}.jsonl")
    root = home / ".codex" / "sessions"
    found = next(root.rglob(f"rollout-*-{session}.jsonl"), None) if root.is_dir() else None
    return str(found) if found else f"(not written yet) {root}/*/*/*/rollout-*-{session}.jsonl"


def tee(lines: Iterable[str], log, out, harness: str, cwd: Path) -> dict | None:
    """Drain every line whatever the log does: a child blocked on a full pipe never exits."""
    parse, result, pointed = PARSERS[harness], None, False
    for line in lines:
        try:
            log.write(line)
            if not pointed and (session := session_id(harness, line.strip())):
                log.write(f"transcript: {transcript_path(harness, cwd, session)}\n")
                pointed = True
            log.flush()
        except (OSError, ValueError) as exc:
            out(f"warning: log write failed ({exc}); continuing without it")
        echo, evt = parse(line.strip()) if line.strip() else (None, None)
        if echo is not None:
            out(echo)
        if evt is not None:
            result = evt
    return result


def kill_group(proc: subprocess.Popen) -> None:
    """The whole session, not the leader: the agent's children hold the stdout pipe too."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()


def kill_live() -> None:
    """Ctrl-C reaches the main thread only; agents run on worker threads must be killed here."""
    for proc in list(LIVE):
        kill_group(proc)


def _feed(proc: subprocess.Popen, prompt: str) -> None:
    # Its own thread: a prompt larger than the pipe buffer deadlocks against a child
    # that writes before it finishes reading. A child that dies early breaks the pipe.
    assert proc.stdin is not None
    with contextlib.suppress(BrokenPipeError):
        try:
            proc.stdin.write(prompt)
        finally:
            proc.stdin.close()


def run_agent(
    role: str, prompt: str, cwd: Path, log_id: str, *, override: str = "", env=None
) -> subprocess.CompletedProcess:
    """Run `role` to completion with no wall clock; `.stdout` is its final answer.
    Log ids read `<story-id>-<role>[-suffix]`; XP_STORY_ID derives from that unless given."""
    harness, model, effort = config.role(role, override)
    if missing := missing_harness(harness):
        config.refuse(missing)
    sandbox = ""
    if harness == "codex":
        sandbox = str(config.load_config().get("codex_sandbox") or "danger-full-access")
        if sandbox not in SANDBOXES:
            config.refuse(f"codex_sandbox {sandbox!r}; set it to {' or '.join(SANDBOXES)}")
    argv = agent_argv(harness, model, effort, sandbox)
    if harness == "codex":
        argv = [*argv[:-1], *codex_widening(cwd), argv[-1]]
    if posture := sandbox_line(argv):
        print(posture, file=sys.stderr)
    extra = dict(env or {})
    child_env = (CLAUDE_ENV if harness == "claude" else {}) | os.environ | extra
    child_env |= {
        "XP_ROLE": role,
        "XP_STORY_ID": extra.get("XP_STORY_ID") or log_id.split(f"-{role}")[0],
        "XP_HARNESS": harness,
    }
    path = config.data_root() / "logs" / f"{log_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"live log: {path}", file=sys.stderr)
    with open(path, "a") as log:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        log.write(f"===== {log_id} {role} {harness}/{model} {stamp} =====\n")
        log.flush()
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=child_env,
            start_new_session=True,  # Ctrl-C stays ours; kill_group gets a group of its own
        )
        LIVE.add(proc)
        feeder = threading.Thread(target=_feed, args=(proc, prompt), daemon=True)
        feeder.start()
        try:
            assert proc.stdout is not None
            result = tee(proc.stdout, log, print, harness, Path(cwd))
        except BaseException:
            kill_group(proc)
            raise
        finally:
            feeder.join()
            proc.wait()
            LIVE.discard(proc)
    rc = proc.returncode
    if result is None:
        print(f"{log_id}: the stream carried no final result; read {path}", file=sys.stderr)
        rc = rc or 1
    elif result.get("is_error"):
        rc = rc or 1
    text = result_text(harness, result) if result else ""
    return subprocess.CompletedProcess(argv, rc, text, "" if rc == 0 else f"see {path}")
