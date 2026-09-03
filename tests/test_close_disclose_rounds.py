"""Release blocker a257aa2f: land's disclose showed only the LAST round's reviewer
range, because write_round keeps reviewed_head/shown_sha at top level and round 2
overwrites round 1's. The lead then assents at land to a merge that hides what the
first reviewer changed. Constructs two rounds with real commits and asserts BOTH
reviewer ranges reach stdout."""

import json
import subprocess
import sys

sys.path.insert(0, "plugins/xp-plugin/scripts")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def test_disclose_shows_every_rounds_reviewer_work(tmp_path, capsys, monkeypatch):
    import review

    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    shas = []
    for n in range(5):
        (repo / f"f{n}").write_text("x")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", f"c{n} ROUND1WORK" if n in (1, 2) else f"c{n} ROUND2WORK")
        shas.append(git(repo, "rev-parse", "HEAD").stdout.strip())

    # monkeypatch.chdir, never os.chdir: reviewer_range shells out to git in cwd, and
    # a bare chdir leaks to every later test on this xdist worker. It did — the first
    # version of this file poisoned test_release's config read, which resolves from cwd.
    monkeypatch.chdir(repo)
    state = {
        "rounds": [
            {"reviewed_head": shas[0], "shown_sha": shas[2]},
            {"reviewed_head": shas[2], "shown_sha": shas[4]},
        ],
        "reviewed_head": shas[2],
        "shown_sha": shas[4],
    }
    review.disclose(state, shas[4])
    out = capsys.readouterr().out
    assert "ROUND2WORK" in out, "the last round's reviewer work is missing entirely"
    assert "ROUND1WORK" in out, (
        "round 1's reviewer commits are hidden at the moment of assent:\n" + out
    )


def test_a_legacy_round_is_migrated_before_new_coverage_overwrites_it(tmp_path):
    import review

    marker = tmp_path / "marker.json"
    legacy = {"fixed": [], "blocking": [], "noted": []}
    state = {"rounds": [legacy], "reviewed_head": "round-1-start", "shown_sha": "round-1-end"}
    review.write_round(
        marker,
        state,
        {"fixed": [], "blocking": [], "noted": []},
        reviewed_head="round-2-start",
        shown_sha="round-2-end",
    )
    written = json.loads(marker.read_text())
    assert review.covered_ranges(written, "head") == [
        ("round-1-start", "round-1-end"),
        ("round-2-start", "round-2-end"),
    ]


def test_a_round_that_recorded_no_coverage_still_holds_its_ROUND_NUMBER(tmp_path):
    """The sprint-17 blocking finding, one round further on: land was fixed to name
    each round's own diff, but covered_ranges DROPS an uncovered round instead of
    holding its place, so every later round shifts down one and is disclosed under an
    earlier round's diff. `sprint_close.stop` and `cmd_salvage` both write exactly such
    a round — a review killed mid-flight — so this needs no legacy state to reach."""
    import review

    killed = {"fixed": [], "blocking": [], "noted": [], "incomplete": "host killed it"}
    done = {"reviewed_head": "r2-start", "shown_sha": "r2-end"}
    state = {"rounds": [killed, done], "reviewed_head": "r2-start", "shown_sha": "r2-end"}
    assert review.covered_ranges(state, "head") == [("head", "head"), ("r2-start", "r2-end")]

    # pre-0.18 state: no round kept coverage and only the LAST one's survives at top
    # level, so it must land at index 2 — never at index 0 under round 1's diff name
    legacy = {"rounds": [{}, {}, {}], "reviewed_head": "r3-start", "shown_sha": "r3-end"}
    assert review.covered_ranges(legacy, "head") == [
        ("head", "head"),
        ("head", "head"),
        ("r3-start", "r3-end"),
    ]
