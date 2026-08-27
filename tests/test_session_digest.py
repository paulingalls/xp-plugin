"""The session digest layer: staleness, and the bound that refuses over it.

Extracted from test_session_start.py when the digest bound took it to 496 of the
500-line cap — over cap means extract, not scroll, and the digest is the cohesive
leaf (constraint 8). THIS repo's own digest is measured next door, in
test_session_start_profile.py, where every other real-artifact check lives.

Verify: pytest -q tests/test_session_digest.py"""

from session_start_helpers import run_recovery, xp_repo


class TestTheDigestLayer:
    def test_fresh_digest_injected_without_stale(self, tmp_path):
        repo, g = xp_repo(tmp_path)
        head = g("rev-parse", "--short", "HEAD").stdout.strip()
        data = tmp_path / "xp"
        data.mkdir(exist_ok=True)
        (data / "session.md").write_text(f"# Session digest — written x at {head}\nDIGEST-BODY\n")
        r = run_recovery(repo, tmp_path)
        assert "DIGEST-BODY" in r.stdout and "STALE" not in r.stdout

    def test_stale_digest_prefixed_with_distance(self, tmp_path):
        repo, g = xp_repo(tmp_path)
        old = g("rev-parse", "--short", "HEAD").stdout.strip()
        data = tmp_path / "xp"
        data.mkdir(exist_ok=True)
        (data / "session.md").write_text(f"# Session digest — written x at {old}\nDIGEST-BODY\n")
        (repo / "f.py").write_text("A = 2\n")
        g("add", "-A")
        g("commit", "-qm", "one")
        (repo / "f.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "two")
        r = run_recovery(repo, tmp_path)
        assert "STALE" in r.stdout and "2 commit" in r.stdout

    def test_stampless_digest_reads_stale_unknown(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        data = tmp_path / "xp"
        data.mkdir(exist_ok=True)
        (data / "session.md").write_text("no stamp here\nDIGEST-BODY\n")
        r = run_recovery(repo, tmp_path)
        assert "STALE" in r.stdout and "unknown" in r.stdout

    def test_no_digest_recovery_block_only(self, tmp_path):
        repo, _g = xp_repo(tmp_path)
        r = run_recovery(repo, tmp_path)
        assert r.returncode == 0
        assert "STALE" not in r.stdout and "story-042" in r.stdout

    def test_a_digest_over_the_bound_is_refused_by_path_and_count(self, tmp_path):
        """bug 597c32db: the size was stated in three prose places and measured
        nowhere, so ours reached 380 lines and evicted four constraints. The
        refusal names the path, the count and the bound — one that said only
        "too long" would leave the lead guessing which file.

        Asserted through the WHOLE hook, not through the measuring function: the
        OUTPUT_CAP cut takes the tail, and the digest's own slot IS the tail.
        """
        repo, _g = xp_repo(tmp_path)
        data = tmp_path / "xp"
        data.mkdir(exist_ok=True)
        digest = data / "session.md"
        digest.write_text("# Session digest — written x at y\n" + "DIGEST-BODY\n" * 40)
        out = run_recovery(repo, tmp_path).stdout
        assert str(digest) in out and "41 lines" in out and "30-line" in out, out
        assert "DIGEST-BODY" not in out, "the oversized digest was injected anyway"

    def test_a_digest_at_the_bound_is_injected_untouched(self, tmp_path):
        """Constraint 2: without this arm the check above passes just as well
        against a mechanism that refuses every digest there is."""
        repo, g = xp_repo(tmp_path)
        head = g("rev-parse", "--short", "HEAD").stdout.strip()
        data = tmp_path / "xp"
        data.mkdir(exist_ok=True)
        (data / "session.md").write_text(
            f"# Session digest — written x at {head}\n" + "DIGEST-BODY\n" * 29
        )
        out = run_recovery(repo, tmp_path).stdout
        assert "DIGEST-BODY" in out and "NOT INJECTED" not in out, out

    def test_an_unreadable_digest_costs_the_digest_and_not_the_recovery_block(self, tmp_path):
        """Constraint 15, and the file's own "one bad file degrades one section".
        `digest_refusal` is read from INSIDE `recovery_block`, so a raise there
        takes branch, dirty count, stories and work.md entries with it — the one
        layer that cannot go stale, gone in silence at exit 0.

        A DIRECTORY at the path is the cheap unreadable: `exists()` is true and
        `read_text` raises, which is exactly the absent-vs-unreadable split.
        """
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp").mkdir(exist_ok=True)
        (tmp_path / "xp" / "session.md").mkdir()
        out = run_recovery(repo, tmp_path).stdout
        assert "story-042" in out, "the unreadable digest ate the whole recovery block"
        assert "UNREADABLE" in out, out
