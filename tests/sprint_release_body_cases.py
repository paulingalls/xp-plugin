"""Sprint land and post-merge. Split from test_sprint_close.py at sprint-004 open."""

import json
import subprocess
import sys

from close_helpers import launches, stub_reviewer  # noqa: F401
from sprint_helpers import (  # noqa: F401
    CLOSE,
    CONFIG,
    PLAN,
    PLUGIN,
    WORK,
    WORK_SECTION,
    committing_stub,
    head,
    make_repo,
    marker_path,
    record_reviews,
    section,
    snapshot,
    sprint,
    work,
)

sys.path.insert(0, str(PLUGIN / "scripts" / "close"))
from sprint_land import _release_body


def release_tools(tmp_path, env, g):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
    assert g("remote", "add", "origin", str(origin)).returncode == 0
    assert g("push", "-q", "origin", "main").returncode == 0
    record = tmp_path / "gh.json"
    gh = tmp_path / "bin" / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args = sys.argv[1:]\nassert '--body' not in args\n"
        "path = args[args.index('--body-file') + 1]\n"
        "data = {'argv': args, 'body': open(path).read()}\n"
        f"open({str(record)!r}, 'w').write(json.dumps(data))\n"
    )
    gh.chmod(0o755)
    return record


def write_closes(tmp_path, records):
    path = tmp_path / "data" / "closes.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def record_release(tmp_path, state):
    marker = marker_path(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(state))
    write_closes(tmp_path, [{"story": "story-042", "title": "done", "merge_sha": "2" * 40}])


def release_state(repo, env, **round_changes):
    covered = head(repo, env)
    coverage = {"reviewed_head": covered, "shown_sha": covered}
    round_ = {
        "fixed": [],
        "blocking": [],
        "schema": 2,
        "dropped": [],
        "debt": [],
        **coverage,
        **round_changes,
    }
    receipt = {"tier": "full", "command": "true", "tree": "recorded-tree", "head": "recorded-head"}
    receipt.update(verdict="passed", ran_by="land", reused=False)
    return dict(rounds=[round_], reviewed_head=covered, shown_sha=covered, full_tier=receipt)


def release_round(repo, env, **changes):
    return release_state(repo, env, **changes)["rounds"][0]


class TestReleasePrBody:
    def test_the_release_pr_carries_only_this_sprints_record(self, tmp_path):
        events = tmp_path / "tier-events"
        command = f"printf x >> {events}"
        repo, env, g = make_repo(tmp_path, config=CONFIG.replace("full: true", f"full: {command}"))
        assert sprint(repo, env, "start").returncode == 0
        marker = marker_path(tmp_path)
        state = {}
        covered = head(repo, env)
        bound = ["RUN-FULL-BEFORE-RELEASE"]
        second = dict(blocking=bound, clearable_by_full=bound, fixed=["second fix", "third fix"])
        rounds = [
            release_round(
                repo,
                env,
                fixed=["first fix"],
                dropped=[
                    {"finding": x, "reason": "fixture reason"}
                    for x in ["first note", "second note"]
                ],
            ),
            release_round(repo, env, **second),
        ]
        state.update(rounds=rounds, reviewed_head=covered, shown_sha=covered)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(state))
        closed = [("story-043", "also done", "4"), ("story-042", "done thing", "2")]
        closed += [("story-099", "not this sprint", "9")]
        write_closes(tmp_path, [dict(story=s, title=t, merge_sha=d * 40) for s, t, d in closed])
        gh_record = release_tools(tmp_path, env, g)

        result = sprint(repo, env, "land")

        assert result.returncode == 0, result.stdout + result.stderr
        receipt = json.loads(marker.read_text())["full_tier"]
        assert events.read_text() == "x" and not (tmp_path / "launches.jsonl").exists()
        call = json.loads(gh_record.read_text())
        assert "--body-file" in call["argv"] and "--body" not in call["argv"]
        body = call["body"]
        first, second = body.index("story-042"), body.index("story-043")
        assert first < second and "2" * 40 in body and "4" * 40 in body
        assert "story-099" not in body and "9" * 40 not in body and "not this sprint" not in body
        assert "Review round 1: 1 fixed · 0 blocking · 2 dropped · 0 debt" in body
        assert "Review round 2: 2 fixed · 1 blocking · 0 dropped · 0 debt" in body
        for value in (
            covered,
            "RUN-FULL-BEFORE-RELEASE",
            "Tier: full",
            "Verdict: passed",
            command,
            f"Measured tree: {receipt['tree']}",
            "ran by land",
        ):
            assert value in body

    def test_a_land_run_is_not_described_as_reused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        record_release(tmp_path, release_state(repo, env))
        gh_record = release_tools(tmp_path, env, g)
        result = sprint(repo, env, "land")
        body = json.loads(gh_record.read_text())["body"]
        assert result.returncode == 0 and "ran by land" in body and "reused from" not in body

    def test_no_recorded_round_still_refuses_before_tier_or_gh(self, tmp_path):
        touched = tmp_path / "tier-ran"
        repo, env, _g = make_repo(
            tmp_path, config=CONFIG.replace("full: true", f"full: touch {touched}")
        )
        marker = marker_path(tmp_path)
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"rounds": [], "full_tier": {}}))
        before = marker.read_bytes()
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "no recorded review for sprint 2" in result.stderr
        assert not touched.exists() and not (tmp_path / "gh.json").exists()
        assert marker.read_bytes() == before

    def test_huge_findings_are_counted_without_becoming_the_body(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        sentinel = "FINDING-PROSE-" * 1000
        record_release(
            tmp_path,
            release_state(
                repo,
                env,
                fixed=[sentinel],
                dropped=[{"finding": sentinel, "reason": "fixture reason"}],
            ),
        )
        gh_record = release_tools(tmp_path, env, g)
        assert sprint(repo, env, "land").returncode == 0
        body = json.loads(gh_record.read_text())["body"]
        assert "1 fixed · 0 blocking · 1 dropped · 0 debt" in body
        assert sentinel not in body and len(body) < 65_536

    def test_an_overlong_body_refuses_before_push_or_gh(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        huge = "BOUND-" * 11000
        state = release_state(repo, env, blocking=[huge], clearable_by_full=[huge])
        record_release(tmp_path, state)
        gh_record = release_tools(tmp_path, env, g)
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "65536" in result.stderr
        assert "clearable_by_full" in result.stderr, "it names prose the body never quotes"
        assert "missing" not in result.stderr and "unreadable" not in result.stderr
        assert (
            not gh_record.exists()
            and g("ls-remote", "--heads", "origin", "sprint-002").stdout == ""
        )

    def test_release_inputs_name_the_unreadable_part(self, tmp_path, monkeypatch):
        repo, env, _g = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("XP_DATA", env["XP_DATA"])
        state = release_state(repo, env)
        record_release(tmp_path, state)
        close_log = tmp_path / "data" / "closes.jsonl"
        close_log.unlink()
        assert "no close log" in _release_body("2", state, marker_path(tmp_path))[1]
        close_log.write_text("{broken\n")
        assert "unreadable close log" in _release_body("2", state, marker_path(tmp_path))[1]
        record_release(tmp_path, state)
        state.pop("reviewed_head")
        state["rounds"][-1].pop("reviewed_head")
        assert "reviewed_head" in _release_body("2", state, marker_path(tmp_path))[1]
        state = release_state(repo, env)
        state["full_tier"] = None
        assert "full_tier" in _release_body("2", state, marker_path(tmp_path))[1]
        state = release_state(repo, env)
        write_closes(tmp_path, [{"story": "story-099", "title": "OTHER", "merge_sha": None}])
        body, error = _release_body("2", state, marker_path(tmp_path))
        assert not error and body.count("no close record") == 2 and "OTHER" not in body
        write_closes(tmp_path, [{"story": "story-042", "title": "T", "merge_sha": None}])
        assert "line 1: story record" in _release_body("2", state, marker_path(tmp_path))[1]
        (tmp_path / "data" / "plan.md").write_text(PLAN.replace("### Sprint 2", "### Sprint 8"))
        assert "no `### Sprint 2` section" in _release_body("2", state, marker_path(tmp_path))[1]
