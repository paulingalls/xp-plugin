import json
import os
import sys
from pathlib import Path

import pytest
import xp
from test_free_post_merge import publish_merge
from test_land import CONFIG, commit, free_patch, git, make_project, story  # noqa: F401
from test_records import refused, repo  # noqa: F401
from test_shared import CARD, plan
from test_sprint import merge_on_trunk
from test_sprint import repo as sprint_repo  # noqa: F401
from test_story import repo as story_repo  # noqa: F401
from xpcore import cards, shared


def github(tmp_path, monkeypatch, labels, extra=None):
    binary = tmp_path / "bin"
    binary.mkdir(exist_ok=True)
    store = tmp_path / "github.json"
    issue = dict(
        number="224",
        title="Original record",
        body="Original finding body",
        labels=labels,
        state="OPEN",
        comments=[],
    )
    issues = {"224": issue, **(extra or {})}
    store.write_text(json.dumps(dict(issues=issues, calls=[], labels={})))
    gh = binary / "gh"
    gh.write_text(
        f"#!{sys.executable}\nSTORE = {str(store)!r}\n"
        + """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
p = Path(STORE)
s = json.loads(p.read_text())
body = sys.stdin.read()
s['calls'].append([args, body])
p.write_text(json.dumps(s))
if os.environ.get('GH_VIEW_FAIL') == ' '.join(args[:3]):
    sys.exit('metadata unavailable')
if args[:2] == ['issue', 'view']:
    i = s['issues'][args[2]]
    print(json.dumps(dict(i, labels=[{'name': n} for n in i['labels']])))
elif args[:2] == ['label', 'list']:
    print(json.dumps([{'name': n} for n in s['labels'] if n == args[3]]))
elif args[:2] == ['label', 'create']:
    s['labels'][args[2]] = {'color': 'default', 'description': ''}
elif args[0] == 'issue' and args[1] in ('edit', 'close', 'comment'):
    i = s['issues'][args[2]]
    for flag, field in [('--title', 'title'), ('--body', 'body')]:
        if flag in args and args[1] == 'edit': i[field] = args[args.index(flag)+1]
    if '--body-file' in args: i['body'] = body
    if '--add-label' in args: i['labels'].append(args[args.index('--add-label')+1])
    if args[1] == 'close': i['state'] = 'CLOSED'
    if args[1] == 'comment': i['comments'].append(args[args.index('--body')+1])
    if '--comment' in args: i['comments'].append(args[args.index('--comment')+1])
elif args[:2] == ['pr', 'view']:
    sys.exit(1)
elif args[:2] not in (['pr', 'create'], ['auth', 'status']):
    sys.exit('unexpected gh command: ' + repr(args))
p.write_text(json.dumps(s))
"""
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary}{os.pathsep}{os.environ['PATH']}")
    return store


def unchanged(store, before, capsys, message, numbers=("224",)):
    after = json.loads(store.read_text())
    for number in numbers:
        assert after["issues"][number] == before["issues"][number]
    calls = [a for a, _ in after["calls"][len(before["calls"]) :]]
    assert not [
        a
        for a in calls
        if a[:2] in (["issue", "edit"], ["issue", "close"], ["issue", "comment"])
        and a[2] in numbers
    ]
    assert not [a for a in calls if a[0] == "label"]
    output = capsys.readouterr().out.splitlines()
    for number in numbers:
        assert f"#{number} is not a card issue; {message}" in output


def test_story_start_leaves_record(story_repo, tmp_path, monkeypatch, capsys):  # noqa: F811
    root, data = Path.cwd(), story_repo
    commit(
        root,
        {".xp/config.yml": (root / ".xp/config.yml").read_text() + "github_issues: on\n"},
        "share",
    )
    path = data / "plan.md"
    path.write_text(
        path.read_text().replace("Files: a.py\n", "Files: a.py\nIssue: #224\nPublished by: local\n")
    )
    store = github(tmp_path, monkeypatch, ["bug", "clone:other@123456"])
    before = json.loads(store.read_text())
    assert xp.main(["story", "story-002"]) == 0
    assert cards.find_card("story-002").status == "in-progress"
    unchanged(store, before, capsys, "its text is left as is")


def test_story_land_leaves_record(story, tmp_path, monkeypatch, capsys):  # noqa: F811
    root, data, wt, _ = story
    path = data / "plan.md"
    path.write_text(path.read_text() + "Issue: #224\n")
    commit(
        root,
        {
            "merged.txt": "ok\n",
            ".xp/config.yml": (root / ".xp/config.yml").read_text() + "github_issues: on\n",
        },
        "share",
    )
    store = github(tmp_path, monkeypatch, ["debt"])
    before = json.loads(store.read_text())
    assert xp.main(["story", "land", "story-001"]) == 0
    assert cards.find_card("story-001").status == "done" and not wt.exists()
    unchanged(store, before, capsys, "its text is left as is")


def test_sprint_open_leaves_record(tmp_path, monkeypatch, capsys):
    root, data = make_project(tmp_path, monkeypatch, CONFIG + "github_issues: on\n")
    (data / "plan.md").write_text(
        "## Sprint 1\n#### story-001 — a   [planned]\nAcceptance: true\nIssue: #224\n"
    )
    store = github(tmp_path, monkeypatch, ["lesson"])
    before = json.loads(store.read_text())
    git(root, "switch", "-qc", "sprint-1")
    assert xp.main(["sprint", "open", "1"]) == 0
    assert (data / "sprint_branch").read_text().strip() == "sprint-1"
    unchanged(store, before, capsys, "its text is left as is")


def test_republish_leaves_record(repo, monkeypatch, capsys):  # noqa: F811
    plan("## Sprint 1\n" + CARD + "Issue: #224\n")
    store = github(repo, monkeypatch, [])
    before = json.loads(store.read_text())
    assert xp.main(["card", "publish", "free-share"]) == 0
    assert cards.find_card("free-share").field("Issue") == "#224"
    unchanged(store, before, capsys, "its text is left as is")


@pytest.mark.parametrize("evidence", ["", "Evidence: true\n"])
def test_free_post_merge_leaves_record(tmp_path, monkeypatch, capsys, evidence):
    root, data, wt = free_patch(tmp_path, monkeypatch)
    path = data / "plan.md"
    path.write_text(path.read_text() + "Issue: #224\n" + evidence)
    store = github(tmp_path, monkeypatch, ["bug"])
    assert xp.main(["free", "land", "fix"]) == 0
    sha = publish_merge(root)
    before = json.loads(store.read_text())
    assert xp.main(["free", "post-merge", "fix"]) == 0
    assert json.loads((data / "landed.jsonl").read_text())["merge"] == sha
    assert cards.find_card("free-fix").status == "done" and not wt.exists()
    assert not git(root, "branch", "--list", "free-fix-x")
    unchanged(store, before, capsys, "close it with xp.py resolve")


def test_sprint_post_merge_selects_only_card_issues(sprint_repo, tmp_path, monkeypatch, capsys):  # noqa: F811
    root, data, _ = sprint_repo
    path = data / "plan.md"
    path.write_text(
        path.read_text()
        + "Issue: #224\n"
        + "".join(
            f"#### story-{n} — a   [{status}]\nIssue: #{n}\n{evidence}"
            for n, status, evidence in [
                ("225", "done", "Evidence: true\n"),
                ("226", "retired", ""),
                ("227", "retired", ""),
                ("228", "done", ""),
                ("229", "retired", ""),
            ]
        )
    )
    extra = {
        n: dict(number=n, title="Record", body="Finding", labels=labels, state="OPEN", comments=[])
        for n, labels in [
            ("225", ["debt"]),
            ("226", ["lesson"]),
            ("227", ["clone:other@123456"]),
            ("228", ["card"]),
            ("229", ["card"]),
        ]
    }
    store = github(tmp_path, monkeypatch, ["bug"], extra)
    assert xp.main(["sprint", "land", "1"]) == 0
    merge_on_trunk(root)
    before = json.loads(store.read_text())
    assert xp.main(["sprint", "post-merge", "1"]) == 0
    assert (data / "sprints/1/release.json").is_file()
    assert not git(root, "branch", "--list", "sprint-1")
    s = json.loads(store.read_text())
    assert s["issues"]["228"]["state"] == s["issues"]["229"]["state"] == "CLOSED"
    unchanged(store, before, capsys, "close it with xp.py resolve", ("224", "225", "226", "227"))


def test_sync_reuses_clone_label(story, tmp_path, monkeypatch):  # noqa: F811
    root, data, _, _ = story
    path = data / "plan.md"
    path.write_text(path.read_text() + "Issue: #224\n")
    commit(
        root,
        {
            "merged.txt": "ok\n",
            ".xp/config.yml": (root / ".xp/config.yml").read_text() + "github_issues: on\n",
        },
        "share",
    )
    store = github(tmp_path, monkeypatch, ["card"])
    s = json.loads(store.read_text())
    label = "clone:" + shared.owner()
    s["labels"][label] = dict(color="123456", description="Project label")
    store.write_text(json.dumps(s))
    assert xp.main(["story", "land", "story-001"]) == 0
    after = json.loads(store.read_text())
    assert label in after["issues"]["224"]["labels"]
    assert after["labels"] == s["labels"]
    assert not [a for a, _ in after["calls"] if a[:2] == ["label", "create"]]


def test_post_merge_reuses_merged_label(tmp_path, monkeypatch):
    root, data, _ = free_patch(tmp_path, monkeypatch)
    path = data / "plan.md"
    path.write_text(path.read_text() + "Issue: #224\nEvidence: true\n")
    store = github(tmp_path, monkeypatch, ["card"])
    s = json.loads(store.read_text())
    s["labels"]["merged"] = dict(color="123456", description="Project label")
    store.write_text(json.dumps(s))
    assert xp.main(["free", "land", "fix"]) == 0
    sha = publish_merge(root)
    assert xp.main(["free", "post-merge", "fix"]) == 0
    after = json.loads(store.read_text())
    assert after["issues"]["224"]["state"] == "OPEN"
    assert "merged" in after["issues"]["224"]["labels"]
    assert after["issues"]["224"]["comments"] == [f"Merged as {sha}"]
    assert after["labels"] == s["labels"]
    assert not [a for a, _ in after["calls"] if a[:2] == ["label", "create"]]


@pytest.mark.parametrize("failure", ["224", "226"])
def test_post_merge_metadata_failure_requires_conditional_recovery(
    sprint_repo,
    tmp_path,
    monkeypatch,
    capsys,
    failure,  # noqa: F811
):
    root, data, _ = sprint_repo
    path = data / "plan.md"
    path.write_text(
        path.read_text() + "Issue: #224\n"
        "#### story-225 — fixed   [done]\nIssue: #225\n"
        "#### story-226 — dropped   [retired]\nIssue: #226\n"
    )
    extra = {
        n: dict(
            number=n, title="Record", body="Finding", labels=["card"], state="OPEN", comments=[]
        )
        for n in ("225", "226")
    }
    store = github(tmp_path, monkeypatch, ["bug"], extra)
    assert xp.main(["sprint", "land", "1"]) == 0
    merge_on_trunk(root)
    monkeypatch.setenv("GH_VIEW_FAIL", f"issue view {failure}")
    err = refused(capsys, ["sprint", "post-merge", "1"])
    sha = json.loads((data / "sprints/1/release.json").read_text())["merge"]
    assert f"#{failure}: metadata unavailable; release recorded." in err
    assert sha in err
    assert "gh issue close 226 --reason 'not planned'  # if labelled card and unheld" in err
    if failure == "224":
        assert f"gh issue close 224 --comment 'Merged as {sha}'  # if labelled card" in err
    else:
        assert "gh issue close 224" not in err
        assert f"gh issue close 225 --comment 'Merged as {sha}'" in err
    s = json.loads(store.read_text())
    assert not [
        a
        for a, _ in s["calls"]
        if a[:2]
        in (["issue", "close"], ["issue", "comment"], ["issue", "edit"], ["label", "create"])
    ]
    assert not git(root, "branch", "--list", "sprint-1")
