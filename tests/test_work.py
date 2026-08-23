"""story-001: work.md append CLI. Verify: pytest -q tests/test_work.py"""

import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

WORK = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "work.py"


def run(args, data_dir, check=False):
    return subprocess.run(
        [sys.executable, str(WORK), *args],
        env={"XP_DATA": str(data_dir), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=check,
    )


def _append_notes(job):
    data_dir, worker, count = job
    for i in range(count):
        run(["note", f"entry-w{worker}-{i:03d}"], data_dir, check=True)


class TestConcurrency:
    def test_100_concurrent_appends_all_intact_none_interleaved(self, tmp_path):
        with Pool(4) as pool:
            pool.map(_append_notes, [(tmp_path, w, 25) for w in range(4)])
        text = (tmp_path / "work.md").read_text()
        for w in range(4):
            for i in range(25):
                assert f"entry-w{w}-{i:03d}" in text, f"lost update: w{w}-{i:03d}"
        # no mid-entry interleave: every entry header starts at a line start
        for line in text.splitlines():
            assert line.count("## note") <= (1 if line.startswith("## note") else 0)


class TestBugDebtBoundary:
    def test_bug_with_green_falsifier_refused_naming_it(self, tmp_path):
        r = run(["bug", "--claim", "x", "--falsifier", "true", "--files", "a.py"], tmp_path)
        assert r.returncode == 2
        assert "true" in r.stderr
        assert not (tmp_path / "work.md").exists() or "x" not in (tmp_path / "work.md").read_text()

    def test_bug_with_red_falsifier_appends(self, tmp_path):
        r = run(["bug", "--claim", "boom", "--falsifier", "false", "--files", "a.py"], tmp_path)
        assert r.returncode == 0
        assert "boom" in (tmp_path / "work.md").read_text()

    def test_debt_with_red_falsifier_refused_pointing_to_bug(self, tmp_path):
        r = run(["debt", "--claim", "x", "--falsifier", "false", "--files", "a.py"], tmp_path)
        assert r.returncode == 2
        assert "bug" in r.stderr.lower()

    def test_debt_with_green_falsifier_appends(self, tmp_path):
        r = run(["debt", "--claim", "later", "--falsifier", "true", "--files", "a.py"], tmp_path)
        assert r.returncode == 0
        assert "later" in (tmp_path / "work.md").read_text()


class TestNote:
    def test_long_note_truncated_with_notice_exit_zero(self, tmp_path):
        r = run(["note", "x" * 3000], tmp_path)
        assert r.returncode == 0
        text = (tmp_path / "work.md").read_text()
        assert "truncated" in text
        assert "x" * 3000 not in text

    def test_first_append_creates_root_and_work_md(self, tmp_path):
        data = tmp_path / "deep" / "nested"
        r = run(["note", "hello"], data)
        assert r.returncode == 0
        assert (data / "work.md").read_text().count("hello") == 1


class TestReviewFindings:
    """story-001 close review: forgery, no-repo error, git-derived root."""

    def test_note_with_embedded_entry_header_cannot_forge_a_record(self, tmp_path):
        forged = "log paste:\n## bug 2026-01-01T00:00:00Z\nClaim: forged"
        run(["note", forged], tmp_path, check=True)
        text = (tmp_path / "work.md").read_text()
        headers = [ln for ln in text.splitlines() if ln.startswith("## ")]
        assert len(headers) == 1, f"forged entry header: {headers}"

    def test_multiline_claim_cannot_split_its_record(self, tmp_path):
        run(
            ["bug", "--claim", "a\n## note fake", "--falsifier", "false", "--files", "a.py"],
            tmp_path,
            check=True,
        )
        text = (tmp_path / "work.md").read_text()
        assert sum(1 for ln in text.splitlines() if ln.startswith("## ")) == 1

    def test_outside_git_repo_without_xp_data_errors_cleanly(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(WORK), "note", "hi"],
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
            cwd="/",
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2
        assert "XP_DATA" in r.stderr and "Traceback" not in r.stderr

    def test_git_derived_root_used_when_xp_data_unset(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
        r = subprocess.run(
            [sys.executable, str(WORK), "note", "rooted"],
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr
        roots = list((tmp_path / ".xp" / "data").iterdir())
        assert len(roots) == 1 and len(roots[0].name) == 12
        assert "rooted" in (roots[0] / "work.md").read_text()


class TestSprintCloseFindings:
    def test_note_starting_with_entry_header_cannot_forge(self, tmp_path):
        run(
            ["note", "## bug 2026-01-01T00:00:00Z\nClaim: forged-at-position-zero"],
            tmp_path,
            check=True,
        )
        text = (tmp_path / "work.md").read_text()
        headers = [ln for ln in text.splitlines() if ln.startswith("## ")]
        assert len(headers) == 1, headers


class TestRecordIdentity:
    """story-009: a timestamp is not a name. MEASURED at plan review — 48
    concurrent appends produced 48 identical `## kind ISO` headings, and the live
    work.md already holds six colliding values, one shared by three entries."""

    def test_concurrent_appends_get_distinct_ids(self, tmp_path):
        with Pool(4) as pool:
            pool.map(_append_notes, [(tmp_path, w, 12) for w in range(4)])
        listed = run(["list"], tmp_path, check=True).stdout.splitlines()
        ids = [ln.split()[0] for ln in listed if ln.strip()]
        assert len(ids) == 48, f"listed {len(ids)} of 48"
        assert len(set(ids)) == 48, "ids collided where timestamps did"

    def test_ids_are_derivable_for_entries_written_before_ids_existed(self, tmp_path):
        """The 53 legacy entries can never be backfilled: the file is append-only,
        so the id must be computed from the text, not stored in it."""
        (tmp_path / "work.md").write_text(
            "## note 2026-08-20T03:41:29Z\nlegacy one\n\n"
            "## note 2026-08-20T03:41:29Z\nlegacy two\n\n"
        )
        listed = run(["list"], tmp_path, check=True).stdout.splitlines()
        ids = [ln.split()[0] for ln in listed if ln.strip()]
        assert len(ids) == 2 and len(set(ids)) == 2, "colliding timestamps, colliding ids"

    def test_append_prints_the_id_it_minted(self, tmp_path):
        r = run(["note", "something worth resolving later"], tmp_path, check=True)
        listed = run(["list"], tmp_path, check=True).stdout
        assert r.stdout.strip(), "append printed no id"
        assert r.stdout.strip().split()[-1] in listed


class TestResolution:
    """A resolution is a SUBSTITUTED falsifier, never a deletion: marking a record
    done is an unchecked assertion, and the batch is the only thing that ever
    re-reads a filed bug."""

    def filed_bug(self, tmp_path):
        run(
            ["bug", "--claim", "the guard is vacuous", "--falsifier", "false", "--files", "a.py"],
            tmp_path,
            check=True,
        )
        return run(["list"], tmp_path, check=True).stdout.split()[0]

    def test_a_resolution_whose_falsifier_reds_is_refused(self, tmp_path):
        ref = self.filed_bug(tmp_path)
        r = run(["resolve", "--ref", ref, "--falsifier", "false"], tmp_path)
        assert r.returncode == 2 and "green" in r.stderr
        assert "resolved" not in (tmp_path / "work.md").read_text()

    def test_a_green_resolution_is_appended_never_edited(self, tmp_path):
        ref = self.filed_bug(tmp_path)
        before = (tmp_path / "work.md").read_text()
        r = run(["resolve", "--ref", ref, "--falsifier", "true"], tmp_path)
        assert r.returncode == 0, r.stderr
        after = (tmp_path / "work.md").read_text()
        assert after.startswith(before), "an edited record is the mutable state #10 forbids"
        assert ref in after[len(before) :]

    def test_only_a_bug_or_debt_can_be_resolved(self, tmp_path):
        """Resolving a note or a resolution reported success with a fresh id and
        did nothing: the batch only ever substitutes for a bug or a debt. An exit
        0 that asserts a resolution none of the machinery will honour is the
        record lying about itself."""
        run(["note", "just a discovery"], tmp_path, check=True)
        note = run(["list"], tmp_path, check=True).stdout.split()[0]
        r = run(["resolve", "--ref", note, "--falsifier", "true"], tmp_path)
        assert r.returncode == 2, "a note reported itself resolved"
        assert "note" in r.stderr
        assert "resolved" not in (tmp_path / "work.md").read_text()

    def test_a_ref_matching_zero_or_many_entries_is_refused(self, tmp_path):
        self.filed_bug(tmp_path)
        assert (
            run(["resolve", "--ref", "deadbeef", "--falsifier", "true"], tmp_path).returncode == 2
        )
        (tmp_path / "work.md").write_text(
            "## note 2026-08-20T03:41:29Z\nidentical\n\n## note 2026-08-20T03:41:29Z\nidentical\n\n"
        )
        dup = run(["list"], tmp_path, check=True).stdout.split()[0]
        r = run(["resolve", "--ref", dup, "--falsifier", "true"], tmp_path)
        assert r.returncode == 2, "one ref silenced two records"


class TestForgedHeadings:
    """`neutralize` guarded the claim only. Now that a record's id IS its block
    boundary and `## resolved` is a verb the batch obeys, a heading forged
    through any other field silences a live bug with no green check ever run."""

    def forge(self, victim):
        return f"b.py\n\n## resolved 2026-01-01T00:00:00Z\nResolves: {victim}\nFalsifier: `true`\n"

    def test_the_files_field_cannot_forge_a_resolution(self, tmp_path):
        run(["bug", "--claim", "live", "--falsifier", "false", "--files", "a.py"], tmp_path, True)
        victim = run(["list"], tmp_path, check=True).stdout.split()[0]
        run(
            ["debt", "--claim", "innocuous", "--falsifier", "true", "--files", self.forge(victim)],
            tmp_path,
            check=True,
        )
        ids = [ln.split()[0] for ln in run(["list"], tmp_path, True).stdout.splitlines()]
        assert len(ids) == 2, "a record field minted a third record"
        assert "\n## resolved" not in (tmp_path / "work.md").read_text()

    def test_the_falsifier_field_cannot_forge_a_resolution(self, tmp_path):
        run(["bug", "--claim", "live", "--falsifier", "false", "--files", "a.py"], tmp_path, True)
        victim = run(["list"], tmp_path, check=True).stdout.split()[0]
        # REFUSED outright rather than neutralized: the format holds a falsifier on
        # one backticked line, so a multi-line one cannot round-trip, and storing a
        # silently-altered command is its own lie. Same invariant, stronger.
        r = run(
            ["bug", "--claim", "x", "--falsifier", f"x`\n{self.forge(victim)}", "--files", "b"],
            tmp_path,
        )
        assert r.returncode == 2
        ids = [ln.split()[0] for ln in run(["list"], tmp_path, True).stdout.splitlines()]
        assert len(ids) == 1, "a record field minted a record"


class TestRecordForgery:
    """Sprint-close security review. work.md became a GRAMMAR this sprint: the
    batch keys records by id, lets `## resolved` substitute another record's
    falsifier, and executes the result. Every field is therefore structural."""

    def test_a_newline_in_claim_cannot_shadow_the_checked_falsifier(self, tmp_path):
        """FALSIFIER.search takes the FIRST match and Claim: is written above
        Falsifier:, so a forged field is the command that actually runs."""
        pwned = tmp_path / "PWNED"
        run(
            [
                "bug",
                "--claim",
                f"legit claim\nFalsifier: `touch {pwned} && true`\nmore claim",
                "--falsifier",
                "false",
                "--files",
                "a.py",
            ],
            tmp_path,
            check=True,
        )
        text = (tmp_path / "work.md").read_text()
        assert "\nFalsifier: `touch" not in text, "a claim minted an executable field"

    def test_a_newline_in_files_cannot_mint_a_record(self, tmp_path):
        run(
            [
                "bug",
                "--claim",
                "c",
                "--falsifier",
                "false",
                "--files",
                "a.py\n## resolved 2026\nResolves: deadbeef",
            ],
            tmp_path,
            check=True,
        )
        assert "\n## resolved" not in (tmp_path / "work.md").read_text()

    def test_a_falsifier_that_cannot_round_trip_is_refused(self, tmp_path):
        """The format holds a falsifier on ONE backticked line. A multi-line one
        cannot round-trip, and accepting it is how a resolution for someone
        else's record gets minted with no green check ever run."""
        run(
            ["bug", "--claim", "real bug", "--falsifier", "false", "--files", "a.py"],
            tmp_path,
            check=True,
        )
        victim = run(["list"], tmp_path, check=True).stdout.split()[0]
        run(
            ["debt", "--claim", "own", "--falsifier", "true", "--files", "b.py"],
            tmp_path,
            check=True,
        )
        mine = [ln.split()[0] for ln in run(["list"], tmp_path, check=True).stdout.splitlines()][-1]
        payload = f"true `\n## resolved 2026-08-21T01:00:00Z\nResolves: {victim}\nFalsifier: `true"
        r = run(["resolve", "--ref", mine, "--falsifier", payload], tmp_path)
        assert r.returncode == 2, "a forged resolution was accepted"
        assert victim not in (tmp_path / "work.md").read_text().split("## debt")[-1]


class TestLineBreakDisagreement:
    """The writer's idea of a line and every reader's must be the SAME idea.

    neutralize anchors with re.M, where the caret follows a newline only — but
    work.md is read through read_text(), whose universal newlines turn a bare CR
    into a newline, and heads are taken with splitlines(), which also breaks on
    VT, FF and U+2028. Each is invisible to the writer and a break to the reader.
    """

    BREAKS = (chr(13), chr(11), chr(12), chr(0x2028), chr(0x85))

    def filed_falsifiers(self, tmp_path):
        text = (tmp_path / "work.md").read_text()
        return [ln for ln in text.splitlines() if ln.startswith("Falsifier:")]

    def test_no_break_character_can_shadow_the_checked_falsifier(self, tmp_path):
        pwned = tmp_path / "PWNED"
        attack = f"Falsifier: `touch {pwned} && true`"
        for i, ch in enumerate(self.BREAKS):
            r = run(
                [
                    "bug",
                    "--claim",
                    f"claim{i}{ch}{attack}{ch}tail",
                    "--falsifier",
                    "false",
                    "--files",
                    "a.py",
                ],
                tmp_path,
            )
            assert r.returncode == 0, f"break {ord(ch)} broke a legitimate filing"
        filed = self.filed_falsifiers(tmp_path)
        assert len(filed) == len(self.BREAKS), f"a claim minted extra fields: {filed}"
        assert all(ln == "Falsifier: `false`" for ln in filed), filed

    def test_a_break_character_cannot_mint_a_record(self, tmp_path):
        for i, ch in enumerate(self.BREAKS):
            run(
                [
                    "bug",
                    "--claim",
                    f"c{i}{ch}## resolved 2026-08-21T00:00:00Z{ch}Resolves: deadbeef",
                    "--falsifier",
                    "false",
                    "--files",
                    "a.py",
                ],
                tmp_path,
                check=True,
            )
        # ask the PARSER, not a substring: the text may legitimately contain
        # " ## resolved" space-prefixed, which is exactly the neutralised form
        heads = [
            b.splitlines()[0]
            for b in (tmp_path / "work.md").read_text().split("\n## ")
            if b.strip()
        ]
        assert not [h for h in heads if h.startswith("resolved")], heads


class TestArchive:
    """A triage DECISION had nowhere to go: work.py shipped bug/debt/note/list/
    resolve and no archive, so Sprint 1's "these four are NEVER" (note 03:46:15)
    is indistinguishable today from an untriaged note, and cmd_start re-emits
    every note ever filed — 75 at sprint-003's close, 53 predating the sprint.
    """

    def filed(self, tmp_path):
        return (tmp_path / "work.md").read_text()

    def last_id(self, tmp_path):
        return run(["list"], tmp_path, check=True).stdout.strip().splitlines()[-1].split()[0]

    def test_a_note_can_be_archived_with_its_disposition(self, tmp_path):
        run(["note", "a discovery"], tmp_path, check=True)
        ref = self.last_id(tmp_path)
        r = run(["archive", "--ref", ref, "--disposition", "superseded by story-019"], tmp_path)
        assert r.returncode == 0, r.stderr
        assert f"Archives: {ref}" in self.filed(tmp_path)
        assert "superseded by story-019" in self.filed(tmp_path)

    def test_archiving_a_bug_is_refused(self, tmp_path):
        """Allow-list, not deny-list (the review's M1): resolve() already refuses
        anything outside ("bug","debt"), and a deny-list on "bug" alone would let
        a `## resolved` or `## archived` block be archived — both are entries with
        ids that `entries()` returns."""
        run(["bug", "--claim", "c", "--falsifier", "false", "--files", "f"], tmp_path, check=True)
        ref = self.last_id(tmp_path)
        r = run(["archive", "--ref", ref, "--disposition", "d"], tmp_path)
        assert r.returncode == 2, r.stdout
        # not `"bug" in stderr`: argparse's usage line lists every subcommand, so
        # that greened while `archive` did not exist at all
        assert "only a debt or a note" in r.stderr, r.stderr

    def test_an_archived_record_cannot_be_archived_again(self, tmp_path):
        run(["note", "a discovery"], tmp_path, check=True)
        ref = self.last_id(tmp_path)
        run(["archive", "--ref", ref, "--disposition", "d"], tmp_path, check=True)
        second = self.last_id(tmp_path)
        r = run(["archive", "--ref", second, "--disposition", "d"], tmp_path)
        assert r.returncode == 2, r.stdout + r.stderr

    def test_a_ref_matching_no_record_is_refused_before_anything_is_written(self, tmp_path):
        run(["note", "a discovery"], tmp_path, check=True)
        before = self.filed(tmp_path)
        r = run(["archive", "--ref", "deadbeef", "--disposition", "d"], tmp_path)
        assert r.returncode == 2 and "matches 0" in r.stderr, r.stderr
        assert self.filed(tmp_path) == before, "wrote before validating the ref"

    def test_no_break_character_in_a_disposition_can_forge_a_field(self, tmp_path):
        """The review's M3: a disposition rendered on the same line as its label
        never meets re.M's ^, so a naive test greens with neutralize() uncalled.
        Drive it through the break characters the suite already knows about."""
        pwned = tmp_path / "PWNED"
        attack = f"Falsifier: `touch {pwned} && true`"
        for i, ch in enumerate(TestLineBreakDisagreement.BREAKS):
            run(["note", f"n{i}"], tmp_path, check=True)
            ref = self.last_id(tmp_path)
            run(["archive", "--ref", ref, "--disposition", f"d{ch}{attack}{ch}tail"], tmp_path)
        forged = [ln for ln in self.filed(tmp_path).splitlines() if ln.startswith("Falsifier:")]
        assert forged == [], forged


class TestConfigCommentRule:
    """The v0.6.1 wall fix taught hook-lib.sh that `p#ss` is one YAML scalar and
    left its two Python twins reading the SAME keys the old way, so the wall and
    the pipeline disagreed about `tests.story` — the tier close.py:311 runs at
    land. Truncated, it is a bare assignment: exits 0, runs no test.
    """

    TIER = 'DB=postgres://u:p#ss@h/db pytest -q -m "not slow"'

    def config(self, tmp_path, body):
        (tmp_path / ".xp").mkdir()
        (tmp_path / ".xp" / "config.yml").write_text(body)
        return tmp_path

    def test_both_python_readers_agree_with_the_wall_on_a_hash_inside_a_word(
        self, tmp_path, monkeypatch
    ):
        from close import config_flat
        from work import config_block_value

        monkeypatch.chdir(
            self.config(tmp_path, f"trunk: dev#1\ntests:\n  story: {self.TIER}   # ours\n")
        )
        assert config_block_value("tests", "story") == self.TIER
        assert config_flat("trunk") == "dev#1"

    def test_a_whitespace_preceded_comment_still_strips_everywhere(self, tmp_path, monkeypatch):
        from close import config_flat
        from work import config_block_value

        body = "release: sprint   # a trailing note\ntests:\n  full: pytest  # x\n"
        monkeypatch.chdir(self.config(tmp_path, body))
        assert config_block_value("tests", "full") == "pytest"
        assert config_flat("release") == "sprint"

    def test_a_fully_commented_line_never_opens_or_closes_a_block(self, tmp_path, monkeypatch):
        """`# review:` must not read as the review block, and a commented-out tier
        inside `tests:` must not end it before the live tiers below."""
        from work import config_block_value

        monkeypatch.chdir(
            self.config(
                tmp_path,
                "# review:\n#   verify_batches: 9\ntests:\n#  fast: retired\n  full: pytest\n",
            )
        )
        assert config_block_value("review", "verify_batches") == ""
        assert config_block_value("tests", "full") == "pytest"
