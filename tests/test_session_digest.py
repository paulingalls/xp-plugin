"""The session digest layer: staleness and the soft size bound.

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

    def test_an_over_bound_digest_warns_then_injects_the_whole_body(self, tmp_path):
        """bug 597c32db: the size was stated in three prose places and measured
        nowhere, so ours reached 380 lines and evicted four constraints. The
        warning names the path, the count and the bound — one that said only
        "too long" would leave the lead guessing which file.

        Asserted through the WHOLE hook, not through the measuring function: the
        OUTPUT_CAP cut takes the tail, and the digest's own slot IS the tail.
        """
        repo, _g = xp_repo(tmp_path)
        data = tmp_path / "xp"
        data.mkdir(exist_ok=True)
        digest = data / "session.md"
        body = [f"DIGEST-BODY-{line}" for line in range(1, 41)]
        digest.write_text("# Session digest — written x at y\n" + "\n".join(body) + "\n")
        out = run_recovery(repo, tmp_path).stdout
        region = out.split("## digest\n", 1)[1].split("## recovery block", 1)[0]
        warning = region.splitlines()[0]
        assert str(digest) in warning and "41 lines" in warning and "30-line" in warning
        assert "WARNING" in warning and "full digest follows" in warning.lower()
        assert [line for line in region.splitlines() if line.startswith("DIGEST-BODY-")] == body
        assert region.index(warning) < region.index(body[0]) < region.index(body[-1])

    def test_an_over_bound_stale_digest_keeps_warning_and_staleness(self, tmp_path):
        repo, g = xp_repo(tmp_path)
        old = g("rev-parse", "--short", "HEAD").stdout.strip()
        data = tmp_path / "xp"
        data.mkdir(exist_ok=True)
        digest = data / "session.md"
        body = [f"STALE-DIGEST-BODY-{line}" for line in range(1, 31)]
        digest.write_text(f"# Session digest — written x at {old}\n" + "\n".join(body) + "\n")
        (repo / "f.py").write_text("A = 2\n")
        g("add", "-A")
        g("commit", "-qm", "advance")

        region = run_recovery(repo, tmp_path).stdout.split("## recovery block", 1)[0]
        assert str(digest) in region and "31 lines" in region and "30-line" in region
        assert region.index("WARNING") < region.index("STALE")
        assert region.index("STALE") < region.index(body[0]) < region.index(body[-1])

    def test_a_digest_at_the_bound_is_injected_untouched(self, tmp_path):
        """Constraint 2: without this arm the check above passes just as well
        against a mechanism that warns for every digest there is."""
        repo, g = xp_repo(tmp_path)
        head = g("rev-parse", "--short", "HEAD").stdout.strip()
        data = tmp_path / "xp"
        data.mkdir(exist_ok=True)
        (data / "session.md").write_text(
            f"# Session digest — written x at {head}\n" + "DIGEST-BODY\n" * 29
        )
        out = run_recovery(repo, tmp_path).stdout
        assert "DIGEST-BODY" in out and "session digest WARNING" not in out, out

    def test_an_unreadable_digest_costs_the_digest_and_not_the_recovery_block(self, tmp_path):
        """A directory constructs unreadable rather than absent (constraint 15)."""
        repo, _g = xp_repo(tmp_path)
        (tmp_path / "xp").mkdir(exist_ok=True)
        (tmp_path / "xp" / "session.md").mkdir()
        out = run_recovery(repo, tmp_path).stdout
        assert "story-042" in out, "the unreadable digest ate the whole recovery block"
        assert "UNREADABLE" in out, out
        assert "session digest WARNING" not in out and "lines against" not in out
