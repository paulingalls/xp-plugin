import json
import subprocess

import close
import pytest
import story_stages


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


@pytest.fixture
def dirty_review_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "review@example.com")
    git(repo, "config", "user.name", "Review Fixture")
    tracked = repo / "tracked.txt"
    tracked.write_text("base\n")
    git(repo, "add", "tracked.txt")
    git(repo, "commit", "-qm", "base")
    tracked.write_text("human stash\n")
    git(repo, "stash", "push", "-q", "-m", "human")
    human = git(repo, "rev-parse", "stash@{0}").stdout.strip()
    tracked.write_text("review dirt\n")
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    return repo, tracked, human


def stash_shas(repo):
    return set(git(repo, "stash", "list", "--format=%H").stdout.splitlines())


def run_review(repo, tracked, monkeypatch, during_review):
    captured = {}

    def reviewed(story_id):
        captured["sha"] = git(repo, "rev-parse", "stash@{0}").stdout.strip()
        during_review(tracked, captured["sha"])
        close.marker_path(story_id).write_text(
            json.dumps({"fixed": [], "blocking": [], "noted": []})
        )
        return 0

    monkeypatch.setattr(close, "cmd_review", reviewed)
    return story_stages.review_story(repo, "story-042"), captured["sha"]


class TestDirtyReviewStash:
    def test_a_successful_restore_drops_only_the_review_stash(self, dirty_review_repo, monkeypatch):
        repo, tracked, human = dirty_review_repo
        result, review = run_review(repo, tracked, monkeypatch, lambda *_: None)

        assert result == (0, {"fixed": [], "blocking": [], "noted": []}, "")
        assert tracked.read_text() == "review dirt\n"
        assert stash_shas(repo) == {human}
        assert review not in stash_shas(repo)

    def test_identical_regeneration_keeps_the_review_result_and_drops_its_stash(
        self, dirty_review_repo, monkeypatch
    ):
        repo, tracked, human = dirty_review_repo

        def regenerate(path, review):
            path.write_text("review dirt\n")
            refused = subprocess.run(
                ["git", "stash", "apply", "-q", review], cwd=repo, capture_output=True
            )
            assert refused.returncode != 0

        result, review = run_review(repo, tracked, monkeypatch, regenerate)

        assert result == (0, {"fixed": [], "blocking": [], "noted": []}, "")
        assert tracked.read_text() == "review dirt\n"
        assert stash_shas(repo) == {human}
        assert review not in stash_shas(repo)

    def test_a_real_restore_conflict_preserves_and_names_the_stash(
        self, dirty_review_repo, monkeypatch
    ):
        repo, tracked, human = dirty_review_repo
        result, review = run_review(
            repo, tracked, monkeypatch, lambda path, _review: path.write_text("other output\n")
        )

        rc, state, refusal = result
        assert rc == 2 and state == {}
        assert "restore" in refusal and "review refusal" in refusal
        assert "refs/stash" in refusal and review in refusal
        assert stash_shas(repo) == {human, review}
        assert tracked.read_text() == "other output\n"
