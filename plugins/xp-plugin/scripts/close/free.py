"""Free mode: a card-less branch off the default branch, and the patch release
it becomes (DESIGN §6). Without it a between-sprint fix either waits for a
sprint or moves main by hand.

Every land guard here is the story leg's own, reached through overlap.py — the
rule fixed in one of two land legs is this repo's most-filed defect class.
"""

import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import overlap
from bookkeep import render_merge_body, render_noted
from close import default_branch, fail, git, marker_path
from review import diff_path, disclose, report_path
from sprint_close import next_version, refuse_unbumpable
from work import slugify, user_ns

FREE = re.compile(r"[^/]+/free-(\d{4}-\d\d-\d\d-(.+))")


def branch_for(slug: str) -> str:
    return f"{user_ns()}/free-{datetime.date.today().isoformat()}-{slugify(slug)}"


def current_free(slug: str) -> tuple[str, str, str]:
    """(marker key, branch, refusal), read off HEAD rather than recomputed from
    today's date — a branch cut yesterday still lands today."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    m = FREE.fullmatch(branch)
    if not m or m.group(2) != slugify(slug):
        return (
            "",
            branch,
            (
                f"refused: on {branch}, which is not a free branch for {slug!r} — run this"
                f" from the branch `free start` cut, e.g. {branch_for(slug)}"
            ),
        )
    return f"free/{m.group(1)}", branch, ""


def cmd_start(slug: str) -> int:
    if git("status", "--porcelain").stdout.strip():
        return fail("refused: working tree is dirty — commit or stash first")
    trunk = default_branch()
    if (branch := git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()) != trunk:
        return fail(
            f"refused: free start cuts off {trunk}, and you are on {branch} — a free"
            f" branch cut anywhere else carries that branch's unreleased work into a"
            f" patch release. `git checkout {trunk}` first"
        )
    new = branch_for(slug)
    if git("rev-parse", "--verify", "-q", f"refs/heads/{new}", check=False).returncode == 0:
        return fail(f"refused: branch {new} already exists")
    if (made := git("checkout", "-q", "-b", new, trunk, check=False)).returncode:
        return fail(f"git checkout -b failed: {made.stderr.strip()}")
    print(f"{new} off {trunk} — no card. Commit, then `close.py free {slug} review`")
    return 0


def cmd_review(slug: str, dry_run: bool) -> int:
    import close

    key, _branch, err = current_free(slug)
    return fail(err) if err else close.cmd_review(key, dry_run, free=True)


def cmd_land(slug: str, dry_run: bool) -> int:
    key, branch, err = current_free(slug)
    if err:
        return fail(err)
    if git("status", "--porcelain").stdout.strip():
        return fail("refused: working tree is dirty — the tier must judge the tree that ships")
    marker = marker_path(key)
    if not marker.exists():
        return fail(f"refused: no review recorded for {branch} — run `close.py free {slug} review`")
    state = json.loads(marker.read_text())
    trunk = default_branch()
    base = git("merge-base", f"refs/heads/{trunk}", "HEAD").stdout.strip()
    if err := overlap.land_refusal(state, f"free {slug}", base):
        return fail(err)
    ref = overlap.merge_source(trunk, "pr")
    if files := overlap.overlapping(ref, base):
        return fail(overlap.collision(ref, files))
    # off REF, not HEAD: a sprint that released while this branch was open left its
    # tag unreachable from here, and the bump would name a version already shipped
    if not (version := next_version("patch", ref)):
        return refuse_unbumpable(ref)
    rounds = state["rounds"]
    title, body = f"free {slug} — {version}", render_merge_body(rounds)
    cmds = [
        ["git", "push", "-u", "origin", branch],
        ["gh", "pr", "create", "--base", trunk, "--title", title, "--body", body],
    ]
    if dry_run:
        for c in cmds:
            print(" ".join(c))
        print(f"(first the full tier; then `git tag {version}` on {trunk} once the PR merges)")
        return 0
    # the FULL tier, not the story one: a close targeting main is a release
    if red := overlap.gates(ref, "", "full", overlap.unmerged(ref)):
        return fail(red)
    head = git("rev-parse", "HEAD").stdout.strip()
    disclose(state, head, diff_path(report_path(key, len(rounds))))
    if not shutil.which("gh"):
        return fail("refused: free land opens a PR — install the gh CLI, or open it by hand")
    for c in cmds:
        if (r := subprocess.run(c, capture_output=True, text=True)).returncode != 0:
            return fail(f"{c[0]} failed: {r.stderr.strip()}")
    print(render_noted(rounds), end="")
    print(f"PR open against {trunk}. After it merges: `git tag {version}` there, and push the tag")
    return 0


def cmd(slug: str, action: str, dry_run: bool) -> int:
    if action == "start":
        return cmd_start(slug)
    if action == "review":
        return cmd_review(slug, dry_run)
    return cmd_land(slug, dry_run)
