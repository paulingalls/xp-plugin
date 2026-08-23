"""Every leg's answer to "this clone has no plan", in ONE wording.

Verify: pytest -q tests/test_plan_missing.py

Six legs carried their own copy of the refusal and one had already drifted:
close.py's land arm dropped the half naming what to check, so the leg reached
LAST in a story told the lead least. The property is uniformity, not a spelling
— nothing here pins the words, so a better message stays legal as long as it
reaches every leg.
"""

import re
import subprocess
import sys
from pathlib import Path

from close_helpers import CLOSE, SPAWN, close, make_repo

# The sentence each leg builds around the path. Deliberately loose on the tail:
# what is compared is whether the legs agree, not what they agree on.
MISSING = re.compile(r"no plan at (?P<path>\S+)(?P<tail>.*)")


def run(script, repo, env, *args):
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=repo, env=env, capture_output=True, text=True
    )


def reviewed_repo(tmp_path):
    """A repo with a close in progress, which is what makes all six legs
    reachable: land refuses without the marker and never reaches its plan check,
    and both sprint legs refuse a dirty tree."""
    repo, env, g = make_repo(tmp_path)
    r = close(repo, env, "review")
    assert r.returncode == 0, r.stderr
    return repo, env, g, Path(env["XP_DATA"]) / "plan.md"


def legs(repo, env):
    """Every command that answers the question — one population, so neither
    property below is asserted over a subset of the other's."""
    return {
        "spawn": run(SPAWN, repo, env, "story-042"),
        "spawn ready": run(SPAWN, repo, env, "ready", "story-042"),
        "story review": run(CLOSE, repo, env, "story", "story-042", "review"),
        "story land": close(repo, env, "land"),
        "sprint start": run(CLOSE, repo, env, "sprint", "1", "start"),
        "sprint review": run(CLOSE, repo, env, "sprint", "1", "review"),
    }


def sentence(proc, leg):
    assert proc.returncode != 0, f"{leg} exited {proc.returncode} with no plan:\n{proc.stdout}"
    found = MISSING.search(proc.stderr)
    assert found, f"{leg} does not name the missing plan:\n{proc.stderr}"
    return found.group("tail").strip()


class TestOneMissingPlanRefusal:
    def test_every_leg_says_the_same_thing(self, tmp_path):
        repo, env, _g, plan = reviewed_repo(tmp_path)
        plan.unlink()

        said = {leg: sentence(proc, leg) for leg, proc in legs(repo, env).items()}
        assert len(set(said.values())) == 1, f"the legs disagree about a missing plan: {said}"

    def test_the_pre_move_copy_still_wins_everywhere(self, tmp_path):
        """The migration sentence is the other arm of the same helper: a leg that
        reached the generic diagnosis while a pre-move plan sat beside it would
        send the lead to scaffold a repo that only needs `mv`."""
        repo, env, g, plan = reviewed_repo(tmp_path)
        plan.rename(repo / ".xp" / "plan.md")
        g("add", "-A")
        g("commit", "-qm", "pre-move plan")

        for leg, proc in legs(repo, env).items():
            assert proc.returncode != 0, leg
            assert "per-clone now" in proc.stderr, (
                f"{leg} lost the migration sentence:\n{proc.stderr}"
            )
