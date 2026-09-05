"""The card refresh gate the mint reads: what stales a receipt, what does not,
and how a receipt that is not one refuses."""

import json
import subprocess

import pytest
from spawn_helpers import SPAWN, make_repo, seed_refresh_receipt, spawn


class TestReadyCredential:
    def test_ready_refuses_an_unknown_story_without_writing_a_marker(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="planned")
        r = spawn(repo, env, "ready", "story-999")
        assert r.returncode == 2 and "story-999" in r.stderr
        assert not (tmp_path / "data" / "markers").exists()


class TestCardRefreshGate:
    """story-103. Constraint 13's freshness check ran when the card was OLDEST
    relative to the tree, so the refresh moved to just before the mint — and a
    step mandated in prose and enforced by nothing is a step that gets skipped."""

    RECEIPT = ("data", "card-refreshes", "story-042.json")

    def receipt(self, tmp_path):
        return tmp_path.joinpath(*self.RECEIPT)

    def replan(self, tmp_path):
        """Back to [planned] so a second mint reaches the gate rather than the
        status refusal above it."""
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("[ready]", "[planned]"))

    def commit(self, repo, env, path, body):
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(body)
        for args in (("add", "-A"), ("commit", "-qm", f"touch {path}")):
            done = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True)
            assert done.returncode == 0, done.stderr

    def test_a_commit_to_a_declared_file_stales_the_receipt_and_an_unrelated_one_does_not(
        self, tmp_path
    ):
        """AC3 and its inverse. A gate that refuses after ANY commit is as useless
        as one that never refuses: the card's claim is about the files it names."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        self.commit(repo, env, "src/thing.py", "# 1\n")
        seed_refresh_receipt(repo, env)
        assert json.loads(self.receipt(tmp_path).read_text())["files"]["src/thing.py"]
        assert spawn(repo, env, "ready", "story-042").returncode == 0

        self.replan(tmp_path)
        self.commit(repo, env, "src/thing.py", "# 2 — the premise moved\n")
        r = spawn(repo, env, "ready", "story-042")
        assert r.returncode == 2, r.stdout
        assert "src/thing.py changed since story-042's card refresh" in r.stderr, r.stderr
        assert "--refresh" in r.stderr

        seed_refresh_receipt(repo, env)
        self.commit(repo, env, "unrelated.md", "nothing the card names\n")
        again = spawn(repo, env, "ready", "story-042")
        assert again.returncode == 0, again.stderr

    def test_a_path_the_card_will_create_is_recorded_absent_not_stale(self, tmp_path):
        """AC4, both readings refused: `null` is not "infinitely stale" — the mint
        goes through — and not "silently exempt" either, because HEAD acquiring
        the path is exactly the change the receipt then no longer describes."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        seed_refresh_receipt(repo, env)
        assert json.loads(self.receipt(tmp_path).read_text())["files"] == {"src/thing.py": None}
        assert spawn(repo, env, "ready", "story-042").returncode == 0

        self.replan(tmp_path)
        self.commit(repo, env, "src/thing.py", "# it exists now\n")
        r = spawn(repo, env, "ready", "story-042")
        assert r.returncode == 2 and "src/thing.py changed since" in r.stderr, r.stderr

    def test_a_card_edited_after_its_refresh_is_refused_at_the_mint(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="planned")
        seed_refresh_receipt(repo, env)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Context: demo.", "Context: unchecked."))
        r = spawn(repo, env, "ready", "story-042")
        assert r.returncode == 2, r.stdout
        assert "ran against different text" in r.stderr, r.stderr

    @pytest.mark.parametrize(
        ("payload", "diagnosis"),
        [
            ("{", "is unreadable"),
            ("[]", "is not a card refresh receipt"),
            ('{"digest": "x", "files": "src/thing.py"}', "is not a card refresh receipt"),
            ('{"files": {}}', "does not match the current card"),
        ],
    )
    def test_a_receipt_that_is_not_one_refuses_by_name(self, tmp_path, payload, diagnosis):
        """Constraint 15: missing is not unreadable, and unreadable is not "ran
        against different text" — each sends the lead somewhere different."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        seed_refresh_receipt(repo, env)
        self.receipt(tmp_path).write_text(payload)
        r = spawn(repo, env, "ready", "story-042")
        assert r.returncode == 2, r.stdout
        assert "Traceback" not in r.stderr and diagnosis in r.stderr, r.stderr

    def test_a_receipt_covering_fewer_paths_than_the_card_declares_is_refused(self, tmp_path):
        """No card EDIT reaches this branch — changing `Files:` moves the digest,
        which refuses one check earlier — so the state it guards is a receipt
        written by an older `declared_files`, and it is constructed here directly.
        Left in place rather than deleted: the alternative is `.get`, which lets
        an uncovered path pass as absent."""
        repo, env, _g = make_repo(tmp_path, status="planned")
        seed_refresh_receipt(repo, env)
        kept = json.loads(self.receipt(tmp_path).read_text()) | {"files": {}}
        self.receipt(tmp_path).write_text(json.dumps(kept))
        r = spawn(repo, env, "ready", "story-042")
        assert r.returncode == 2, r.stdout
        assert "does not cover src/thing.py" in r.stderr, r.stderr

    def test_the_gate_is_never_inherited_by_a_caller_that_did_not_ask_for_it(self):
        """`mint` has TWO callers and the free lane exempts itself, so the flag
        carries no default: the exemption has to be a decision at every call
        site, not the value a caller added later silently gets. Which lane is
        exempt is walked in test_close_free.py, not asserted here."""
        import inspect

        import ready as credential

        signature = inspect.signature(credential.mint)
        assert signature.parameters["require_refresh"].default is inspect.Parameter.empty
        free = (SPAWN.parent / "close" / "free.py").read_text()
        assert "ready.mint(key, require_refresh=False)" in free
