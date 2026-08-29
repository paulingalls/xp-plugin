"""The sprint-close falsifier batch executes and reports by distinct command."""

import inspect
import shlex
from pathlib import Path

import pytest
import work as work_module
from sprint_helpers import (
    CONFIG,
    WORK_SECTION,
    launches,
    make_repo,
    section,
    snapshot,
    sprint,
    work,
)


class TestFalsifierBatch:
    def test_a_red_falsifier_aborts_and_is_refiled_as_a_bug(self, tmp_path):
        """Constructed, never observed: the fixture files a debt whose falsifier is
        green now and makes it red before the batch runs."""
        repo, env, _g = make_repo(tmp_path)
        flag = tmp_path / "flag"
        flag.write_text("ok")
        work(
            repo,
            env,
            "debt",
            "--claim",
            "latent",
            "--falsifier",
            f"test -f {flag}",
            "--files",
            "a.py",
        )
        flag.unlink()
        root = tmp_path / "data"
        before = snapshot(root)
        r = sprint(repo, env, "start")
        assert r.returncode == 2, r.stdout
        assert "latent" in r.stderr or "latent" in r.stdout
        after = snapshot(root)
        assert "## bug " in after[Path("work.md")].decode()
        # the append branch of the read-only property, which the green path
        # cannot reach: this is the only leg that writes anything at all
        assert after[Path("work.md")].startswith(before[Path("work.md")]), "work.md was rewritten"
        assert {k: v for k, v in after.items() if k != Path("work.md")} == {
            k: v for k, v in before.items() if k != Path("work.md")
        }

    def test_re_running_against_an_unfixed_red_files_one_bug_not_one_per_run(self, tmp_path):
        """The red path is the one that actually gets re-run — you fix, then run
        again. Each run appended a fresh duplicate, and every duplicate is itself
        a live record needing its own resolution, so the debris self-perpetuates."""
        repo, env, _g = make_repo(tmp_path)
        flag = tmp_path / "flag"
        flag.write_text("ok")
        work(
            repo,
            env,
            "debt",
            "--claim",
            "latent",
            "--falsifier",
            f"test -f {flag}",
            "--files",
            "a.py",
        )
        flag.unlink()
        for _ in range(3):
            assert sprint(repo, env, "start").returncode == 2
        filed = (tmp_path / "data" / "work.md").read_text().count("## bug ")
        assert filed == 1, f"three runs filed {filed} bugs for one unfixed red"

    def test_a_resolved_record_runs_the_RESOLUTION_falsifier_not_nothing(self, tmp_path):
        """A resolution that was wrong must red later and reopen the record."""
        repo, env, _g = make_repo(tmp_path)
        flag = tmp_path / "fixed"
        flag.write_text("ok")
        work(repo, env, "bug", "--claim", "broken", "--falsifier", "false", "--files", "a.py")
        ref = work(repo, env, "list").stdout.split()[0]
        assert (
            work(repo, env, "resolve", "--ref", ref, "--falsifier", f"test -f {flag}").returncode
            == 0
        )
        assert sprint(repo, env, "start").returncode == 0, "a green resolution should pass"
        flag.unlink()  # the fix regressed
        r = sprint(repo, env, "start")
        assert r.returncode == 2, "a resolved record was skipped instead of re-checked"

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


def file_debt(repo, env, claim, command, covered_by=""):
    args = ["debt", "--claim", claim, "--falsifier", command, "--files", "a.py"]
    if covered_by:
        args += ["--covered-by", covered_by]
    result = work(repo, env, *args)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


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
        "resolve": ["resolve", "--ref", ref, "--falsifier", writes(replacement)],
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
    stale = work(repo, env, "resolve", "--ref", ref, "--falsifier", writes(replacement))
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


def shared_red_batch(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    flag = tmp_path / "shared-red"
    flag.write_text("ok")
    command = f"test -f {shlex.quote(str(flag))}"
    ids = [file_debt(repo, env, claim, command) for claim in ("first", "second")]
    flag.unlink()
    return ids, sprint(repo, env, "start"), tmp_path / "data" / "work.md"


def test_a_shared_red_falsifier_refusal_names_every_record(tmp_path):
    ids, result, _work_md = shared_red_batch(tmp_path)
    assert result.returncode == 2
    assert all(eid in result.stderr for eid in ids)


def test_a_shared_red_falsifier_bug_claim_names_every_record(tmp_path):
    ids, result, work_md = shared_red_batch(tmp_path)
    assert result.returncode == 2
    bug = work_md.read_text().rsplit("## bug ", 1)[1]
    claims = [line for line in bug.splitlines() if line.startswith("Claim: ")]
    assert len(claims) == 1
    assert all(eid in claims[0] for eid in ids)


def test_falsifier_execution_has_no_per_record_context():
    assert list(inspect.signature(work_module.falsifier_is_green).parameters) == ["command"]


def writes(path, succeeds=True):
    return f"printf x >> {shlex.quote(str(path))}; {'true' if succeeds else 'false'}"


def test_a_green_full_tier_is_trusted_without_reexecuting_the_falsifier(tmp_path):
    tier, falsifier = tmp_path / "tier", tmp_path / "falsifier"
    config = CONFIG.replace("full: true", f"full: {writes(tier)}")
    repo, env, _g = make_repo(tmp_path, config=config)
    ref = file_debt(repo, env, "covered claim", writes(falsifier), "full")
    before = falsifier.read_text()

    result = sprint(repo, env, "start")

    assert result.returncode == 0, result.stderr
    assert tier.read_text() == "x" and falsifier.read_text() == before
    # not `"full" in stdout`: the `running the full tier:` line already carries
    # the name, so that spelling greens against a report naming no tier at all
    assert f"trusted {ref}" in result.stdout and "via tier full" in result.stdout


def test_a_shared_command_with_a_legacy_record_is_not_deferred(tmp_path):
    tier, falsifier = tmp_path / "tier", tmp_path / "falsifier"
    config = CONFIG.replace("full: true", f"full: {writes(tier)}")
    repo, env, _g = make_repo(tmp_path, config=config)
    command = writes(falsifier)
    file_debt(repo, env, "covered claim", command, "full")
    file_debt(repo, env, "legacy claim", command)
    before = falsifier.read_text()

    result = sprint(repo, env, "start")

    assert result.returncode == 0, result.stderr
    assert tier.read_text() == "x" and falsifier.read_text() == before + "x"
    assert "trusted" not in result.stdout


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


def test_a_declared_tier_that_was_not_run_does_not_suppress_the_falsifier(tmp_path):
    falsifier = tmp_path / "falsifier"
    config = CONFIG.replace("tests:\n", "tests:\n  fast: true\n")
    repo, env, _g = make_repo(tmp_path, config=config)
    file_debt(repo, env, "fast selection", writes(falsifier), "fast")
    before = falsifier.read_text()

    result = sprint(repo, env, "start")

    assert result.returncode == 0, result.stderr
    assert falsifier.read_text() == before + "x"
    assert "trusted" not in result.stdout


def test_a_red_full_tier_runs_the_deferred_falsifier_before_refusing(tmp_path):
    tier, falsifier = tmp_path / "tier", tmp_path / "falsifier"
    config = CONFIG.replace("full: true", f"full: {writes(tier, False)}")
    repo, env, _g = make_repo(tmp_path, config=config)
    file_debt(repo, env, "covered claim", writes(falsifier), "full")
    before = falsifier.read_text()

    result = sprint(repo, env, "start")

    assert result.returncode == 2 and "full tier" in result.stderr
    assert tier.read_text() == "x" and falsifier.read_text() == before + "x"


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
    assert "tier" not in (result.stdout + result.stderr).lower()


def test_a_resolution_without_a_declaration_executes_its_replacement(tmp_path):
    counter = tmp_path / "replacement"
    repo, env, _g = make_repo(tmp_path)
    result = work(
        repo,
        env,
        "bug",
        "--claim",
        "fixed",
        "--falsifier",
        "false",
        "--files",
        "a",
        "--covered-by",
        "full",
    )
    assert result.returncode == 0, result.stderr
    ref = result.stdout.strip()
    assert work(repo, env, "resolve", "--ref", ref, "--falsifier", writes(counter)).returncode == 0
    before = counter.read_text()

    assert sprint(repo, env, "start").returncode == 0
    assert counter.read_text() == before + "x"


def test_a_resolution_coverage_declaration_is_visible_to_sprint_review(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    filed = work(
        repo,
        env,
        "bug",
        "--claim",
        "fixed",
        "--falsifier",
        "false",
        "--files",
        "a",
    )
    result = work(
        repo,
        env,
        "resolve",
        "--ref",
        filed.stdout.strip(),
        "--falsifier",
        "true",
        "--covered-by",
        "full",
    )
    assert result.returncode == 0, result.stderr

    assert sprint(repo, env, "review").returncode == 0
    body = section(
        launches(tmp_path)[0]["stdin"], "Resolutions filed during the sprint", WORK_SECTION
    )
    assert "covered by: full" in body
