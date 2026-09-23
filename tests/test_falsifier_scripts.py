"""Live work records own every standalone falsifier script."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_data_root_guard import real_data_root
from work import entry_id

ROOT = Path(__file__).parent.parent
CHECKER_PATH = ROOT / "tests" / "scripts" / "check_falsifier_node_ids.py"
HOOKSPATH_PATH = ROOT / "tests" / "scripts" / "falsifier_hookspath_bypass.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load(CHECKER_PATH, "falsifier_script_checker")
hooks_path = load(HOOKSPATH_PATH, "hooks_path_falsifier")


def record(command, files="source.py"):
    return (
        "## debt 2026-09-18T00:00:00Z\n"
        "Claim: the condition stays absent\n"
        f"Falsifier: `{command}`\n"
        f"Files: {files}\n\n"
    )


def records(root, text):
    root.mkdir(exist_ok=True)
    (root / "work.md").write_text(text)
    return list(checker.corpus(root))


def checks(root, live, directory, **kwargs):
    return checker.run_checks(live, root / "work.md", directory, **kwargs)


def scripts(repo, names):
    directory = repo / "tests" / "scripts"
    directory.mkdir(parents=True)
    for name, body in names.items():
        (directory / name).write_text(body)
    return directory


def run_in(repo, command):
    result = subprocess.run(command, shell=True, cwd=repo, capture_output=True, text=True)
    return SimpleNamespace(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        elapsed=0.0,
    )


def test_live_falsifier_lines_and_directory_scripts_must_correspond(tmp_path, capsys):
    directory = scripts(
        tmp_path,
        {
            "falsifier_live.py": "raise SystemExit(0)\n",
            "falsifier_orphan.py": "raise SystemExit(0)\n",
        },
    )
    live = records(tmp_path / "data", record("python3 tests/scripts/falsifier_live.py"))

    assert checks(tmp_path / "data", live, directory, execute=False) == 1
    error = capsys.readouterr().err
    assert "falsifier_orphan.py" in error
    assert "falsifier_live.py" not in error
    cli = subprocess.run(
        [sys.executable, CHECKER_PATH, "--scripts-dir", directory, tmp_path / "data"],
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 1 and "falsifier_orphan.py" in cli.stderr


def test_a_files_line_does_not_own_a_resolution_script(tmp_path, capsys):
    directory = scripts(tmp_path, {"falsifier_old.py": "raise SystemExit(0)\n"})
    original = record("python3 tests/scripts/falsifier_old.py", "tests/scripts/falsifier_old.py")
    replacement = (
        f"## resolved 2026-09-18T00:00:01Z\nResolves: {entry_id(original)}\nFalsifier: `true`\n\n"
    )

    assert (
        checks(
            tmp_path / "data",
            records(tmp_path / "data", original + replacement),
            directory,
            execute=False,
        )
        == 1
    )
    assert "falsifier_old.py" in capsys.readouterr().err


def test_archiving_a_record_names_the_orphan_without_removing_it(tmp_path, capsys):
    body = "raise SystemExit(0)\n"
    directory = scripts(tmp_path, {"falsifier_retired.py": body})
    original = record("python3 tests/scripts/falsifier_retired.py")
    root = tmp_path / "data"
    assert checks(root, records(root, original), directory, execute=False) == 0
    archived = (
        "## archived 2026-09-18T00:00:01Z\n"
        f"Archives: {entry_id(original)}\n"
        "Disposition: removed after archive\n\n"
    )

    assert checks(root, records(root, original + archived), directory, execute=False) == 1
    assert "falsifier_retired.py" in capsys.readouterr().err
    assert (directory / "falsifier_retired.py").read_text() == body


def test_a_live_record_naming_a_missing_script_is_refused_before_execution(tmp_path, capsys):
    directory = scripts(tmp_path, {})
    live = records(tmp_path / "data", record("python3 tests/scripts/falsifier_missing.py"))
    called = []

    assert checks(tmp_path / "data", live, directory, runner=called.append) == 1
    error = capsys.readouterr().err
    expected_id = entry_id(record("python3 tests/scripts/falsifier_missing.py"))
    assert "falsifier_missing.py" in error and expected_id in error
    assert called == []


def test_claim_red_and_could_not_run_are_distinct(tmp_path, capsys):
    bodies = {
        "falsifier_claim.py": "raise SystemExit('claim still red')\n",
        "falsifier_import.py": "raise ImportError('renamed module')\n",
        "falsifier_module.py": "raise ModuleNotFoundError('moved module')\n",
        "falsifier_path.py": "raise FileNotFoundError(__file__)\n",
        "falsifier_marker.py": (
            "import sys\nprint('COULD NOT RUN: fixture moved', file=sys.stderr)\n"
            "raise SystemExit(2)\n"
        ),
    }
    directory = scripts(tmp_path, bodies)
    ledger = "".join(
        record(f"python3 tests/scripts/{name}", f"claim-{index}.py")
        for index, name in enumerate(bodies)
    )

    status = checks(
        tmp_path / "data",
        records(tmp_path / "data", ledger),
        directory,
        runner=lambda command: run_in(tmp_path, command),
    )

    assert status == 2
    error = capsys.readouterr().err
    assert "RED: python3 tests/scripts/falsifier_claim.py" in error
    for name in (
        "falsifier_import.py",
        "falsifier_module.py",
        "falsifier_path.py",
        "falsifier_marker.py",
    ):
        assert f"COULD NOT RUN: python3 tests/scripts/{name}" in error
    claim = [item for item in records(tmp_path / "data", ledger) if "claim.py" in item[2]]
    assert checker.audit_scripts(claim, runner=lambda command: run_in(tmp_path, command)) == 1


def test_a_script_the_interpreter_cannot_open_is_not_a_claim_red(tmp_path, capsys):
    """The working directory, not the claim: `can't open file` carries no traceback at
    all, so the Traceback-shaped tests above cannot stand in for this one."""
    directory = scripts(tmp_path, {"falsifier_moved.py": "raise SystemExit(0)\n"})
    command = "python3 tests/scripts/falsifier_moved.py"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    status = checks(
        tmp_path / "data",
        records(tmp_path / "data", record(command)),
        directory,
        runner=lambda c: run_in(elsewhere, c),
    )

    assert status == 2
    assert f"COULD NOT RUN: {command}" in capsys.readouterr().err


def test_a_renamed_subject_script_is_not_a_claim_red(tmp_path, capsys):
    """The falsifier is not the only script an interpreter must open. A falsifier that
    drives a repo script by path reports THAT script's rename, so the message names
    the subject and not the falsifier — which is why the cwd test above, matching on
    the falsifier's own path, passed while this case still read RED."""
    directory = scripts(
        tmp_path,
        {
            "falsifier_drives.py": (
                "import subprocess,sys\n"
                "r=subprocess.run([sys.executable,'plugins/renamed_away.py'],"
                "capture_output=True,text=True)\n"
                "print(r.stdout,end=''); print(r.stderr,end='',file=sys.stderr)\n"
                "raise SystemExit(r.returncode)\n"
            )
        },
    )
    command = "python3 tests/scripts/falsifier_drives.py"

    status = checks(
        tmp_path / "data",
        records(tmp_path / "data", record(command)),
        directory,
        runner=lambda c: run_in(tmp_path, c),
    )

    assert status == 2
    assert f"COULD NOT RUN: {command}" in capsys.readouterr().err


def test_the_audit_runs_a_live_falsifier_from_any_working_directory(tmp_path, monkeypatch):
    """The DEFAULT runner is the shipped path and the least-walked one: a Falsifier line
    is repo-relative, so an ambient cwd decided whether the command ran at all."""
    monkeypatch.chdir(tmp_path)
    command = "cat tests/scripts/falsifier_fast_tier_cost.py"

    assert checker.audit_scripts(records(tmp_path / "data", record(command))) == 0
    assert Path.cwd().resolve() == tmp_path.resolve()


def test_duplicate_records_run_one_complete_command_once(tmp_path):
    command = f"{sys.executable} tests/scripts/falsifier_shared.py --complete"
    directory = scripts(tmp_path, {"falsifier_shared.py": "raise SystemExit(0)\n"})
    calls = []

    def green(value):
        calls.append(value)
        return SimpleNamespace(returncode=0, stdout="", stderr="", elapsed=0.0)

    assert (
        checks(
            tmp_path / "data",
            records(tmp_path / "data", record(command, "one.py") + record(command, "two.py")),
            directory,
            runner=green,
        )
        == 0
    )
    assert calls == [command]


def test_this_repositories_scripts_equal_the_live_record_scripts():
    root = real_data_root()
    work = root / "work.md"
    if not work.is_file():
        pytest.skip(f"live work records absent: {work}")
    live = list(checker.corpus(root))
    owned = set(checker.script_owners(live))
    present = {
        f"tests/scripts/{path.name}" for path in (ROOT / "tests" / "scripts").glob("falsifier_*.py")
    }
    assert present == owned


def test_live_script_check_reports_missing_work(tmp_path, monkeypatch):
    monkeypatch.setattr("test_falsifier_scripts.real_data_root", lambda: tmp_path)
    with pytest.raises(pytest.skip.Exception, match=r"live work records absent: .*work.md"):
        test_this_repositories_scripts_equal_the_live_record_scripts()


def test_hookspath_falsifier_constructs_or_explicitly_declines(tmp_path, capsys):
    status = hooks_path.main(tmp_path)
    error = capsys.readouterr().err
    assert status == 0 or (status == 2 and error.startswith("COULD NOT RUN:"))
