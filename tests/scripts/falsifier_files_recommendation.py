"""Falsifier for the Files-as-contract bug (record 1f255131): reds if the code
ever starts treating a card's `Files:` line as a permission list.

The bug's cost was prose — the plan-reviewer charter called a bare files-list
omission a broken-gate catch, and EXECUTOR.md makes the card the whole scope, so
an implementation-known file outside Files became "card is wrong -> stop": five
plan-gate exits and ~500k teammate tokens at story-028. NO SCRIPT CAN HOLD THAT
HALF. Prose is judged by a reader, and a check that greps the charter for its
current wording greens the moment the same rule returns in different words —
constraint 11's exact prohibition, and constraint 2's vacuous guard.

What a script CAN hold is the half the decision made load-bearing: Files binds
nothing in code EXCEPT the `.xp/` explicit grant. Both arms are CONSTRUCTED
against the shipped gate — a reviewer PATCH that touches an undeclared ordinary
file is permitted, one that touches an undeclared `.xp/` file refuses — so the
day someone widens the gate to all of Files, or drops the `.xp/` exception,
this reds and the record reopens. The prose half is held where prose is held:
the charters, re-read at every review.

THE SITE MOVED AT STORY-034 and this followed it. It used to drive
check_reviewer_motion over a reviewer COMMIT; reviewers no longer commit at all,
so that arm began reding on the new design rather than on the property, and
blocked sprint-006's close. The grant now lives in review.apply_patch, which
scopes the STAGED tree. A falsifier that outlives the site it names is the
failure this batch hit three times in one close (see 7fed6ef1, f009389a).
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "plugins" / "xp-plugin" / "scripts"))
import review

CARD = "#### story-001 — demo   [ready]\nFiles: src/thing.py, .xp/config.yml\nVerify: true\n"


def apply_patch_over(tmp: Path, path: str) -> str:
    """A repo where the reviewer's PATCH touches `path`.
    Returns review.apply_patch's verdict: "" is permitted."""
    repo = tmp / path.replace("/", "_")
    (repo / ".xp").mkdir(parents=True)
    (repo / "src").mkdir()
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, check=True, capture_output=True
    )
    run("init", "-q", "-b", "main")
    run("config", "user.email", "lead@xp.local")
    run("config", "user.name", "the lead")
    (repo / "src" / "thing.py").write_text("A = 1\n")
    (repo / ".xp" / "config.yml").write_text("tests:\n  story: true\n")
    run("add", "-A")
    run("commit", "-qm", "base")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    del head  # the patch path is judged on the STAGED tree, not on a range
    # Built by STAGING and diffing --cached, never `diff --no-index`: the latter
    # emits absolute a/ and b/ paths, and rewriting them by hand produces
    # `a.xp/system.md` — a patch git cannot read, so apply_patch returns early and
    # BOTH arms read as permitted. A falsifier that cannot construct its own
    # condition asserts nothing (constraint 11).
    target = repo / path
    target.write_text("# the reviewer's fix\n")
    run("add", "-A")
    diff = subprocess.run(
        ["git", "diff", "--cached", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout
    run("reset", "-q", "HEAD")
    target.unlink()  # apply_patch applies it; the tree must not already carry it
    report = repo / "round-1.json"
    review.patch_path(report).write_text(diff)
    cwd = Path.cwd()
    try:
        os.chdir(repo)
        return review.apply_patch(report, CARD)
    finally:
        os.chdir(cwd)


def main(tmp: Path) -> int:
    undeclared_ordinary = apply_patch_over(tmp, "src/other.py")
    if undeclared_ordinary:
        print(
            "an undeclared ORDINARY file was refused — Files is a permission list"
            f" again:\n{undeclared_ordinary}",
            file=sys.stderr,
        )
        return 1
    undeclared_xp = apply_patch_over(tmp, ".xp/system.md")
    if not undeclared_xp:
        print(
            "an undeclared .xp/ file was permitted — the explicit grant that stayed"
            " an exception is gone",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        sys.exit(main(Path(tmp)))
