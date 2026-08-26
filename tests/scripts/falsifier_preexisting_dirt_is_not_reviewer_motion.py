#!/usr/bin/env python3
"""A file the lead left before the review must not cost the round.

check_reviewer_motion refuses on ANY `git status --porcelain` output at the end of
a review, and its own docstring concedes it cannot say who left the files. So a
reviewer that behaved perfectly — restored the tree, wrote its report and patch —
has its entire round discarded because the lead created an unrelated file while it
ran. Report and patch are on disk; the marker never records them.
Same root as fa23e06f/story-054: the pipeline holds a finished artifact and
destroys it for a reason unrelated to that artifact's validity.
CONSTRUCTED: a real repo, an untracked file present BEFORE the guard runs, a HEAD
that never moved and a marker that never changed — i.e. a reviewer that did
nothing wrong. Never greps the refusal text.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins" / "xp-plugin" / "scripts"))
import review  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp) / "repo"
    repo.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": tmp}

    def run(*a):
        return subprocess.run(["git", *a], cwd=repo, env=env, capture_output=True, text=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (repo / "src.py").write_text("A = 1\n")
    run("add", "-A")
    run("commit", "-qm", "base")
    head = run("rev-parse", "HEAD").stdout.strip()

    marker = Path(tmp) / "marker.json"
    marker.write_text('{"rounds": []}')
    digest = review.marker_digest(marker)

    # The lead's own file, created BEFORE the guard runs. The reviewer never saw it.
    (repo / "falsifier_i_just_wrote.py").write_text("# mine, not the reviewer's\n")

    import os

    os.chdir(repo)
    refusal = review.check_reviewer_motion(head, marker, digest)

print("HEAD unmoved, marker unchanged, reviewer touched nothing.")
print(f"guard refused: {bool(refusal)}")
if refusal:
    print(f"  {refusal.strip().splitlines()[0][:110]}")
    print("  ^ the round is discarded; the report and patch stay on disk unrecorded")
sys.exit(1 if refusal else 0)
