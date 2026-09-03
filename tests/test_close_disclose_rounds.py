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
