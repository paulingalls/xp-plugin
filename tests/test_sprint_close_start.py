"""Sprint-start output and mutation bounds, extracted for constraint 8."""

import subprocess
from pathlib import Path

from sprint_helpers import make_repo, snapshot, sprint, work


class TestStartIsReadOnly:
    def test_start_mutates_nothing_but_appends_to_work_md(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "note", "a note to consume")
        root = tmp_path / "data"
        before = snapshot(root)
        before_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
        ).stdout
        assert sprint(repo, env, "start").returncode == 0
        after = snapshot(root)
        for name, blob in before.items():
            if name == Path("work.md"):
                assert after[name].startswith(blob), "work.md was rewritten, not appended to"
            else:
                assert after[name] == blob, f"{name} changed during a read-and-emit leg"
        assert (
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
            ).stdout
            == before_head
        )

    def test_start_is_idempotent(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        first = sprint(repo, env, "start")
        second = sprint(repo, env, "start")
        assert first.returncode == second.returncode == 0
        assert first.stdout == second.stdout

    def test_start_emits_the_retro_skeleton_and_the_digest_PROMPT(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "note", "SENTINEL-NOTE-FOR-TRIAGE")
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        assert "SENTINEL-NOTE-FOR-TRIAGE" in r.stdout
        assert "Retro" in r.stdout
        assert "digest" in r.stdout.lower()

    def test_a_teammate_stamped_note_is_triaged_by_its_CLAIM_not_its_stamp(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        claim = "THE-CLAIM-A-HUMAN-TRIAGES"
        work(repo, env | {"XP_STORY_ID": "story-042"}, "note", claim)
        r = sprint(repo, env, "start")
        assert r.returncode == 0, r.stderr
        listed = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("note ")]
        assert listed, r.stdout
        assert claim in listed[0], f"the stamp displaced the claim: {listed[0]!r}"
        assert "Story: story-042" not in listed[0], listed[0]
