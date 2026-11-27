import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import xp
from test_land import git
from test_retro import released, result
from xpcore import retro


@pytest.fixture
def publishing(tmp_path, monkeypatch, fake_retro):
    root, data, folder = released(tmp_path, monkeypatch)
    (root / ".xp/config.yml").open("a").write("\ngithub_issues: on\n")
    store = tmp_path / "github.json"
    store.write_text(json.dumps({"calls": [], "issues": [], "pages": []}))
    monkeypatch.setenv("GH_STORE", str(store))
    gh = tmp_path / "retro-bin/gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, sys
from pathlib import Path
args = sys.argv[1:]
store = Path(os.environ['GH_STORE'])
state = json.loads(store.read_text())
body = sys.stdin.read()
state['calls'].append([args, body])
store.write_text(json.dumps(state))
if args[:2] == ['repo', 'view']:
    print('{"nameWithOwner":"owner/project"}')
elif args[:2] == ['api', 'graphql']:
    if os.environ.get('GH_FAIL'): sys.exit('snapshot unavailable')
    pages = state['pages'] or [{'data': {'repository': {'issues': {'nodes': state['issues']}}}}]
    if 'labels:["bug","debt","lesson"]' in ' '.join(args):
        for page in pages:
            connection = page['data']['repository']['issues']
            connection['nodes'] = [i for i in connection['nodes']
                if any(label['name'] in ('bug','debt','lesson') for label in i.get('labels', []))]
    print(json.dumps(pages if '--paginate' in args else pages[:1]))
elif args[:2] == ['issue', 'view']:
    print('{"state":"OPEN","stateReason":null}')
elif args[:2] == ['issue', 'list']:
    print(json.dumps(state['issues']))
elif args[:2] == ['issue', 'create']:
    if len(state['issues']) == int(os.environ.get('GH_FAIL_AT', '-1')):
        sys.exit('creation denied')
    ledger = Path(os.environ['LEDGER'])
    assert ledger.exists() and os.environ.get('PRESEAT') or (
        ledger.exists() and Path(os.environ['PUBLISHED']).exists())
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
    monkeypatch.setenv("LEDGER", str(retro.ledger_path()))
    monkeypatch.setenv("PUBLISHED", str(folder / "retro.md"))
    return root, data, folder, store, fake_retro


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
    path = retro.ledger_path()
    path.parent.mkdir(parents=True)
    path.write_text("- L7 [proposed] Filed already (seen: old:0) -> action; #99\n")
    two_proposals(monkeypatch)
    monkeypatch.setenv("GH_FAIL_AT", "1")
    assert xp.main(["retro", "1"]) == 1
    path = retro.ledger_path()
    text = path.read_text()
    assert "; #224" in text and "L9 [proposed]" in text and "; #225" not in text
    assert (folder / "retro.md").exists()
    error = capsys.readouterr().err
    assert all(s in error for s in ("creation denied", "L9", str(path), "xp.py retro 1"))
    monkeypatch.delenv("GH_FAIL_AT")
    monkeypatch.setenv("RETRO_RESULT", '{"sightings":[],"proposals":[]}')
    assert xp.main(["retro", "1"]) == 0
    issues = state(publishing)["issues"]
    assert len(issues) == 2
    assert all(s in issues[0]["body"] for s in ("L8", "A lesson", "Delete the step", "An hour"))
    assert all(f"; #{n}" in path.read_text() for n in (99, 224, 225))
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
    assert all(f"; #{n}" in retro.ledger_path().read_text() for n in (224, 225))


def test_receipt_failure_names_manual_repair(publishing, monkeypatch, capsys):
    result(monkeypatch)
    replace = Path.replace

    def fail_receipt(source, target):
        if target == retro.ledger_path() and state(publishing)["issues"]:
            raise OSError("receipt unavailable")
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_receipt)
    assert xp.main(["retro", "1"]) == 1
    error = capsys.readouterr().err
    assert all(
        s in error
        for s in ("https://example.test/issues/224", "L1", str(retro.ledger_path()), "; #224")
    )
    assert "retry" not in error and "run xp.py retro" not in error
    assert "; #224" not in retro.ledger_path().read_text()
    assert len(state(publishing)["issues"]) == 1


def test_pending_reread_under_lock(publishing, monkeypatch, tmp_path):
    import fcntl
    import time

    root, _, _, _, _ = publishing
    path = retro.ledger_path()
    path.parent.mkdir(parents=True)
    text = "- L7 [proposed] Pending (seen: old:0) -> proposal: action\n"
    path.write_text(text)
    monkeypatch.setenv("PRESEAT", "1")
    marker = tmp_path / "locking"
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); import xp; "
        "from xpcore import retro; from pathlib import Path; "
        "original = retro.fcntl.flock\n"
        f"def lock(*args):\n Path({str(marker)!r}).touch()\n original(*args)\n"
        "retro.fcntl.flock = lock\n"
        "sys.exit(xp.main(['retro','1']))"
    )
    with path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(Path(xp.__file__).parent)],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert marker.exists() and process.poll() is None
            assert not state(publishing)["issues"]
            path.write_text(text.rstrip() + "; #99\n")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            out, err = process.communicate(timeout=20)
    assert process.returncode == 0, out + err
    assert not state(publishing)["issues"] and "; #99" in path.read_text()


def test_removed_manual_command(publishing, capsys):
    with pytest.raises(SystemExit) as exc:
        xp.main(["lesson", "file", "7"])
    assert exc.value.code == 2
    assert "invalid choice: 'lesson'" in capsys.readouterr().err
