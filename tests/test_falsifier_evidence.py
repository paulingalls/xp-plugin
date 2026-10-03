"""A red falsifier batch preserves every source's bounded evidence."""

import shlex
import sys
from pathlib import Path

import work as work_module
from sprint_helpers import make_repo, snapshot, sprint, work


def recorded_files(root):
    return {
        name: blob
        for name, blob in snapshot(root).items()
        if not name.name.startswith("timing.jsonl")
    }


def file_debt(repo, env, claim, command, files="a.py"):
    result = work(repo, env, "debt", "--claim", claim, "--falsifier", command, "--files", files)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def red_debt(repo, env, tmp_path, claim, stdout, stderr, files="a.py"):
    flag = tmp_path / f"{claim}-flag"
    flag.write_text("ok")
    command = (
        f"test -f {shlex.quote(str(flag))} || {{ printf {shlex.quote(stdout)}; "
        f"printf {shlex.quote(stderr)} >&2; false; }}"
    )
    return file_debt(repo, env, claim, command, files), command, flag


def make_legacy_stub(repo, env, tmp_path, ref, command):
    root = tmp_path / "data"
    text = dict(work_module.entries(root))[ref]
    (root / "archive.md").write_text(f"# Record {ref}\n\n{text}")
    stub = f"{text.splitlines()[0]}\nId: {ref}\nFalsifier: `{command}`\n\n"
    path = root / "work.md"
    path.write_text(path.read_text().replace(text, stub))


def assert_evidence(text, expected):
    for ref, command, stdout, stderr in expected:
        marker = f"source {ref} ("
        assert text.count(marker) == 1
        section = text.split(f"command: {command}", 1)[1].split("\ncommand:", 1)[0]
        assert marker in section
        assert f"stdout:\n{stdout}" in section
        assert f"stderr:\n{stderr}" in section


def test_three_commands_report_two_reds_without_filing(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    first = red_debt(
        repo, env, tmp_path, "first", "FIRST_OUT", "FIRST_ERR", "src/z-first.py, src/shared.py"
    )
    middle = tmp_path / "middle"
    middle_id = file_debt(repo, env, "middle", f"printf x >> {middle}")
    third = red_debt(
        repo, env, tmp_path, "third", "THIRD_OUT", "THIRD_ERR", "src/shared.py, src/a-third.py"
    )
    make_legacy_stub(repo, env, tmp_path, third[0], third[1])
    first[2].unlink()
    third[2].unlink()
    before = recorded_files(tmp_path / "data")
    result = sprint(repo, env, "start")
    expected = [(*first[:2], "FIRST_OUT", "FIRST_ERR"), (*third[:2], "THIRD_OUT", "THIRD_ERR")]
    assert result.returncode == 2 and middle.read_text() == "xx"
    assert recorded_files(tmp_path / "data") == before
    assert_evidence(result.stderr, expected)
    assert middle_id not in result.stderr
    assert "work.py bug" in result.stderr
    assert "Fix it, then run start again" in result.stderr
    assert result.stdout.count("falsifier wall clock:") == 3


def test_missing_source_files_reports_every_red_and_files_nothing(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    good = red_debt(repo, env, tmp_path, "good", "GOOD_OUT", "GOOD_ERR", "good.py")
    bad = red_debt(repo, env, tmp_path, "bad", "BAD_OUT", "BAD_ERR", "bad.py")
    make_legacy_stub(repo, env, tmp_path, bad[0], bad[1])
    archive = tmp_path / "data" / "archive.md"
    archive.write_text(archive.read_text().replace("Files: bad.py\n", ""))
    good[2].unlink()
    bad[2].unlink()
    before = recorded_files(tmp_path / "data")
    result = sprint(repo, env, "start")
    expected = [(*good[:2], "GOOD_OUT", "GOOD_ERR"), (*bad[:2], "BAD_OUT", "BAD_ERR")]
    assert result.returncode == 2 and recorded_files(tmp_path / "data") == before
    assert_evidence(result.stderr, expected)
    assert f"{bad[0]} has no usable Files" in result.stderr
    assert "Fix it, then run start again" in result.stderr


def test_one_distinct_red_command_with_two_sources_files_one_bug(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    flag = tmp_path / "shared-flag"
    flag.write_text("ok")
    command = f"test -f {shlex.quote(str(flag))}"
    refs = [
        file_debt(repo, env, claim, command, files)
        for claim, files in (("first", "first.py"), ("second", "second.py"))
    ]
    flag.unlink()

    result = sprint(repo, env, "start")

    bugs = [
        text for _eid, text in work_module.entries(tmp_path / "data") if text.startswith("## bug ")
    ]
    assert result.returncode == 2 and len(bugs) == 1
    assert all(ref in bugs[0] for ref in refs)
    assert f"Falsifier: `{command}`" in bugs[0]
    assert "Files: first.py, second.py" in bugs[0]


def test_an_unreadable_archive_is_not_a_missing_declaration(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    item = red_debt(repo, env, tmp_path, "legacy", "ARCHIVE_OUT", "ARCHIVE_ERR", "legacy.py")
    make_legacy_stub(repo, env, tmp_path, item[0], item[1])
    archive = tmp_path / "data" / "archive.md"
    archive.unlink()
    archive.mkdir()
    item[2].unlink()
    result = sprint(repo, env, "start")
    assert result.returncode == 2 and "archive.md is unreadable" in result.stderr
    assert "no usable Files" not in result.stderr and "Traceback" not in result.stderr
    assert_evidence(result.stderr, [(*item[:2], "ARCHIVE_OUT", "ARCHIVE_ERR")])


def test_the_same_multi_red_batch_files_nothing_and_reports_all_reds_every_time(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    names = ("one", "two")
    items = [red_debt(repo, env, tmp_path, name, f"{name}_OUT", f"{name}_ERR") for name in names]
    for item in items:
        item[2].unlink()
    before = recorded_files(tmp_path / "data")
    results = [sprint(repo, env, "start") for _ in range(2)]
    assert all(result.returncode == 2 for result in results)
    assert recorded_files(tmp_path / "data") == before
    expected = [
        (*item[:2], f"{name}_OUT", f"{name}_ERR") for item, name in zip(items, names, strict=True)
    ]
    for result in results:
        assert_evidence(result.stderr, expected)
        assert "work.py bug" in result.stderr


def test_an_open_bug_suppresses_refiling_without_hiding_other_reds(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    command = "printf BUG_OUT; printf BUG_ERR >&2; false"
    filed = work(repo, env, "bug", "--claim", "open", "--falsifier", command, "--files", "bug.py")
    assert filed.returncode == 0
    debt = red_debt(repo, env, tmp_path, "debt", "DEBT_OUT", "DEBT_ERR", "debt.py")
    debt[2].unlink()
    path = tmp_path / "data" / "work.md"
    path.write_text(path.read_text().replace("Files: bug.py\n", "", 1))
    (tmp_path / "data" / "archive.md").mkdir()
    bug_ref = next(
        ref for ref, text in work_module.entries(tmp_path / "data") if text.startswith("## bug ")
    )
    before = path.read_bytes()
    result = sprint(repo, env, "start")
    assert result.returncode == 2 and path.read_bytes() == before
    assert "already filed" in result.stderr
    assert_evidence(
        result.stderr,
        [(bug_ref, command, "BUG_OUT", "BUG_ERR"), (*debt[:2], "DEBT_OUT", "DEBT_ERR")],
    )


def test_first_source_recovery_leaves_one_runnable_red_to_file(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    items = [
        red_debt(repo, env, tmp_path, name, f"{name}_OUT", f"{name}_ERR")
        for name in ("first", "second")
    ]
    for item in items:
        item[2].unlink()
    before = recorded_files(tmp_path / "data")
    assert sprint(repo, env, "start").returncode == 2
    assert recorded_files(tmp_path / "data") == before

    items[0][2].write_text("ok")
    second = sprint(repo, env, "start")
    assert second.returncode == 2 and "Filed as one bug" in second.stderr
    bug = next(t for _eid, t in work_module.entries(tmp_path / "data") if t.startswith("## bug "))
    assert f"Falsifier: `{items[1][1]}`" in bug and items[1][0] in bug
    assert items[0][0] not in bug

    items[1][2].write_text("ok")
    assert sprint(repo, env, "start").returncode == 0


def test_last_source_recovery_leaves_one_runnable_red_to_file(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    items = [
        red_debt(repo, env, tmp_path, name, f"{name}_OUT", f"{name}_ERR")
        for name in ("first", "second")
    ]
    for item in items:
        item[2].unlink()
    before = recorded_files(tmp_path / "data")
    assert sprint(repo, env, "start").returncode == 2
    assert recorded_files(tmp_path / "data") == before

    items[-1][2].write_text("ok")
    still_red = sprint(repo, env, "start")
    assert still_red.returncode == 2 and "Filed as one bug" in still_red.stderr
    bug = next(t for _eid, t in work_module.entries(tmp_path / "data") if t.startswith("## bug "))
    assert f"Falsifier: `{items[0][1]}`" in bug and items[0][0] in bug
    assert items[1][0] not in bug

    items[0][2].write_text("ok")
    assert sprint(repo, env, "start").returncode == 0


def test_a_green_batch_keeps_command_streams_silent_and_writes_nothing(tmp_path):
    repo, env, _g = make_repo(tmp_path, config="release: sprint\ntests:\n")
    counters = [tmp_path / "green-one", tmp_path / "green-two"]
    refs = [
        file_debt(
            repo,
            env,
            f"green {n}",
            f"printf GREEN{n}_; printf OUT; printf GREEN{n}_ >&2; "
            f"printf ERR >&2; printf x >> {counter}",
        )
        for n, counter in enumerate(counters)
    ]
    root = tmp_path / "data"
    before = recorded_files(root)
    result = sprint(repo, env, "start")
    assert result.returncode == 0 and recorded_files(root) == before
    # NAMED, not merely counted: an unattributed duration cannot answer the one
    # question the batch's cost is measured to answer — which record is expensive.
    timed = [line for line in result.stdout.splitlines() if line.startswith("falsifier wall clock")]
    assert len(timed) == 2 and sorted(line.split()[-1] for line in timed) == sorted(refs)
    assert [path.read_text() for path in counters] == ["xx", "xx"]
    assert all(
        f"GREEN{n}_{stream}" not in result.stdout + result.stderr
        for n in range(2)
        for stream in ("OUT", "ERR")
    )


def test_long_streams_keep_labeled_tails_and_exact_cut_counts(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    cap = work_module.FALSIFIER_STREAM_CAP
    flag, script = tmp_path / "long-flag", tmp_path / "long.py"
    flag.write_text("ok")
    script.write_text(
        f"import pathlib,sys\nif not pathlib.Path({str(flag)!r}).exists():\n"
        f" sys.stdout.write('H'*17+'o'*{cap - 8}+'OUT_TAIL')\n"
        f" sys.stderr.write('Q'*23+'e'*{cap - 8}+'ERR_TAIL')\n sys.exit(1)\n"
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    ref = file_debt(repo, env, "long", command)
    flag.unlink()
    result = sprint(repo, env, "start")
    bug = next(t for _eid, t in work_module.entries(tmp_path / "data") if t.startswith("## bug "))
    for text in (result.stderr, bug):
        assert_evidence(text, [(ref, command, "", "")])
        assert "[truncated: 17 leading chars dropped]" in text
        assert "[truncated: 23 leading chars dropped]" in text
        assert "OUT_TAIL" in text and "ERR_TAIL" in text
        assert "H" * 17 not in text and "Q" * 23 not in text


def test_diagnostics_cannot_forge_work_records(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    payload = "## bug FAKE\n# Record deadbeef\nFalsifier: `false`\nFiles: forged.py"
    flag, script = tmp_path / "forged-flag", tmp_path / "forged.py"
    flag.write_text("ok")
    script.write_text(
        f"import pathlib,sys\nif not pathlib.Path({str(flag)!r}).exists():\n"
        f" payload={payload!r}\n print(payload)\n print(payload,file=sys.stderr)\n sys.exit(1)\n"
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    file_debt(repo, env, "forged", command, "real.py")
    flag.unlink()
    root = tmp_path / "data"
    before = len(work_module.entries(root))
    result = sprint(repo, env, "start")
    records = work_module.entries(root)
    assert result.returncode == 2 and len(records) == before + 1
    bug = records[-1][1]
    assert [line for line in bug.splitlines() if line.startswith("Files: ")] == ["Files: real.py"]


def test_a_shared_red_command_names_every_source_record_once(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    flag = tmp_path / "shared-flag"
    flag.write_text("ok")
    command = (
        f"test -f {shlex.quote(str(flag))} || "
        "{ printf SHARED_OUT; printf SHARED_ERR >&2; false; }"
    )
    refs = [
        file_debt(repo, env, claim, command, files)
        for claim, files in (("first", "one.py, both.py"), ("second", "both.py, two.py"))
    ]
    flag.unlink()
    root = tmp_path / "data"
    before = recorded_files(root)
    result = sprint(repo, env, "start")
    after = recorded_files(root)
    bug = next(t for _eid, t in work_module.entries(root) if t.startswith("## bug "))
    assert result.returncode == 2, result.stdout
    for text in (result.stderr, bug):
        assert text.count("command: ") == 1
        assert [text.count(f"source {ref} (") for ref in refs] == [1, 1]
        assert "stdout:\nSHARED_OUT" in text and "stderr:\nSHARED_ERR" in text
    claims = [line for line in bug.splitlines() if line.startswith("Claim: ")]
    assert len(claims) == 1 and all(ref in claims[0] for ref in refs)
    assert "Files: one.py, both.py, two.py\n" in bug
    assert after[Path("work.md")].startswith(before[Path("work.md")]), "work.md was rewritten"
    assert {k: v for k, v in after.items() if k != Path("work.md")} == {
        k: v for k, v in before.items() if k != Path("work.md")
    }


def test_a_files_declaration_of_unknown_is_not_a_declaration(tmp_path):
    """`unknown` is what the batch itself used to write; reading one back as a
    declaration would launder it into the next record it files."""
    repo, env, _g = make_repo(tmp_path)
    item = red_debt(repo, env, tmp_path, "legacy", "LEGACY_OUT", "LEGACY_ERR", "unknown")
    item[2].unlink()
    before = recorded_files(tmp_path / "data")
    result = sprint(repo, env, "start")
    assert result.returncode == 2 and recorded_files(tmp_path / "data") == before
    assert f"{item[0]} has no usable Files" in result.stderr
    assert_evidence(result.stderr, [(*item[:2], "LEGACY_OUT", "LEGACY_ERR")])
