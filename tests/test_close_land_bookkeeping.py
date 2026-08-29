"""Bookkeeping after the story merge lands."""

import json
import subprocess
import sys

from close_helpers import CLOSE, close, make_repo, mint_ready


class TestLandBookkeeping:
    """story-008 AC 3/7/8: what land does after the merge lands."""

    def with_origin(self, tmp_path, push_story_branch=True):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "-u", "origin", "main")
        if push_story_branch:
            g("push", "-q", "-u", "origin", "story-042-branch")
        return repo, env, g

    def test_land_pushes_trunk_and_deletes_the_story_branch_both_sides(self, tmp_path):
        repo, env, g = self.with_origin(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr + r.stdout
        assert r.stdout.splitlines()[-1] == (
            "story-042 closed. REPLACE the session digest (you are its sole writer);"
            " first line must be: # Session digest — written <ISO-ts> at <short-sha>"
        )
        assert "story-042-branch" not in g("branch", "--list").stdout
        assert "story-042-branch" not in g("ls-remote", "--heads", "origin").stdout
        local_main = g("rev-parse", "main").stdout.strip()
        assert g("rev-parse", "origin/main").stdout.strip() == local_main

    def test_unpushed_story_branch_does_not_produce_a_spurious_failure(self, tmp_path):
        """N2b: a story closed with `spawn --in-place` never pushed its branch —
        this repo's own story-007 did exactly that."""
        repo, env, g = self.with_origin(tmp_path, push_story_branch=False)
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "story-042-branch" not in g("branch", "--list").stdout

    def test_incomplete_bookkeeping_exits_nonzero_not_zero(self, tmp_path):
        """N2a: a warning above 'closed.' is a hand-step the lead will miss."""
        repo, env, _g = self.with_origin(tmp_path)
        close(repo, env, "review")
        subprocess.run(["rm", "-rf", str(tmp_path / "origin.git")], check=True)
        r = close(repo, env, "land")
        assert r.returncode == 3, "push failure must not read as success"
        assert "git push origin main" in r.stderr
        # the merge, flip and amend all landed and merge_sha is on a ref — only a
        # failed AMEND orphans it. Withholding the record here made the close
        # unrecordable by any command, because the card already reads [done].
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        assert rec["story"] == "story-042"
        assert not (tmp_path / "data" / "markers" / "story-042.close.json").exists()

    def test_land_clears_the_stories_test_status_markers(self, tmp_path):
        """AC 3: cleared, never greened — close.py may not forge another
        session's measurement (DESIGN §4)."""
        repo, env, _g = make_repo(tmp_path)
        d = tmp_path / "data" / "markers"
        d.mkdir(parents=True, exist_ok=True)
        stale = d / "sess-old.story-042.test-status"
        stale.write_text(json.dumps({"story": "story-042", "verify": "true", "red": True}))
        keep = d / "sess-old.story-099.test-status"
        keep.write_text(json.dumps({"story": "story-099", "verify": "true", "red": True}))
        close(repo, env, "review")
        assert close(repo, env, "land").returncode == 0
        assert not stale.exists()
        assert keep.exists(), "another story's gate state is not this close's business"

    def test_close_record_is_appended_and_names_the_real_merge_commit(self, tmp_path):
        """AC 8 + G6. The sha was read before the --amend and so was on no ref;
        with the amend gone it is the merge commit, and the claim it must name the
        REAL merge is what outlived the mechanism."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        assert close(repo, env, "land").returncode == 0
        lines = (tmp_path / "data" / "closes.jsonl").read_text().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["story"] == "story-042" and rec["title"] == "demo story"
        assert rec["rounds"] == [{"fixed": [], "blocking": [], "noted": []}]
        assert rec["merge_sha"] == g("rev-parse", "main").stdout.strip()
        assert g("cat-file", "-t", rec["merge_sha"]).stdout.strip() == "commit"

    def test_a_second_close_appends_rather_than_overwriting(self, tmp_path):
        """N7: overwriting would be the project-global mutable marker
        constraints #10 forbids, and would lose the sprint's history."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        close(repo, env, "land")
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text() + "#### story-043 — second   [in-progress]\nVerify: true\n"
        )
        mint_ready(repo, env, "story-043")
        g("checkout", "-qb", "story-043-branch")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "second story work")
        for action in ("review", "land"):
            subprocess.run(
                [sys.executable, str(CLOSE), "story", "story-043", action, "--merge-mode", "local"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
        records = (tmp_path / "data" / "closes.jsonl").read_text().splitlines()
        assert [json.loads(r)["story"] for r in records] == ["story-042", "story-043"]
