"""TestArchive, lifted whole at the sprint-22 [sprint-direct] disposal fix.

test_work.py stood at 492 of constraint 8's 500-line hard cap with the
filed-in-error cases still to write. Tests are production code and the cap
binds them; extraction at the cap needs no separate approval so long as
collection is unchanged either side (constraint 8).
"""

# ALIASED out of pytest's Test* collection pattern: importing the class under its
# own name collects its cases a SECOND time here (measured: 40 where 38 are real).
from test_work import TestLineBreakDisagreement as _LineBreaks
from work_helpers import resolve_without_tier, run


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
        assert "an already RESOLVED bug" in r.stderr and "then resolve it" in r.stderr

    def test_an_archived_record_cannot_be_archived_again(self, tmp_path):
        run(["note", "a discovery"], tmp_path, check=True)
        ref = self.last_id(tmp_path)
        run(["archive", "--ref", ref, "--disposition", "d"], tmp_path, check=True)
        second = self.last_id(tmp_path)
        r = run(["archive", "--ref", second, "--disposition", "d"], tmp_path)
        assert r.returncode == 2, r.stdout + r.stderr
        # constraint 15: retired is not unfinished. A refusal naming only the bug
        # arm sends a lead holding a DISPOSED record to `resolve`, which checks
        # only that the replacement is green — a frictionless dishonest exit.
        assert "already disposed" in r.stderr, r.stderr

    def test_a_ref_matching_no_record_is_refused_before_anything_is_written(self, tmp_path):
        run(["note", "a discovery"], tmp_path, check=True)
        before = self.filed(tmp_path)
        r = run(["archive", "--ref", "deadbeef", "--disposition", "d"], tmp_path)
        assert r.returncode == 2 and "matches 0" in r.stderr, r.stderr
        assert self.filed(tmp_path) == before, "wrote before validating the ref"

    def test_neither_leg_refuses_in_silence(self, tmp_path):
        """A refusal that prints nothing leaves the lead an exit code and no next
        action. Constructed, not grepped: a heading whose kind field reads EMPTY
        is the one record shape that walks past both `--ref` arms."""
        (tmp_path / "work.md").write_text("##  bug 2026-08-20T03:41:29Z\nClaim: c\n\n")
        ref = run(["list"], tmp_path, check=True).stdout.split()[0]
        for args in (
            ["archive", "--ref", ref, "--disposition", "d"],
            resolve_without_tier(ref, "true"),
        ):
            r = run(args, tmp_path)
            assert r.returncode == 2, r.stdout
            assert ref in r.stderr, f"{args[0]} refused without naming the record: {r.stderr!r}"

    def test_no_break_character_in_a_disposition_can_forge_a_field(self, tmp_path):
        """The review's M3: a disposition rendered on the same line as its label
        never meets re.M's ^, so a naive test greens with neutralize() uncalled.
        Drive it through the break characters the suite already knows about."""
        pwned = tmp_path / "PWNED"
        attack = f"Falsifier: `touch {pwned} && true`"
        for i, ch in enumerate(_LineBreaks.BREAKS):
            run(["note", f"n{i}"], tmp_path, check=True)
            ref = self.last_id(tmp_path)
            run(["archive", "--ref", ref, "--disposition", f"d{ch}{attack}{ch}tail"], tmp_path)
        forged = [ln for ln in self.filed(tmp_path).splitlines() if ln.startswith("Falsifier:")]
        assert forged == [], forged

    def test_a_bug_filed_in_error_is_archivable_with_a_reason(self, tmp_path):
        """Constraint 15: FILED IN ERROR is a state, distinct from both `open` and
        `fixed`, and until this case the tool conflated it with `open`.

        MEASURED, sprint 22: a bug whose subject lived in an unlanded story could
        not be disposed of at all. `archive` refuses an unresolved bug, `resolve`
        demands a green replacement, and the only covering falsifier was inside
        the story the record was blocking — so the record blocked every card in
        the sprint and had no honest exit. Fixing the bug was not available: there
        was nothing wrong with the code, only with the record.
        """
        run(["bug", "--claim", "c", "--falsifier", "false", "--files", "f"], tmp_path, check=True)
        ref = self.last_id(tmp_path)
        reason = "misfiled: wrong record type and a falsifier that never covered the claim"
        r = run(["archive", "--ref", ref, "--disposition", reason], tmp_path)
        assert r.returncode == 0, r.stderr
        assert f"Archives: {ref}" in self.filed(tmp_path)
        assert "misfiled" in self.filed(tmp_path)

    def test_filed_in_error_is_not_a_frictionless_exit(self, tmp_path):
        """The disposal must stay EXPENSIVE to reach by accident, or it becomes the
        cheap way to bury a real red falsifier — which is the whole reason archive
        refused unresolved bugs in the first place. The word alone buys nothing.
        """
        run(["bug", "--claim", "c", "--falsifier", "false", "--files", "f"], tmp_path, check=True)
        ref = self.last_id(tmp_path)
        bare = run(["archive", "--ref", ref, "--disposition", "misfiled"], tmp_path)
        assert bare.returncode == 2, bare.stdout
        assert "why it was filed in error" in bare.stderr, bare.stderr
        plain = run(["archive", "--ref", ref, "--disposition", "dropped"], tmp_path)
        assert plain.returncode == 2, "the ordinary refusal must be untouched"
        assert "an already RESOLVED bug" in plain.stderr
