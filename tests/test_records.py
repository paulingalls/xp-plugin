import json
import os
import shlex
import shutil
import subprocess
import sys

import pytest
import xp
from xpcore import records

PY = shlex.quote(sys.executable)
RED = f"{PY} -c 'raise SystemExit(3)'"
GREEN = f"{PY} -c 'print(1)'"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    subprocess.run(["git", "init", "-q", str(tmp_path / "r")], check=True)
    monkeypatch.chdir(tmp_path / "r")
    binpath = tmp_path / "bin"
    binpath.mkdir()
    gh = binpath / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, sys
from pathlib import Path
args = sys.argv[1:]
store = Path(os.environ['GH_STORE'])
state = json.loads(store.read_text())
state['calls'].append([args, sys.stdin.read(), os.getcwd()])
if args[:2] == ['auth', 'status']:
    if os.environ.get('GH_FAIL'):
        store.write_text(json.dumps(state))
        sys.exit('authentication expired')
elif args[:2] == ['label', 'list']:
    # gh 2.103 prints nothing, not [], when --search matches no label
    names = [{'name': x} for x in state['labels'] if x == args[args.index('--search')+1]]
    print(json.dumps(names) if names else '')
elif args[:2] == ['label', 'create']:
    state['labels'].append(args[2])
elif args[:2] == ['issue', 'create']:
    state['issues'].append({'number': 224, 'title': args[args.index('--title')+1],
                          'labels': [{'name': args[args.index('--label')+1]}]})
    print('https://example.test/issues/224')
elif args[:2] == ['issue', 'list']:
    if os.environ.get('GH_FAIL'):
        store.write_text(json.dumps(state))
        sys.exit('network unavailable')
    print(json.dumps(state['issues']) if '--json' in args else '')
elif args[:2] != ['issue', 'close']:
    sys.exit('unexpected gh command')
store.write_text(json.dumps(state))
"""
    )
    gh.chmod(0o755)
    store = tmp_path / "issues.json"
    store.write_text(json.dumps({"calls": [], "labels": ["debt"], "issues": []}))
    monkeypatch.setenv("GH_STORE", str(store))
    monkeypatch.setenv("PATH", str(binpath) + os.pathsep + os.environ["PATH"])
    return tmp_path


def state(repo):
    return json.loads((repo / "issues.json").read_text())


def refused(capsys, argv):
    with pytest.raises(SystemExit) as exc:
        xp.main(argv)
    assert exc.value.code == 2
    return capsys.readouterr().err


def filing(kind="bug", falsifier=RED):
    args = [kind, "--claim", "parser drops tabs", "--falsifier", falsifier, "--files", "a.py"]
    return args + (
        ["--too-big", "crosses concern", "--too-important", "silent loss"] if kind == "debt" else []
    )


@pytest.mark.parametrize("kind", ["bug", "debt"])
def test_file_issue(repo, capsys, monkeypatch, kind):
    records.work_path().parent.mkdir()
    records.work_path().write_text("old notes\n")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
    )
    checkout = repo / "worktree"
    subprocess.run(["git", "worktree", "add", "-qb", "filing", str(checkout)], check=True)
    nested = checkout / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    script = (
        'from pathlib import Path; Path("once").open("a").write("x"); '
        'print("stdout"); import sys; print("stderr", file=sys.stderr); '
        f"sys.exit({3 if kind == 'bug' else 0})"
    )
    command = f"{PY} -c {shlex.quote(script)}"
    assert xp.main(filing(kind, command)) == 0
    s = state(repo)
    create = next(c for c in s["calls"] if c[0][:2] == ["issue", "create"])
    assert s["issues"][0]["labels"] == [{"name": kind}]
    for text in [
        "Claim: parser drops tabs",
        "Files: a.py",
        "Filer: r",
        "stdout",
        "stderr",
        f"Falsifier rc: {3 if kind == 'bug' else 0}",
    ]:
        assert text in create[1]
    if kind == "debt":
        assert "Too big: crosses concern" in create[1] and "Too important: silent loss" in create[1]
        assert not any(c[0][:2] == ["label", "create"] for c in s["calls"])
    assert kind in s["labels"]
    assert all(c[2] == str(checkout) for c in s["calls"])
    assert (checkout / "once").read_text() == "x"
    assert records.work_path().read_text() == "old notes\n"
    assert "https://example.test/issues/224" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args, message",
    [
        (filing("bug", GREEN), "file as debt"),
        (filing("debt", RED), "file as bug"),
        (filing(falsifier="no-such-binary-xp"), "exited 127"),
        (filing(falsifier=" "), "falsifier is empty"),
        (
            [
                "debt",
                "--claim",
                "c",
                "--falsifier",
                GREEN,
                "--too-big",
                " ",
                "--too-important",
                "i",
            ],
            "both bars",
        ),
    ],
)
def test_invalid_falsifier(repo, capsys, args, message):
    assert message in refused(capsys, args)
    assert not state(repo)["calls"] and not records.work_path().exists()


@pytest.mark.parametrize("kind", ["bug", "debt"])
@pytest.mark.parametrize("missing", ["gh", "gitleaks", "auth"])
def test_dependencies(repo, monkeypatch, capsys, kind, missing):
    if kind == "debt":
        records.work_path().parent.mkdir()
        records.work_path().write_text("old local records\n")
    if missing == "auth":
        monkeypatch.setenv("GH_FAIL", "1")
    else:
        isolated = repo / "isolated"
        isolated.mkdir()
        for name in ("gh", "gitleaks", "git", "sh"):
            if name != missing:
                (isolated / name).symlink_to(shutil.which(name))
        monkeypatch.setenv("PATH", str(isolated))
    err = refused(capsys, filing(kind, RED if kind == "bug" else GREEN))
    assert ("gitleaks" if missing == "gitleaks" else "gh auth login") in err
    if kind == "debt":
        assert records.work_path().read_text() == "old local records\n"
    else:
        assert not records.work_path().exists()
    assert not state(repo)["calls"] if missing != "auth" else len(state(repo)["calls"]) == 1


@pytest.mark.parametrize("command", [GREEN, RED])
def test_numeric_resolve(repo, capsys, command):
    args = ["resolve", "--ref", "224", "--falsifier", command]
    if command == RED:
        assert "exited 3" in refused(capsys, args)
        assert not state(repo)["calls"]
    else:
        assert xp.main(args) == 0
        close = state(repo)["calls"][-1][0]
        assert close[:3] == ["issue", "close", "224"]
        comment = close[close.index("--comment") + 1]
        assert GREEN in comment and "Falsifier rc: 0" in comment and "    1" in comment
    assert not records.work_path().exists()


def legacy():
    records.work_path().parent.mkdir(exist_ok=True)
    records.work_path().write_text(
        "## bug abcdefab now\nClaim: old bug\n\n## debt deadbeef now\nClaim: old debt\n"
    )


def test_legacy_and_note(repo, capsys, monkeypatch):
    legacy()
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert "exited 3" in refused(capsys, ["resolve", "--ref", "abcdefab", "--falsifier", RED])
    assert xp.main(["resolve", "--ref", "abcdefab", "--falsifier", GREEN]) == 0
    assert records.open_records() == ["debt deadbeef — old debt"]
    assert "already resolved" in refused(
        capsys, ["resolve", "--ref", "abcdefab", "--falsifier", GREEN]
    )
    assert "no bug or debt" in refused(
        capsys, ["resolve", "--ref", "unknown", "--falsifier", GREEN]
    )
    assert xp.main(["note", "line one\n## bug feedface now"]) == 0
    assert records.open_records() == ["debt deadbeef — old debt"]


def test_output_is_bounded(repo):
    assert xp.main(filing(falsifier=f"{PY} -c 'print(\"x\" * 50000); raise SystemExit(1)'")) == 0
    body = next(c[1] for c in state(repo)["calls"] if c[0][:2] == ["issue", "create"])
    assert len(body) < records.OUTPUT_CAP + 500


def test_recover_across_clones(repo, monkeypatch, capsys):
    assert xp.main(filing()) == 0
    assert xp.main(filing("debt", GREEN)) == 0
    subprocess.run(["git", "clone", "-q", str(repo / "r"), str(repo / "clone")], check=True)
    monkeypatch.chdir(repo / "clone")
    monkeypatch.setenv("XP_DATA", str(repo / "other-data"))
    legacy()
    assert xp.main(["resolve", "--ref", "abcdefab", "--falsifier", GREEN]) == 0
    assert xp.main(["recover"]) == 0
    out = capsys.readouterr().out.split("## open records")[1]
    remote, local = out.split("local (filed before 1.6.0)")
    assert (
        "224" in remote and "bug" in remote and "debt" in remote and "parser drops tabs" in remote
    )
    assert "old debt" in local and "old bug" not in local
    s = state(repo)
    s["issues"] *= 50
    (repo / "issues.json").write_text(json.dumps(s))
    assert xp.main(["recover"]) == 0
    assert "first 100 shown" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["missing", "network", "timeout"])
def test_recover_failure(repo, monkeypatch, capsys, failure):
    legacy()
    if failure == "missing":
        (repo / "bin" / "gh").unlink()
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
    elif failure == "network":
        monkeypatch.setenv("GH_FAIL", "1")
    else:
        monkeypatch.setattr(records, "GH_TIMEOUT", 0.001)
        (repo / "bin" / "gh").write_text(f"#!{sys.executable}\nimport time\ntime.sleep(1)\n")
    assert xp.main(["recover"]) == 0
    out = capsys.readouterr().out.split("## open records")[1]
    assert {"missing": "gh", "network": "network unavailable", "timeout": "timed out"}[
        failure
    ] in out
    assert "local (filed before 1.6.0)" in out and "old bug" in out and "## sprint" in out
