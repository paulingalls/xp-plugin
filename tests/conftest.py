"""Git exports GIT_DIR to hook subprocesses; a worktree exports an ABSOLUTE path, so
any inherited git call would run against the real index with the fixture as its
work tree. Stripped once here so every test's fixture repo is its own."""

import os
import sys
from pathlib import Path

import pytest

for _var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "XP_AGENT"):
    os.environ.pop(_var, None)

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"))


@pytest.fixture
def fake_retro(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    bin_ = tmp_path / "retro-bin"
    bin_.mkdir()
    script = """#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
prompt = sys.stdin.read()
Path(os.environ["HOME"], "retro-prompt").write_text(prompt)
Path(os.environ["HOME"], "retro-argv").write_text(" ".join(sys.argv))
path = re.search(r"- RETRO_PATH: (.+)", prompt)[1]
markdown = "## Misses\\nNone\\n## Sightings\\nNone\\n## Proposals\\nNone\\n"
if not os.environ.get("RETRO_MISSING"):
    Path(path).write_text(os.environ.get("RETRO_MARKDOWN", markdown))
content = [{"type":"text","text":"PRIVATE NARRATIVE"}]
print(json.dumps({"type":"assistant","message":{"content":content}}))
result = os.environ.get("RETRO_RESULT", '{"sightings":[],"proposals":[]}')
print(json.dumps({"type":"result","result":result}))
sys.exit(int(os.environ.get("RETRO_EXIT", "0")))
"""
    for harness in ("claude", "codex"):
        path = bin_ / harness
        path.write_text(script)
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    return home
