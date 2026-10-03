"""The structured gate: what a recorded round contains, and what land discloses
from it at the moment of assent.

Extracted from test_close_land.py at the Sprint-17 close (constraint 8: 519 lines
against the 500 cap). The seam is the artifact — round records and their
disclosure here, land's other failure modes and bookkeeping there.
"""

import json

from close_free_card_cases import add_free_card, checkout_free, commit_on_free, spawn_free
from close_helpers import (
    CLEAN,
    close,
    free,
    free_repo,
    gh_calls,
    make_repo,
    marker,
    marker_file,
    stub_reviewer,
)


def overflowing_findings():
    return CLEAN | {
        "fixed": [f"fixed-{i:02}" for i in range(25)],
        "blocking": [f"blocking-{i:02}" for i in range(25)],
        "dropped": [{"finding": f"dropped-{i:02}", "reason": "fixture reason"} for i in range(25)],
    }


def story_prior(bundle):
    start = bundle.index("## Earlier rounds of THIS review\n\n")
    start += len("## Earlier rounds of THIS review\n\n")
    return bundle[start : bundle.index("\n\n## Cumulative diff", start)]


class TestBoundedDurableBody:
    def test_story_body_names_complete_round_reports_that_outlive_cleanup(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        findings = overflowing_findings()
        findings["fixed"][0] = "x" * 5000
        stub_reviewer(tmp_path, report=findings)
        assert close(repo, env, "review").returncode == 2
        (repo / "src/thing.py").write_text("A = 3\n")
        g("commit", "-qam", "lead correction")
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0

        reports = tmp_path / "data" / "reports"
        paths = [reports / f"story-042.round-{n}.json" for n in (1, 2)]
        saved = json.loads(paths[0].read_text())
        recorded = marker(tmp_path)["rounds"][0]
        assert all(path.is_file() for path in paths)
        assert recorded["fixed"][0] == "x" * 5000
        assert len(recorded["dropped"]) == len(findings["dropped"])
        assert all(
            saved[status][-1] == findings[status][-1] for status in ("fixed", "blocking", "dropped")
        )

        assert close(repo, env, "land").returncode == 0
        body = g("log", "-1", "--format=%B", "main").stdout
        for status in ("fixed", "blocking", "dropped"):
            first = recorded[status][0]
            last = recorded[status][-1]
            first = first["finding"] if isinstance(first, dict) else first
            last = last["finding"] if isinstance(last, dict) else last
            assert first[:400] in body and last not in body
            assert sum(line.startswith(f"  {status}:") for line in body.splitlines()) == 20
        notice = "(+6 more, in full at reports/story-042.round-1.json)"
        assert body.count(notice) == 3
        assert str(tmp_path / "data") not in body
        assert "at reports)" not in body and "closes.jsonl" not in body
        assert not marker_file(tmp_path).exists()
        assert all(path.is_file() for path in paths)
        assert json.loads(paths[0].read_text()) == saved

    def test_each_rounds_elision_names_that_rounds_own_report(self, tmp_path):
        """A body with ONE overflowing round greens against a static `round-1`, which
        is the defect TestLandNamesEachRoundsOwnDiff below caught in the other renderer."""
        repo, env, g = make_repo(tmp_path)
        for prefix in ("first", "second"):
            report = CLEAN | {"fixed": [f"{prefix}-{i:02}" for i in range(25)]}
            stub_reviewer(tmp_path, report=report)
            assert close(repo, env, "review").returncode == 0
        assert close(repo, env, "land").returncode == 0

        one, two = g("log", "-1", "--format=%B", "main").stdout.split("Review round 2:")
        assert "first-18" in one and "second-18" in two
        assert "in full at reports/story-042.round-1.json" in one and "round-2" not in one
        assert "in full at reports/story-042.round-2.json" in two and "round-1" not in two

    def test_free_pr_body_names_its_complete_report_after_cleanup(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "fix-typo", "start").returncode == 0
        branch, key = checkout_free(g)
        commit_on_free(repo, g)
        add_free_card(env, key)
        tree = spawn_free(repo, env, g, tmp_path, key)
        findings = {
            "fixed": [],
            "blocking": [],
            "schema": 2,
            "dropped": [
                {"finding": item, "reason": "fixture reason"}
                for item in [f"free-note-{i:02}" for i in range(25)]
            ],
            "debt": [],
        }
        stub_reviewer(tmp_path, report=findings)
        assert free(tree, env, "fix-typo", "review").returncode == 0
        report = tmp_path / "data" / "reports" / f"{key}.round-2.json"
        saved = json.loads(report.read_text())
        assert saved["dropped"][-1]["finding"] == "free-note-24"

        assert free(tree, env, "fix-typo", "land").returncode == 0
        create = next(call for call in gh_calls(tmp_path) if call[:2] == ["pr", "create"])
        body = create[create.index("--body") + 1]
        assert "free-note-00" in body and "free-note-24" not in body
        assert sum(line.startswith("  dropped:") for line in body.splitlines()) == 20
        assert body.count(f"(+6 more, in full at reports/{key}.round-2.json)") == 1
        assert str(tmp_path / "data") not in body
        assert "at reports)" not in body and "closes.jsonl" not in body

        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", branch, "-m", "merge free release")
        assert free(repo, env, "fix-typo", "post-merge").returncode == 0
        assert not marker_file(tmp_path, key).exists()
        assert json.loads(report.read_text()) == saved


class TestLandNamesEachRoundsOwnDiff:
    """Sprint-17 sprint-review blocking finding. The per-round disclosure fix landed
    in `review.disclose` and in sprint_close's callable, but land's STORY leg kept a
    single static path — so every round but the last was printed under the wrong
    assent artifact: round 1's commits above a `full diff:` naming round 2's file."""

    def test_each_disclosed_round_names_its_own_diff_file(self, tmp_path):
        """CONSTRUCTS two recorded rounds with real commits and reads what land
        printed. A static path satisfies any assertion that only counts rounds, so
        this pairs each round's commit subject with the diff filename beside it."""
        repo, env, g = make_repo(tmp_path, files="src/thing.py, round-1.py, round-2.py")
        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0
        state = json.loads(marker_file(tmp_path).read_text())
        shas = [g("rev-parse", "HEAD").stdout.strip()]
        for n in (1, 2):
            (repo / f"round-{n}.py").write_text(f"ROUND_{n} = True\n")
            g("add", "-A")
            g("commit", "-qm", f"REVIEWER-ROUND-{n}")
            shas.append(g("rev-parse", "HEAD").stdout.strip())
        rounds = [{**CLEAN, "reviewed_head": shas[n], "shown_sha": shas[n + 1]} for n in range(2)]
        marker_file(tmp_path).write_text(json.dumps({**state, "rounds": rounds, **rounds[-1]}))
        r = close(repo, env, "land")
        out = r.stdout
        assert "REVIEWER-ROUND-1" in out, (r.returncode, r.stdout[-1500:], r.stderr[-1500:])
        first = out.index("REVIEWER-ROUND-1")
        assert "round-1.diff" in out[first : out.index("REVIEWER-ROUND-2")], (
            "round 1's commits were disclosed under another round's diff:\n" + out
        )

    def test_a_killed_first_round_does_not_shift_the_second_onto_its_diff(self, tmp_path):
        """The same defect reached through the NUMBERING rather than the path. A round
        killed mid-review records no coverage (`sprint_close.stop`, `cmd_salvage`), and
        dropping it renumbers round 2 as round 1 — so land names round-1.diff over
        round 2's commits, a file holding a different diff or none at all."""
        repo, env, g = make_repo(tmp_path, files="src/thing.py, round-2.py")
        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0
        state = json.loads(marker_file(tmp_path).read_text())
        start = g("rev-parse", "HEAD").stdout.strip()
        (repo / "round-2.py").write_text("ROUND_2 = True\n")
        g("add", "-A")
        g("commit", "-qm", "REVIEWER-ROUND-2")
        shown = g("rev-parse", "HEAD").stdout.strip()
        killed = {**CLEAN, "incomplete": "the host killed round 1"}
        done = {**CLEAN, "reviewed_head": start, "shown_sha": shown}
        marker_file(tmp_path).write_text(json.dumps({**state, "rounds": [killed, done], **done}))
        r = close(repo, env, "land")
        assert "REVIEWER-ROUND-2" in r.stdout, (r.returncode, r.stdout[-1500:], r.stderr[-1500:])
        assert "round-2.diff" in r.stdout and "round-1.diff" not in r.stdout, (
            "round 2 was disclosed under the killed round's diff name:\n" + r.stdout
        )

    def test_a_salvaged_round_is_disclosed_under_the_diff_it_was_written_as(self, tmp_path):
        """The third route to the same defect, and the one list index cannot answer.
        Salvage INSERTS an older attempt at its chronological place, so from there on
        every later round sits one index past the file rotate_story named it for —
        `round_file` is the pairing, and nothing drove it through land until here."""
        repo, env, g = make_repo(tmp_path, files="src/thing.py, salvaged.py")
        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0
        state = json.loads(marker_file(tmp_path).read_text())
        start = g("rev-parse", "HEAD").stdout.strip()
        (repo / "salvaged.py").write_text("SALVAGED = True\n")
        g("add", "-A")
        g("commit", "-qm", "REVIEWER-SALVAGED")
        shown = g("rev-parse", "HEAD").stdout.strip()
        # the salvaged attempt was queued first but rotation pushed its files to
        # round-2, while the round recorded in the meantime kept round-1
        salvaged = {**CLEAN, "reviewed_head": start, "shown_sha": shown}
        salvaged |= {"salvaged": True, "round_file": 2}
        live = {**CLEAN, "reviewed_head": shown, "shown_sha": shown, "round_file": 1}
        marker_file(tmp_path).write_text(json.dumps({**state, "rounds": [salvaged, live], **live}))
        r = close(repo, env, "land")
        assert "REVIEWER-SALVAGED" in r.stdout, (r.returncode, r.stdout[-1500:], r.stderr[-1500:])
        assert "round-2.diff" in r.stdout and "round-1.diff" not in r.stdout, (
            "the salvaged round was disclosed under the list index, not its own diff:\n" + r.stdout
        )
