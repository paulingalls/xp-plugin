import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import xp
from test_free_post_merge import publish_merge
from test_land import CONFIG, commit, free_patch, git, make_project, story  # noqa: F401
from test_records import refused
from test_sprint import merge_on_trunk
from test_sprint import repo as sprint_repo  # noqa: F401
from test_story import repo as story_repo  # noqa: F401
from xpcore import cards


def fake_github(tmp_path, monkeypatch, data, record):
    binary = tmp_path / "bin"
    binary.mkdir(exist_ok=True)
    store = tmp_path / "github.json"
    store.write_text(json.dumps({"calls": [], "closed": [], "merged": [], "comments": []}))
    gh = binary / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + f"STORE = {str(store)!r}\n"
        + f"RECORD = {str(data / record)!r}\n"
        + """import json, os, sys
from pathlib import Path
args = sys.argv[1:]
p = Path(STORE)
s = json.loads(p.read_text())
s['calls'].append(args)
p.write_text(json.dumps(s))
if args[:2] == ['pr', 'create'] or args[:2] == ['auth', 'status']:
    sys.exit(0)
if args[:2] == ['issue', 'view']:
    print(json.dumps({'labels': []}))
    sys.exit(0)
if args[:2] == ['issue', 'edit'] and '--body-file' in args:
    s['published'] = s.get('published', []) + [args[2]]
    p.write_text(json.dumps(s))
    sys.exit(0)
assert Path(RECORD).is_file(), 'issue update preceded release record'
if args[:2] == ['issue', 'close'] or args[:2] == ['issue', 'comment']:
    assert Path(RECORD).read_text().find(args[-1].split()[-1]) >= 0
if os.environ.get('GH_FAIL') == ' '.join(args[:3]):
    sys.exit('network unavailable')
if args[:2] == ['issue', 'close']:
    s['closed'].append(args[2])
elif args[:2] == ['issue', 'edit']:
    s['merged'].append(args[2])
elif args[:2] == ['issue', 'comment']:
    s['comments'].append(args[2])
elif args[:2] != ['label', 'create']:
    sys.exit('unexpected gh command')
p.write_text(json.dumps(s))
"""
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary}{os.pathsep}{os.environ['PATH']}")
    return store


@pytest.mark.parametrize(
    "fields", ["", "Issue: #224\n", "Issue: #224\nEvidence: touch forbidden\n"]
)
def test_free_shared_completion(tmp_path, monkeypatch, capsys, fields):
    root, data, wt = free_patch(tmp_path, monkeypatch)
    path = data / "plan.md"
    path.write_text(path.read_text() + fields)
    store = fake_github(tmp_path, monkeypatch, data, "landed.jsonl")
    git(root, "branch", "-m", "main", "develop")
    config = (wt / ".xp/config.yml").read_text().replace("main", "develop")
    if not fields:
        config += "github_issues: on\n"
    commit(wt, {".xp/config.yml": config}, "trunk")
    commit(root, {".xp/config.yml": (wt / ".xp/config.yml").read_text()}, "trunk config")
    git(root, "push", "-q", "origin", "develop")
    assert xp.main(["free", "land", "fix"]) == 0
    body = json.loads(store.read_text())["calls"][0][-1]
    assert "Closes #" not in body and "Refs #" not in body
    assert len(json.loads(store.read_text())["calls"]) == 1
    git(root, "merge", "-q", "--no-ff", "free-fix-x", "-m", "PR")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "push", "-q", "origin", "develop")
    assert xp.main(["free", "post-merge", "fix", "--dry-run"]) == 0
    assert len(json.loads(store.read_text())["calls"]) == 1
    assert xp.main(["free", "post-merge", "fix"]) == 0
    s = json.loads(store.read_text())
    evidence, issue = "Evidence:" in fields, "Issue:" in fields
    assert s["closed"] == (["224"] if issue and not evidence else [])
    assert s["merged"] == (["224"] if evidence else [])
    assert s["comments"] == (["224"] if evidence else [])
    assert not (root / "forbidden").exists()
    assert cards.find_card("free-fix").status == "done" and not wt.exists()
    assert not git(root, "branch", "--list", "free-fix-x")
    assert json.loads((data / "landed.jsonl").read_text())["merge"] == sha
    before = store.read_text()
    assert "closed already" in refused(capsys, ["free", "post-merge", "fix"])
    assert store.read_text() == before


@pytest.mark.parametrize("failure", [None, "issue close 224", "issue comment 225"])
def test_sprint_shared_completion(sprint_repo, tmp_path, monkeypatch, capsys, failure):  # noqa: F811
    root, data, hooklog = sprint_repo
    path = data / "plan.md"
    path.write_text(
        path.read_text() + "Issue: #224\n"
        "#### story-002 — read   [done]\nIssue: #225\nEvidence: touch forbidden\n"
        "#### story-003 — later   [planned]\nIssue: #226\n"
        "#### story-004 — dropped   [retired]\nIssue: #227\n"
        "## Sprint 2\n#### story-005 — other   [done]\nIssue: #228\n"
        "## Free\n#### free-other — other   [done]\nIssue: #229\n"
    )
    store = fake_github(tmp_path, monkeypatch, data, "sprints/1/release.json")
    assert xp.main(["sprint", "land", "1"]) == 0
    body = json.loads(store.read_text())["calls"][0][-1]
    assert "Closes #" not in body and "Refs #" not in body
    merge_on_trunk(root)
    assert xp.main(["sprint", "post-merge", "1", "--dry-run"]) == 0
    assert len(json.loads(store.read_text())["calls"]) == 1
    if failure:
        monkeypatch.setenv("GH_FAIL", failure)
        err = refused(capsys, ["sprint", "post-merge", "1"])
        assert "network unavailable" in err
        monkeypatch.delenv("GH_FAIL")
        for command in err.split("Finish manually:\n")[1].strip().splitlines():
            subprocess.run(shlex.split(command), check=True)
    else:
        assert xp.main(["sprint", "post-merge", "1"]) == 0
    s = json.loads(store.read_text())
    assert s["closed"] == ["224", "227"] and s["merged"] == ["225"] and s["comments"] == ["225"]
    retired = next(c for c in s["calls"] if c[:3] == ["issue", "close", "227"])
    assert retired[3:5] == ["--reason", "not planned"]
    assert not (root / "forbidden").exists() and hooklog.read_text() == "ran\n"
    assert not git(root, "branch", "--list", "sprint-1")
    before = store.read_text()
    refused(capsys, ["sprint", "post-merge", "1"])
    assert store.read_text() == before


@pytest.mark.parametrize(
    "failure", ["issue close 224", "label create merged", "issue edit 224", "issue comment 224"]
)
def test_issue_failure_names_remaining_commands(tmp_path, monkeypatch, capsys, failure):
    root, data, wt = free_patch(tmp_path, monkeypatch)
    fields = "Issue: #224\n" + ("Evidence: true\n" if failure != "issue close 224" else "")
    path = data / "plan.md"
    path.write_text(path.read_text() + fields)
    store = fake_github(tmp_path, monkeypatch, data, "landed.jsonl")
    assert xp.main(["free", "land", "fix"]) == 0
    sha = publish_merge(root)
    monkeypatch.setenv("GH_FAIL", failure)
    err = refused(capsys, ["free", "post-merge", "fix"])
    assert "#224" in err and "network unavailable" in err
    calls = json.loads(store.read_text())["calls"]
    assert shlex.join(["gh", *calls[-1]]) in err
    assert sha in err
    if failure in ["label create merged", "issue edit 224"]:
        assert "gh issue comment 224 --body" in err
    if failure == "label create merged":
        assert "gh issue edit 224 --add-label merged" in err
    assert cards.find_card("free-fix").status == "done" and not wt.exists()
    monkeypatch.delenv("GH_FAIL")
    for command in err.split("Finish manually:\n")[1].strip().splitlines():
        subprocess.run(shlex.split(command), check=True)
    s = json.loads(store.read_text())
    assert s["closed"] == (["224"] if failure == "issue close 224" else [])
    assert s["comments"] == ([] if failure == "issue close 224" else ["224"])


@pytest.mark.parametrize("on", [False, True])
def test_story_land_republishes_only_when_on(story, tmp_path, monkeypatch, on):  # noqa: F811
    root, data, _, _ = story
    store = fake_github(tmp_path, monkeypatch, data, "landed.jsonl")
    path = data / "plan.md"
    path.write_text(path.read_text() + "Issue: #224\n")
    config = (root / ".xp/config.yml").read_text() + ("github_issues: on\n" if on else "")
    commit(root, {"merged.txt": "ok\n", ".xp/config.yml": config}, "sprint work")
    assert xp.main(["story", "land", "story-001"]) == 0
    calls = json.loads(store.read_text())["calls"]
    edits = [c for c in calls if c[:3] == ["issue", "edit", "224"]]
    assert (edits[0][3] == "--title") if on else not calls
    body = git(root, "log", "-1", "--format=%B")
    assert "Closes #" not in body and "Refs #" not in body


def test_sprint_open_republishes_slate_cards(tmp_path, monkeypatch):
    root, data = make_project(tmp_path, monkeypatch, CONFIG + "github_issues: on\n")
    (data / "plan.md").write_text(
        "## Sprint 1 — s\n\n#### story-001 — a   [planned]\nAcceptance: true\nIssue: #224\n"
        "#### story-002 — b   [planned]\nAcceptance: true\n"
        "## Free\n#### free-x — x   [planned]\nIssue: #225\n"
    )
    store = fake_github(tmp_path, monkeypatch, data, "landed.jsonl")
    git(root, "switch", "-qc", "sprint-1")
    assert xp.main(["sprint", "open", "1"]) == 0
    assert json.loads(store.read_text())["published"] == ["224"]


def test_story_start_republishes_in_progress(story_repo, tmp_path, monkeypatch):  # noqa: F811
    data, root = story_repo, Path.cwd()
    (root / ".xp/config.yml").write_text(
        (root / ".xp/config.yml").read_text() + "github_issues: on\n"
    )
    git(root, "commit", "-qam", "share")
    path = data / "plan.md"
    path.write_text(
        path.read_text().replace(
            "One file   [planned]\nFiles: a.py\n",
            "One file   [planned]\nFiles: a.py\nIssue: #224\n",
        )
    )
    store = fake_github(tmp_path, monkeypatch, data, "landed.jsonl")
    assert xp.main(["story", "story-002"]) == 0
    assert json.loads(store.read_text())["published"][0] == "224"
