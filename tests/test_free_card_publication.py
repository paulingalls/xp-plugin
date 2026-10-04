"""A free release publishes and completes only its validated card."""

import re
import sys
from pathlib import Path

import pytest
from card_adjustment_support import command
from close_helpers import SPAWN, free, marker_file
from test_close_free_post_merge import TestFreePostMerge as FreeFixture


@pytest.mark.parametrize(
    "versioned,when", [(True, "verify"), (False, "verify"), (True, "completion")]
)
def test_verify_card_edit_cannot_publish_previous_green(tmp_path, versioned, when):
    fixture = FreeFixture()
    repo, env, g, branch = fixture.reviewed(
        tmp_path, extra="" if versioned else "versioning: off\n"
    )
    fixture.merge_pr(g, branch)
    key = branch.split("/", 1)[1]
    candidate = tmp_path / "candidate.md"
    gate = tmp_path / "gate.py"

    def snapshot():
        result = command(repo, env, "work.py", "card-snapshot", key, str(candidate))
        assert result.returncode == 0, result.stderr
        return re.search(r"^digest: (\w+)$", result.stdout, re.M).group(1)

    digest = snapshot()
    verify = f"{sys.executable} {gate}" if when == "verify" else "true"
    candidate.write_text(candidate.read_text().replace("Verify: true", f"Verify: {verify}"))
    args = [
        "edit-card",
        key,
        "--context",
        "card-edit",
        "--digest",
        digest,
        "--status",
        "in-progress",
        str(candidate),
    ]
    edited = command(repo, env, "work.py", *args)
    assert edited.returncode == 0, edited.stderr
    candidate = tmp_path / "replacement.md"
    args[-1] = str(candidate)
    args[args.index("--digest") + 1] = snapshot()
    candidate.write_text(candidate.read_text().replace(f"Verify: {verify}", "Verify: false"))
    argv = [sys.executable, str(SPAWN.parent / "work.py"), *args]
    gate.write_text(f"import subprocess\nsubprocess.run({argv!r}, check=True)\n")
    if when == "completion":
        wrapper = tmp_path / "bin/git"
        wrapper.write_text(
            '#!/bin/sh\n/usr/bin/git "$@"\nresult=$?\n'
            'if [ "$1" = worktree ] && [ "$2" = list ]; then\n'
            f' "{sys.executable}" "{gate}" >&2 || exit $?\n'
            "fi\nexit $result\n"
        )
        wrapper.chmod(0o755)
    marker = marker_file(tmp_path, key)
    original = marker.read_bytes()

    result = free(repo, env, "fix-typo", "post-merge")

    assert result.returncode == 2, result.stdout + result.stderr
    assert "card changed" in result.stderr
    assert ("v0.2.1" in g("tag").stdout.split()) == (when == "completion")
    current = (Path(env["XP_DATA"]) / "plan.md").read_text()
    assert "Verify: false" in current and "[in-progress]" in current
    assert marker.read_bytes() == original
    assert branch in g("branch", "--list").stdout


def test_publication_holds_existing_plan_lock(tmp_path):
    fixture = FreeFixture()
    repo, env, g, branch = fixture.reviewed(tmp_path)
    fixture.merge_pr(g, branch)
    probe = tmp_path / "lock_probe.py"
    sentinel = tmp_path / "locked"
    probe.write_text(
        "import fcntl, os\nfrom pathlib import Path\n"
        "with (Path(os.environ['XP_DATA'])/'locks/plan.lock').open('a+') as handle:\n"
        " try:\n  fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        " except BlockingIOError:\n"
        f"  Path({str(sentinel)!r}).touch()\n"
        " else:\n  raise SystemExit(7)\n"
    )
    wrapper = tmp_path / "bin/git"
    wrapper.write_text(
        '#!/bin/sh\nif [ "$1" = tag ] && [ "$2" = v0.2.1 ]; then\n'
        f' "{sys.executable}" "{probe}" || exit $?\n'
        'fi\nexec /usr/bin/git "$@"\n'
    )
    wrapper.chmod(0o755)

    result = free(repo, env, "fix-typo", "post-merge")

    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.exists()
    assert "v0.2.1" in g("tag").stdout.split()


@pytest.mark.meta
@pytest.mark.parametrize("boundary", ["card", "lock", "completion"])
def test_publication_card_boundary_faults(tmp_path, monkeypatch, boundary):
    import shutil

    import close_helpers

    def guarantee(root):
        root.mkdir()
        if boundary == "lock":
            test_publication_holds_existing_plan_lock(root)
        else:
            test_verify_card_edit_cannot_publish_previous_green(
                root, True, "completion" if boundary == "completion" else "verify"
            )

    guarantee(tmp_path / "control")
    installed = tmp_path / "installed"
    shutil.copytree(close_helpers.PLUGIN, installed)
    path = installed / "scripts/close/free.py"
    old, new = {
        "card": ("if story_card(text, key)[0] != card:", "if False:"),
        "lock": ("current_card_action(publish)", "publish()"),
        "completion": (
            'if error := current_card_action(lambda: "", complete=True):',
            'if error := "":',
        ),
    }[boundary]
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))
    monkeypatch.setattr(close_helpers, "CLOSE", installed / "scripts/close.py")
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "fault")
