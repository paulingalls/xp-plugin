"""The sprint-close falsifier batch executes and reports by distinct command."""

import inspect
import shlex
import subprocess
from unittest.mock import patch

import pytest
import work as work_module
from sprint_helpers import (
    CONFIG,
    make_repo,
    sprint,
    work,
)


def test_falsifier_result_measures_the_command_wall_clock():
    completed = subprocess.CompletedProcess("true", 0, "out", "err")
    with (
        patch.object(work_module.time, "perf_counter", side_effect=[10.0, 12.75]),
        patch.object(work_module.subprocess, "run", return_value=completed),
    ):
        result = work_module.falsifier_result("true")
    assert (result.returncode, result.stdout, result.stderr, result.elapsed) == (
        0,
        "out",
        "err",
        2.75,
    )


def test_resolve_rejects_an_empty_falsifier_without_writing_a_resolution(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    filed = work(repo, env, "bug", "--claim", "fixed", "--falsifier", "false", "--files", "a.py")
    ledger = tmp_path / "data" / "work.md"
    before = ledger.read_bytes()

    result = work(
        repo,
        env,
        "resolve",
        "--ref",
        filed.stdout.strip(),
        "--falsifier",
        "",
    )

    assert result.returncode == 2 and "falsifier" in result.stderr
    assert ledger.read_bytes() == before


class TestFalsifierBatch:
    def test_only_a_resolved_record_can_substitute_a_falsifier(self, tmp_path):
        """Keyed off the heading `resolve` writes, never off a `Resolves:` line
        anywhere in a block: a record that merely REFERENCES an id would
        substitute its own green falsifier, silencing a live bug with the
        green-check that resolve exists to enforce never having run."""
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "bug", "--claim", "live", "--falsifier", "false", "--files", "a.py")
        victim = work(repo, env, "list").stdout.split()[0]
        work(
            repo,
            env,
            "debt",
            "--claim",
            f"partial cleanup\nResolves: {victim}",
            "--falsifier",
            "true",
            "--files",
            "a.py",
        )
        r = sprint(repo, env, "start")
        assert r.returncode == 2, "a record that only referenced an id silenced a live bug"


def file_debt(repo, env, claim, command):
    args = ["debt", "--claim", claim, "--falsifier", command, "--files", "a.py"]
    result = work(repo, env, *args)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize("mode, code", [("missing", 127), ("not_executable", 126)])
def test_unrun_falsifier_refuses_without_filing(tmp_path, mode, code):
    repo, env, _g = make_repo(tmp_path)
    script = tmp_path / "check"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    ref = file_debt(repo, env, "environment command", str(script))
    ledger = tmp_path / "data" / "work.md"
    before = ledger.read_bytes()
    if mode == "missing":
        script.unlink()
    else:
        script.chmod(0o644)

    result = sprint(repo, env, "start")

    assert result.returncode == 2 and ledger.read_bytes() == before
    assert str(script) in result.stderr and ref in result.stderr
    assert "could not run" in result.stderr and "work.py bug" in result.stderr
    assert f"{code}" in result.stderr


def live_control(repo, env, tmp_path):
    """A record the batch MUST run. Every exclusion below asserts only that a
    counter did not grow, and that greens just as well against a close whose
    batch executes nothing at all — the mutation constraint 2 calls certifying."""
    counter = tmp_path / "control"
    file_debt(repo, env, "live control", writes(counter))
    return counter


def archive_debt(repo, env, counter):
    ref = file_debt(repo, env, "disposed", writes(counter))
    before = counter.read_text()
    assert work(repo, env, "archive", "--ref", ref, "--disposition", "dropped").returncode == 0
    return ref, before


def test_an_archived_debt_falsifier_is_not_executed(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    counter = tmp_path / "archived"
    _ref, before = archive_debt(repo, env, counter)
    control = live_control(repo, env, tmp_path)

    assert sprint(repo, env, "start").returncode == 0
    assert counter.read_text() == before
    assert control.read_text() == "xx"


def test_a_compacted_archived_debt_falsifier_is_not_executed(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    counter = tmp_path / "compacted"
    ref, before = archive_debt(repo, env, counter)
    control = live_control(repo, env, tmp_path)
    assert work(repo, env, "compact").returncode == 0
    compacted = (tmp_path / "data" / "work.md").read_text()
    stub = f"Id: {ref}\nArchives: {ref}\nDisposition: dropped\nFalsifier: `{writes(counter)}`"
    assert stub in compacted, compacted

    assert sprint(repo, env, "start").returncode == 0
    assert counter.read_text() == before
    assert control.read_text() == "xx"


@pytest.mark.parametrize("order", [("resolve", "archive"), ("archive", "resolve")])
def test_archive_wins_over_resolution_before_and_after_compaction(tmp_path, order):
    """Archive wins in both orders, including the compacted one-field stub."""
    repo, env, _g = make_repo(tmp_path)
    original, replacement = tmp_path / "original", tmp_path / "replacement"
    ref = file_debt(repo, env, "disposed after repair", writes(original))
    steps = {
        "resolve": [
            "resolve",
            "--ref",
            ref,
            "--falsifier",
            writes(replacement),
        ],
        "archive": ["archive", "--ref", ref, "--disposition", "dropped"],
    }
    for step in order:
        result = work(repo, env, *steps[step])
        if order[0] == "archive" and step == "resolve":
            assert result.returncode == 2 and "archived" in result.stderr
        else:
            assert result.returncode == 0, step

    def contents(path):
        return path.read_text() if path.exists() else ""

    before = contents(original), contents(replacement)
    control = live_control(repo, env, tmp_path)

    assert sprint(repo, env, "start").returncode == 0
    assert (contents(original), contents(replacement)) == before
    assert control.read_text() == "xx"
    assert work(repo, env, "compact").returncode == 0
    stale = work(
        repo,
        env,
        "resolve",
        "--ref",
        ref,
        "--falsifier",
        writes(replacement),
    )
    assert stale.returncode == 2 and "archived" in stale.stderr
    assert sprint(repo, env, "start").returncode == 0
    assert (contents(original), contents(replacement)) == before
    assert control.read_text() == "xxx"


def test_an_archives_mention_does_not_dispose_another_record(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    counter = tmp_path / "still-live"
    ref = file_debt(repo, env, "must remain live", writes(counter))
    before = counter.read_text()
    with (tmp_path / "data" / "work.md").open("a") as records:
        records.write(
            "## bug 2026-01-01T00:00:00Z\nClaim: hand-written mention\n"
            f"Archives: {ref}\nFalsifier: `false`\nFiles: a.py\n\n"
        )

    assert sprint(repo, env, "start").returncode == 2
    assert counter.read_text() == before + "x"


def test_a_shared_falsifier_executes_once(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    counter = tmp_path / "shared"
    command = f"printf x >> {shlex.quote(str(counter))}"
    file_debt(repo, env, "first citation", command)
    file_debt(repo, env, "second citation", command)
    before = counter.read_text()
    assert sprint(repo, env, "start").returncode == 0
    assert counter.read_text() == before + "x"


def test_different_falsifiers_both_execute(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    counters = [tmp_path / "first", tmp_path / "second"]
    for n, counter in enumerate(counters):
        file_debt(repo, env, f"citation {n}", f"printf x >> {shlex.quote(str(counter))}")
    assert sprint(repo, env, "start").returncode == 0
    assert [counter.read_text() for counter in counters] == ["xx", "xx"]


def test_falsifier_execution_has_no_per_record_context():
    assert list(inspect.signature(work_module.falsifier_is_green).parameters) == ["command"]
    assert work_module.falsifier_is_green("true") is True
    assert work_module.falsifier_is_green("false") is False
    result = work_module.falsifier_result("printf out; printf err >&2; false")
    assert result.returncode != 0 and result.stdout == "out" and result.stderr == "err"


def writes(path, succeeds=True):
    return f"printf x >> {shlex.quote(str(path))}; {'true' if succeeds else 'false'}"


def test_a_declaration_whose_tier_the_config_no_longer_defines_still_executes(tmp_path):
    """The record names `full`, the project renamed it, so no run of `full`
    happened this close. Without the configured-tier half of the defer test the
    command is dropped in silence — no execution and no `trusted` line either."""
    counter = tmp_path / "renamed-tier"
    repo, env, _g = make_repo(tmp_path, config=CONFIG.replace("full:", "nightly:"))
    (tmp_path / "data" / "work.md").write_text(
        "## debt 2026-01-01T00:00:00Z\nClaim: declared before the tier was renamed\n"
        f"Falsifier: `{writes(counter)}`\nCovered by: full\nFiles: old.py\n\n"
    )

    result = sprint(repo, env, "start")

    assert result.returncode == 0, result.stderr
    ran = counter.read_text() if counter.exists() else "never executed"
    assert ran == "x", f"took a verdict from a tier that never ran: {ran}"
    assert "trusted" not in result.stdout


def test_a_project_with_no_tiers_executes_legacy_records_without_tier_prose(tmp_path):
    repo, env, _g = make_repo(tmp_path, config="release: sprint\nroles:\n  reviewer: claude/opus\n")
    counter = tmp_path / "legacy"
    (tmp_path / "data" / "work.md").write_text(
        "## debt 2026-01-01T00:00:00Z\nClaim: legacy\n"
        f"Falsifier: `{writes(counter)}`\nFiles: old.py\n\n"
    )

    result = sprint(repo, env, "start")

    assert result.returncode == 0, result.stderr
    assert counter.read_text() == "x"
    assert "Covered by:" not in result.stdout and "tier_coverage" not in result.stdout
