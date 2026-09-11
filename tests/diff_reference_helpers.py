import re
import shlex
import subprocess

FULL_SHA = r"[0-9a-f]{40}"


def named_section(bundle, title):
    prefix = f"## {title}\n\n"
    start = bundle.index(prefix) + len(prefix)
    end = bundle.find("\n## ", start)
    return bundle[start:] if end < 0 else bundle[start:end]


def named_diff_argv(bundle, title):
    body = named_section(bundle, title)
    commands = re.findall(rf"^git diff ({FULL_SHA})\.\.({FULL_SHA})$", body, re.M)
    assert len(commands) == 1, f"expected one pinned diff command in {title!r}:\n{body}"
    base, head = commands[0]
    argv = shlex.split(f"git diff {base}..{head}")
    assert argv == ["git", "diff", f"{base}..{head}"]
    return argv


def read_named_diff(bundle, title, repo, env):
    return subprocess.run(
        named_diff_argv(bundle, title),
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
