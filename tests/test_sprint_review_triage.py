"""Sprint-close note triage emission."""

import subprocess
import sys

from sprint_helpers import PLUGIN, make_repo, sprint


class TestTriageEmissionShrinks:
    """cmd_start listed every `## note ` block ever filed — no window, no filter —
    so a note re-emitted at every close forever. 75 at sprint-003, 53 predating
    the sprint. The verb is inert without this: archiving 75 records changes
    nothing a human sees until start stops naming them."""

    def test_an_archived_note_leaves_the_triage_emission(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        work = lambda *a: subprocess.run(  # noqa: E731
            [sys.executable, str(PLUGIN / "scripts" / "work.py"), *a],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        work("note", "KEEP-ME-SENTINEL")
        work("note", "ARCHIVE-ME-SENTINEL")
        ref = work("list").stdout.strip().splitlines()[-1].split()[0]
        before = sprint(repo, env, "start").stdout
        assert "ARCHIVE-ME-SENTINEL" in before and "KEEP-ME-SENTINEL" in before
        assert work("archive", "--ref", ref, "--disposition", "dropped").returncode == 0
        after = sprint(repo, env, "start").stdout
        assert "ARCHIVE-ME-SENTINEL" not in after, "archived note still queued for triage"
        assert "KEEP-ME-SENTINEL" in after, "filtered an unarchived note too"
