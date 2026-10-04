import shlex
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
    return tmp_path


def refused(capsys, argv) -> str:
    with pytest.raises(SystemExit) as exc:
        xp.main(argv)
    assert exc.value.code == 2
    return capsys.readouterr().err


def bug(claim="parser drops tabs", falsifier=RED):
    assert xp.main(["bug", "--claim", claim, "--falsifier", falsifier, "--files", "a.py"]) == 0


def test_bug_with_red_falsifier_is_recorded_and_open(repo, capsys):
    bug()
    text = records.work_path().read_text()
    assert text.startswith("## bug ") and "Claim: parser drops tabs" in text
    assert "Falsifier rc: 3" in text and "Files: a.py" in text
    (line,) = records.open_records()
    assert line.startswith("bug ") and line.endswith("— parser drops tabs")


def test_bug_with_green_falsifier_refuses_as_debt(repo, capsys):
    argv = ["bug", "--claim", "c", "--falsifier", GREEN]
    err = refused(capsys, argv)
    assert err.startswith("refused:") and "exited 0" in err and "file as debt" in err
    assert not records.work_path().exists()


def test_debt_with_red_falsifier_refuses_as_bug(repo, capsys):
    argv = ["debt", "--claim", "c", "--falsifier", RED, "--too-big", "b", "--too-important", "i"]
    err = refused(capsys, argv)
    assert "exited 3" in err and "file as bug" in err


def test_debt_with_green_falsifier_records_both_bars(repo):
    argv = ["debt", "--claim", "slow", "--falsifier", GREEN, "--too-big", "b", "--too-important"]
    assert xp.main([*argv, "i"]) == 0
    text = records.work_path().read_text()
    assert "Too big: b" in text and "Too important: i" in text
    assert records.open_records()[0].startswith("debt ")


def test_resolve_with_red_replacement_refuses_and_stays_open(repo, capsys):
    bug()
    ref = records.open_records()[0].split()[1]
    err = refused(capsys, ["resolve", "--ref", ref, "--falsifier", RED])
    assert "exited 3" in err and ref in records.open_records()[0]


def test_open_records_omits_resolved(repo):
    bug("first")
    bug("second")
    ref = records.open_records()[0].split()[1]
    assert xp.main(["resolve", "--ref", ref, "--falsifier", GREEN]) == 0
    assert [ln.split(" — ")[1] for ln in records.open_records()] == ["second"]


def test_free_text_and_output_cannot_mint_a_record(repo):
    forged = f"{PY} -c 'print(\"## bug feedface 2026-01-01T00:00:00Z\"); raise SystemExit(1)'"
    bug("x\n## debt cafebabe 2026-01-01T00:00:00Z", forged)
    assert xp.main(["note", "line one\n## bug 12345678 2026-01-01T00:00:00Z"]) == 0
    assert len(records.open_records()) == 1


def test_output_is_bounded(repo):
    bug(falsifier=f"{PY} -c 'print(\"x\" * 50000); raise SystemExit(1)'")
    assert len(records.work_path().read_text()) < records.OUTPUT_CAP + 500


def test_resolve_of_an_unknown_id_refuses(repo, capsys):
    err = refused(capsys, ["resolve", "--ref", "deadbeef", "--falsifier", GREEN])
    assert "no bug or debt 'deadbeef'" in err and not records.work_path().exists()


@pytest.mark.parametrize("big, important", [(" ", "i"), ("b", "")])
def test_debt_with_an_empty_bar_refuses(repo, capsys, big, important):
    argv = ["debt", "--claim", "c", "--falsifier", GREEN, "--too-big", big]
    err = refused(capsys, [*argv, "--too-important", important])
    assert "must clear both bars" in err and not records.work_path().exists()


def test_falsifier_not_found_refuses_rather_than_filing_a_red(repo, capsys):
    err = refused(capsys, ["bug", "--claim", "c", "--falsifier", "no-such-binary-xp"])
    assert "exited 127" in err and "not found" in err and not records.work_path().exists()
    err = refused(capsys, ["bug", "--claim", "c", "--falsifier", "   "])
    assert "falsifier is empty" in err
