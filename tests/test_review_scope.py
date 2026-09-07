"""The `.xp/` scope guard, and the normalisation the card's Files line needs first.

Extracted from tests/test_review.py at story-093, which was AT the 500-line cap
(constraint 8) when issue #45 arrived and so had no room for the case below.
Verify: pytest -q tests/test_review_scope.py
"""

import json

from review import declared_files
from sprint_helpers import (
    PLAN,
    PLUGIN,
    make_repo,
    marker_path,
    sprint,
    staged_stub,
)

CANDIDATES = {"fixed": [], "blocking": ["a silent one"], "noted": ["a loud one"]}

SURVIVES = {"fixed": [], "blocking": ["a silent one"], "noted": []}

DECLARED = "#### story-042 — done thing   [done]"


def declaring(files):
    return PLAN.replace(DECLARED, f"{DECLARED}\nFiles: {files}")


class TestAnUndeclaredPathIsRefused:
    def test_a_fixer_patch_touching_an_UNDECLARED_xp_file_is_refused(self, tmp_path):
        """The `.xp/` scope moved from the committed range to patch apply, and the
        sprint arm passes the whole sprint's cards where the story arm passes one.
        Only the story arm had a negative test, so this call site's refusal was
        carried by nothing (constraint 2)."""
        repo, env, _g = make_repo(tmp_path)
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            patches=[("fix", ".xp/constraints.md", "sneaky")],
        )
        r = sprint(repo, env, "review")
        assert r.returncode == 2, r.stdout
        assert ".xp/constraints.md" in r.stderr and "Files line" in r.stderr, r.stderr
        assert "sneaky" not in (repo / ".xp" / "constraints.md").read_text()
        assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["incomplete"]

    def test_LAND_names_a_GATE_file_the_fixer_rewrote(self, tmp_path):
        """The scope rule lets the fixer edit any `.xp/` path a sprint card's Files
        line declares, and a card DOES declare `.xp/system.md`, whose `Worktree
        bootstrap:` line spawn shell-executes. shown_sha is recorded AFTER the
        fixer, so land's own GATE_FILES check compares an empty range and never
        sees it. Loud is the least this can be."""
        repo, env, _g = make_repo(tmp_path, plan=declaring("src.py, .xp/system.md"))
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            patches=[("fix", ".xp/system.md", "boot: x")],
        )
        assert sprint(repo, env, "review").returncode == 0
        land = sprint(repo, env, "land")
        assert "gate file" in land.stdout and ".xp/system.md" in land.stdout, land.stdout


class TestTheFilesLineIsProseNotAPath:
    """Issue #45, field-reported on 0.15.0: `declared_files` strips whitespace only,
    so a path a human wrote for a human never equals what git prints. The guard then
    refuses a file the card DOES name, and its refusal path hard-resets the tree.
    Both decorations below are live: backticks are the markdown convention the issue
    hit, and `(new)` is on three cards of this repo's own Sprint 16 slate."""

    def accepts(self, tmp_path, files):
        repo, env, _g = make_repo(tmp_path, plan=declaring(files))
        staged_stub(
            tmp_path,
            find=CANDIDATES,
            verify=SURVIVES,
            patches=[("fix", ".xp/system.md", "boot: x")],
        )
        return sprint(repo, env, "review")

    def test_a_BACKTICKED_declaration_names_the_path_it_spells(self, tmp_path):
        r = self.accepts(tmp_path, "`src.py`, `.xp/system.md`")
        assert r.returncode == 0, r.stderr

    def test_a_declaration_annotated_NEW_names_the_path_it_spells(self, tmp_path):
        r = self.accepts(tmp_path, "src.py, .xp/system.md (new)")
        assert r.returncode == 0, r.stderr

    def test_BOTH_decorations_at_once_name_the_path_they_spell(self, tmp_path):
        """`_bare` strips twice for exactly this: one pass leaves the backtick that
        `(new)` sat outside of. Each decoration alone survives a single pass, so
        without this case the second one is unpinned."""
        r = self.accepts(tmp_path, "`src.py`, `.xp/system.md` (new)")
        assert r.returncode == 0, r.stderr

    def test_NEW_inside_backticks_names_the_path_it_spells(self, tmp_path):
        r = self.accepts(tmp_path, "`src.py`, `.xp/system.md (new)`")
        assert r.returncode == 0, r.stderr

    def test_a_comma_inside_an_annotation_never_splits_away_its_path(self):
        card = "Files: a.py, infra/compose.yml (compose, not the chart), b.py"
        paths = declared_files(card)
        assert paths == {"a.py", "infra/compose.yml", "b.py"}
        assert not any(set(path) & set("()[]{}") for path in paths)

    def test_an_implausible_entry_refuses_before_patch_apply_and_its_repair_is_walked(
        self, tmp_path
    ):
        bad = tmp_path / "bad"
        repo, env, g = make_repo(bad, plan=declaring(".xp/system.md [bootstrap rationale]"))
        staged_stub(
            bad,
            find=CANDIDATES,
            verify=SURVIVES,
            patches=[("fix", ".xp/system.md", "boot: x")],
        )
        refused = sprint(repo, env, "review")
        assert refused.returncode == 2, refused.stdout
        assert ".xp/system.md [bootstrap rationale]" in refused.stderr, refused.stderr
        assert "bare comma-separated paths" in refused.stderr, refused.stderr
        assert "card body" in refused.stderr, refused.stderr
        assert "Traceback" not in refused.stderr
        assert "boot: x" not in (repo / ".xp" / "system.md").read_text()
        assert not g("status", "--porcelain").stdout
        assert json.loads(marker_path(bad).read_text())["rounds"][-1]["incomplete"]

        repaired = tmp_path / "repaired"
        plan = declaring(".xp/system.md").replace(
            "Files: .xp/system.md", "Context: bootstrap rationale\nFiles: .xp/system.md"
        )
        repo, env, _g = make_repo(repaired, plan=plan)
        staged_stub(
            repaired,
            find=CANDIDATES,
            verify=SURVIVES,
            patches=[("fix", ".xp/system.md", "boot: x")],
        )
        accepted = sprint(repo, env, "review")
        assert accepted.returncode == 0, accepted.stderr
        assert "boot: x" in (repo / ".xp" / "system.md").read_text()

    def test_the_shipped_template_states_and_walks_the_Files_contract(self):
        template = (PLUGIN / "templates" / "plan.md").read_text()
        contract = template.lower()
        assert "comma-separated bare paths" in contract
        assert "(new)" in contract and "allowed" in contract
        assert "no other parentheticals" in contract
        assert "rationale" in contract and "card body" in contract
        # The template AS SHIPPED, never a substituted line: its own example is the
        # one card every consuming project starts from, and the placeholder it
        # replaced (`<the files it will touch>`) does not parse.
        assert declared_files(template) == {"path/to/file.py", "path/to/new.py"}
        assert "the files it will touch" not in template

    def test_an_undeclared_path_is_still_refused_when_others_are_decorated(self, tmp_path):
        """Normalising must not turn the guard off — the inverse of the two above,
        because a strip that ate too much would green every case in this class."""
        r = self.accepts(tmp_path, "`src.py`, `.xp/constraints.md` (new)")
        assert r.returncode == 2, r.stdout
        assert ".xp/system.md" in r.stderr and "Files line" in r.stderr, r.stderr
