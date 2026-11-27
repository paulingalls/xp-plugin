import json
import os
import sys

import pytest
import xp
from test_land import git
from test_retro import released, result


@pytest.fixture
def publishing(tmp_path, monkeypatch, fake_retro):
    root, data, folder = released(tmp_path, monkeypatch)
    (root / ".xp/config.yml").open("a").write("\ngithub_issues: on\n")
    wiki = tmp_path / "origin.wiki.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(wiki))
    seed = tmp_path / "wiki-seed"
    git(tmp_path, "clone", "-q", str(wiki), str(seed))
    (seed / "Home.md").write_text("Wiki home\n")
    wiki_commit(seed)
    monkeypatch.setenv("WIKI", str(wiki))
    store = tmp_path / "github.json"
    store.write_text(json.dumps({"calls": [], "issues": [], "pages": []}))
    monkeypatch.setenv("GH_STORE", str(store))
    gh = tmp_path / "retro-bin/gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, sys, subprocess
from pathlib import Path
args = sys.argv[1:]
store = Path(os.environ['GH_STORE'])
state = json.loads(store.read_text())
body = sys.stdin.read()
state['calls'].append([args, body])
store.write_text(json.dumps(state))
if args[:2] == ['repo', 'view']:
    print('{"nameWithOwner":"owner/project","url":"https://example.test/owner/project"}')
elif args[:2] == ['api', 'graphql']:
    if os.environ.get('GH_FAIL'): sys.exit('snapshot unavailable')
    pages = state['pages'] or [{'data': {'repository': {'issues': {'nodes': state['issues']}}}}]
    pages = json.loads(json.dumps(pages))
    if 'labels:["bug","debt","lesson"]' in ' '.join(args):
        for page in pages:
            connection = page['data']['repository']['issues']
            connection['nodes'] = [i for i in connection['nodes']
                if any(label['name'] in ('bug','debt','lesson') for label in i.get('labels', []))]
    for page in pages:
        for issue in page['data']['repository']['issues']['nodes']:
            issue['labels'] = {'nodes': issue.get('labels', [])}
    print(json.dumps(pages if '--paginate' in args else pages[:1]))
elif args[:2] == ['issue', 'view']:
    print(json.dumps(next((i for i in state['issues'] if str(i['number']) == args[2]),
        {'state':'OPEN','stateReason':None})))
elif args[:2] == ['issue', 'close']:
    issue = next(i for i in state['issues'] if str(i['number']) == args[2])
    issue.update(state='CLOSED', stateReason='COMPLETED', closedAt='2026-11-26')
    issue['comment'] = args[args.index('--comment')+1]
elif args[:2] == ['issue', 'list']:
    print(json.dumps(state['issues']))
elif args[:2] == ['issue', 'create']:
    if len(state['issues']) == int(os.environ.get('GH_FAIL_AT', '-1')):
        sys.exit('creation denied')
    ledger = subprocess.check_output(['git', '--git-dir', os.environ['WIKI'],
        'show', 'HEAD:Lessons.md'], text=True)
    assert '[proposed]' in ledger
    assert os.environ.get('PRESEAT') or Path(os.environ['PUBLISHED']).exists()
    number = 224 + len(state['issues'])
    state['issues'].append({'number':number, 'title':args[args.index('--title')+1],
        'body':body, 'labels':[{'name':'lesson'}], 'state':'OPEN',
        'stateReason':None, 'closedAt':None})
    print(f'https://example.test/issues/{number}')
elif args[:2] not in (['auth', 'status'], ['label', 'create']):
    sys.exit('unexpected gh command')
store.write_text(json.dumps(state))
"""
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PUBLISHED", str(folder / "retro.md"))
    return root, data, folder, store, fake_retro


def wiki_commit(directory):
    git(
        directory,
        "add",
        "Home.md",
        "Lessons.md" if (directory / "Lessons.md").exists() else "Home.md",
    )
    git(directory, "-c", "user.name=xp", "-c", "user.email=xp@localhost", "commit", "-qm", "wiki")
    git(directory, "push", "-q", "origin", "HEAD")


def wiki_seed(publishing, text):
    seed = publishing[0].parent / "wiki-seed"
    git(seed, "pull", "-q", "--ff-only")
    (seed / "Lessons.md").write_text(text)
    wiki_commit(seed)


def wiki_read(publishing):
    return git(publishing[0].parent / "origin.wiki.git", "show", "HEAD:Lessons.md") + "\n"


def state(publishing):
    return json.loads(publishing[3].read_text())


def two_proposals(monkeypatch):
    result(monkeypatch)
    answer = json.loads(os.environ["RETRO_RESULT"])
    answer["sightings"].append({"lesson": "new:2", "text": "Second observation"})
    answer["proposals"].append({**answer["proposals"][0], "lessons": ["new:2"]})
    monkeypatch.setenv("RETRO_RESULT", json.dumps(answer))


def test_publication_retry_and_recovery(publishing, monkeypatch, capsys):
    root, _, folder, _, _ = publishing
    wiki_seed(publishing, "- L7 [proposed] Filed already (seen: old:0) -> action; #99\n")
    two_proposals(monkeypatch)
    monkeypatch.setenv("GH_FAIL_AT", "1")
    assert xp.main(["retro", "1"]) == 1
    text = wiki_read(publishing)
    assert "; #224" in text and "L9 [proposed]" in text and "; #225" not in text
    assert (folder / "retro.md").exists()
    error = capsys.readouterr().err
    assert all(s in error for s in ("creation denied", "L9", "wiki", "Lessons.md", "xp.py retro 1"))
    monkeypatch.delenv("GH_FAIL_AT")
    monkeypatch.setenv("RETRO_RESULT", '{"sightings":[],"proposals":[]}')
    assert xp.main(["retro", "1"]) == 0
    issues = state(publishing)["issues"]
    assert len(issues) == 2
    assert all(s in issues[0]["body"] for s in ("L8", "A lesson", "Delete the step", "An hour"))
    assert all(f"; #{n}" in wiki_read(publishing) for n in (99, 224, 225))
    for args, _ in state(publishing)["calls"]:
        if args[:2] in (["label", "create"], ["issue", "create"]):
            assert args[-2:] == ["-R", git(root, "remote", "get-url", "origin")]
    assert xp.main(["recover"]) == 0
    output = capsys.readouterr().out
    assert "#224 lesson — A lesson" in output and "- L8 [proposed]" not in output


def test_two_new_proposals(publishing, monkeypatch):
    two_proposals(monkeypatch)
    assert xp.main(["retro", "1"]) == 0
    assert len(state(publishing)["issues"]) == 2
    assert all(f"; #{n}" in wiki_read(publishing) for n in (224, 225))


def test_removed_manual_command(publishing, capsys):
    with pytest.raises(SystemExit) as exc:
        xp.main(["lesson", "file", "7"])
    assert exc.value.code == 2
    assert "invalid choice: 'lesson'" in capsys.readouterr().err


def closing_setup(publishing):
    _, _, folder, store, _ = publishing
    issues = [
        {
            "number": n,
            "title": f"Lesson {n}",
            "labels": [{"name": "lesson"}],
            "state": "OPEN",
            "stateReason": None,
            "closedAt": None,
        }
        for n in (224, 225, 780)
    ]
    issues[-1].update(state="CLOSED", stateReason="COMPLETED", closedAt="2026-11-26")
    s = state(publishing)
    s["issues"] = issues
    store.write_text(json.dumps(s))
    wiki_seed(
        publishing,
        "- L7 [proposed] Fixed (seen: old:0) -> proposal: remove; #224\n"
        "- L8 [proposed] Unresolved (seen: old:0) -> proposal: keep; #225\n",
    )
    (folder / "retro.md").write_text("Previous retro")
    return {"issue": 224, "evidence": {"kind": "issue", "ref": "#780"}}


def closing_answer(monkeypatch, closures):
    monkeypatch.setenv(
        "RETRO_RESULT", json.dumps({"sightings": [], "proposals": [], "closures": closures})
    )


@pytest.mark.parametrize("kind", ["issue", "commit", "rule"])
def test_close_landed_lesson(publishing, monkeypatch, kind):
    request = closing_setup(publishing)
    root, _, folder, _, _ = publishing
    ref = {
        "issue": "#780",
        "commit": git(root, "rev-parse", "HEAD"),
        "rule": ".xp/system.md: Existing rule",
    }[kind]
    (root / ".xp/system.md").write_text("Existing rule\n")
    request["evidence"] = {"kind": kind, "ref": ref}
    before = wiki_read(publishing)
    closing_answer(monkeypatch, [request])
    assert xp.main(["retro", "1"]) == 0
    assert wiki_read(publishing) == "".join(before.splitlines(keepends=True)[1:])
    issues = state(publishing)["issues"]
    assert issues[0]["state"] == "CLOSED" and issues[0]["stateReason"] == "COMPLETED"
    assert ref in issues[0]["comment"] and issues[1]["state"] == "OPEN"
    assert (folder / "retro.md").read_text() != "Previous retro"
    closing_answer(monkeypatch, [])
    assert xp.main(["retro", "1"]) == 0
    calls = [a for a, _ in state(publishing)["calls"] if a[:2] == ["issue", "close"]]
    assert len(calls) == 1
    assert calls[0][calls[0].index("--reason") + 1] == "completed"
    assert calls[0][-2:] == ["-R", git(root, "remote", "get-url", "origin")]
    assert wiki_read(publishing) == "".join(before.splitlines(keepends=True)[1:])


@pytest.mark.parametrize(
    "invalid",
    [
        "bug",
        "debt",
        "closed",
        "absent",
        "missing",
        "blank",
        "kind",
        "malformed",
        "unresolved",
        "open",
        "duplicate",
        "reason",
        "unseen",
        "file",
        "blank-rule",
        "secret",
        "unlanded",
        "dropped",
    ],
)
def test_refuse_closure_batch(publishing, monkeypatch, capsys, invalid):
    valid = closing_setup(publishing)
    other = {"issue": 225, "evidence": {"kind": "issue", "ref": "#780"}}
    s = state(publishing)
    if invalid in ("bug", "debt"):
        s["issues"][1]["labels"] = [{"name": invalid}]
    elif invalid == "closed":
        other["issue"] = 780
    elif invalid == "absent":
        other["issue"] = 999
    elif invalid == "missing":
        del other["evidence"]
    elif invalid == "secret":
        root = publishing[0]
        (root / ".gitleaks.toml").write_text(
            '[[rules]]\nid = "c"\nregex = "xp_canary_[a-f0-9]{8}"\n'
        )
        (root / ".xp/system.md").write_text("Rule\n")
        other["evidence"] = {"kind": "rule", "ref": ".xp/system.md: xp_canary_0123abcd"}
    elif invalid in ("blank", "kind", "malformed", "unresolved", "open", "unseen", "file"):
        other["evidence"] = {
            "blank": {"kind": "issue", "ref": " "},
            "kind": {"kind": "guess", "ref": "#780"},
            "malformed": {"kind": "issue", "ref": "780"},
            "unresolved": {"kind": "commit", "ref": "deadbeef"},
            "open": {"kind": "issue", "ref": "#224"},
            "unseen": {"kind": "issue", "ref": "#999"},
            "file": {"kind": "rule", "ref": ".xp/constraints.md: absent"},
        }[invalid]
    elif invalid == "blank-rule":
        (publishing[0] / ".xp/system.md").write_text("Rule\n")
        other["evidence"] = {"kind": "rule", "ref": ".xp/system.md: "}
    elif invalid == "unlanded":
        root = publishing[0]
        git(root, "switch", "-q", "-c", "side")
        git(root, "commit", "-q", "--allow-empty", "-m", "unlanded fix")
        other["evidence"] = {"kind": "commit", "ref": git(root, "rev-parse", "HEAD")}
        git(root, "switch", "-q", "-")
    elif invalid == "dropped":
        s["issues"][2]["stateReason"] = "NOT_PLANNED"
    elif invalid == "duplicate":
        other = valid
    elif invalid == "reason":
        other["reason"] = "not planned"
    publishing[3].write_text(json.dumps(s))
    before = wiki_read(publishing)
    closing_answer(monkeypatch, [valid, other])
    assert xp.main(["retro", "1"]) == 1
    assert ("gitleaks" if invalid == "secret" else "closure") in capsys.readouterr().err.lower()
    assert wiki_read(publishing) == before
    assert (publishing[2] / "retro.md").read_text() == "Previous retro"
    assert state(publishing)["issues"] == s["issues"]
    assert not [a for a, _ in state(publishing)["calls"] if a[:2] == ["issue", "close"]]
