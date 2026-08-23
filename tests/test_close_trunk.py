"""`trunk:` — the branch releases are tagged on, when it is not git's default.

A git-flow consumer (field report, Legacy) integrates on develop with main
hundreds of commits behind. Story close targeted sprint_branch correctly, then
sprint close insisted on tagging default_branch() — a branch containing none of
the sprint — and there was no way to say otherwise.

OUT OF SCOPE, deliberately: the integration→main release cut. `trunk:` names ONE
branch, where sprints land and releases tag. Cutting develop→main stays the
project's own release process; xp neither opens that PR nor tags it. The
predecessor's stage 3 separated the two; this key does not reinstate that.
"""

import subprocess
import sys
from pathlib import Path

from sprint_helpers import CONFIG, make_repo, sprint

SCRIPTS = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"
GITFLOW = CONFIG + "trunk: develop\n"


def resolved(repo, env):
    """What the SHIPPED default_branch() returns here — not a reimplementation."""
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); from close import default_branch;"
            " print(default_branch())",
            str(SCRIPTS),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def test_an_unset_trunk_still_reads_git(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    assert resolved(repo, env).stdout.strip() == "main"


def test_a_configured_trunk_is_what_the_release_targets(tmp_path):
    repo, env, g = make_repo(tmp_path, config=GITFLOW)
    g("branch", "develop", "main")
    r = resolved(repo, env)
    assert r.stdout.strip() == "develop", (r.stdout, r.stderr)


def test_a_configured_trunk_that_does_not_exist_refuses_rather_than_falling_back(tmp_path):
    """sprint_branch's discipline, for the same reason: silently releasing to
    main because the configured branch is missing is what this key prevents."""
    repo, env, _g = make_repo(tmp_path, config=GITFLOW)  # develop never created
    r = resolved(repo, env)
    assert r.returncode != 0, f"fell back instead of refusing: {r.stdout!r}"
    assert "develop" in r.stderr and "main" not in r.stdout


def test_post_merge_tags_the_configured_trunk_and_leaves_git_s_default_alone(tmp_path):
    """The field case end to end: the sprint integrates on develop and the tag
    lands on the merged develop sha, while main keeps none of it."""
    repo, env, g = make_repo(tmp_path, config=GITFLOW)
    g("branch", "develop", "main")
    g("tag", "v0.2.1", "main")
    g("checkout", "-q", "develop")
    g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
    merged = g("rev-parse", "HEAD").stdout.strip()

    r = sprint(repo, env, "post-merge")

    assert r.returncode == 0, r.stderr
    assert g("rev-list", "-n1", "v0.3.0").stdout.strip() == merged
    assert g("rev-parse", "main").stdout.strip() != merged, "the release moved main"
