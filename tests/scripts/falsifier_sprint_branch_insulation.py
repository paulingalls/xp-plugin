"""Falsifier for the checked-in sprint_branch key (supersedes 37187713's INVERTED
one, which grepped for the key and so went green BECAUSE the flaw was present).

The claim stands: .xp/config.yml is tracked, so every clone reads one clone's
sprint branch. What makes that TOLERABLE is the insulation the claim itself
names — nothing reaches the integration branch except close.integration_target(),
which honours the key when the branch exists and REFUSES rather than silently
falling back when it does not. This asserts that, so it is green while the
insulation holds and reds if anything starts reading the key directly or the
refusal turns back into a fallback.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "plugins" / "xp-plugin" / "scripts"))


def main() -> int:
    import close

    tmp = Path(tempfile.mkdtemp())
    (tmp / ".xp").mkdir()
    run = lambda *a: subprocess.run(a, cwd=tmp, capture_output=True)  # noqa: E731
    run("git", "init", "-q", "-b", "main")
    run(
        "git",
        "-c",
        "user.email=l@x",
        "-c",
        "user.name=l",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    )
    run("git", "branch", "sprint-999")
    cfg = tmp / ".xp" / "config.yml"
    import os

    os.chdir(tmp)

    cfg.write_text("release: sprint\ntrunk: main\nsprint_branch: sprint-999\n")
    if (got := close.integration_target()) != "sprint-999":
        print(f"the configured sprint branch was ignored: {got!r}", file=sys.stderr)
        return 1
    cfg.write_text("release: sprint\ntrunk: main\n")
    if (got := close.integration_target()) != "main":
        print(f"no key set, yet the target is not trunk: {got!r}", file=sys.stderr)
        return 1
    # The half that matters most: a key naming a branch that does not exist must
    # REFUSE, never silently merge a fresh clone's work to trunk.
    cfg.write_text("release: sprint\ntrunk: main\nsprint_branch: sprint-nope\n")
    try:
        got = close.integration_target()
    except SystemExit:  # the refusal is a hard stop, not a return value
        return 0
    print(f"a sprint_branch naming no ref returned {got!r} instead of refusing", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
