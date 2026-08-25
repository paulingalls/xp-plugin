"""story-012b: the reviewer fixes; the lead reads its diff.
Split from test_close.py at sprint-004 open."""

import subprocess
import sys

from close_helpers import (  # noqa: F401
    CARD,
    CLEAN,
    CLOSE,
    CONFIG,
    CONSTRAINTS_PATCH,
    FIX_PATCH,
    PLUGIN,
    RENAME_OUT_PATCH,
    REVIEWER_EMAIL,
    REVIEWER_NAME,
    WORK,
    XP_PATCH,
    close,
    close_bare,
    launches,
    make_repo,
    marker,
    marker_file,
    prose,
    stub_reviewer,
)


class TestFixingReviewer:
    """story-012b: the reviewer fixes; the lead reads its diff."""

    def fixing_stub(self, tmp_path, extra="", patch=FIX_PATCH):
        """A read-only reviewer that proposes its fix beside the report."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "claude").write_text(
            "#!/bin/sh\n"
            "input=$(cat)\n"
            "p=$(printf '%s' \"$input\" | sed -n 's/^REPORT_PATH: //p')\n"
            "q=$(printf '%s' \"$input\" | sed -n 's/^PATCH_PATH: //p')\n"
            'printf \'{"fixed": ["tightened the guard"], "blocking": [], "noted": []}\' > "$p"\n'
            f"printf '%s' '{patch}' > \"$q\"\n"
            f"{extra}"
            'printf \'{"type": "result", "result": "fixed one thing"}\'\n'
        )
        (bin_dir / "claude").chmod(0o755)
        return bin_dir

    def test_the_script_applies_and_commits_the_reviewers_patch(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        pre = g("rev-parse", "HEAD").stdout.strip()
        self.fixing_stub(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        m = marker(tmp_path)
        assert m["reviewed_head"] == pre, "the sha the reviewer was SHOWN"
        assert m["shown_sha"] == g("rev-parse", "HEAD").stdout.strip(), "what the LEAD sees"
        assert m["shown_sha"] != m["reviewed_head"]
        assert g("show", "--format=", "--name-only", "HEAD").stdout.strip() == "src/thing.py"

    def test_a_commit_made_while_the_reviewer_held_the_tree_is_refused(self, tmp_path):
        """AC 2, job B of the deleted guard. A lead commit made while the reviewer
        held the tree is otherwise absorbed into shown_sha, land's HEAD==shown_sha
        holds by construction, and it merges having been read by nobody. No `env -u`
        any more: the launch carries no GIT_AUTHOR_* to out-rank `-c user.name`."""
        repo, env, _g = make_repo(tmp_path)
        self.fixing_stub(
            tmp_path,
            extra=(
                "echo 'lead = 1' >> src/other.py\n"
                "git add -A\n"
                "git -c user.name=t -c user.email=t@t"
                " commit -qm 'lead worked in parallel'\n"
            ),
        )
        r = close(repo, env, "review")
        assert r.returncode == 2, "an unreviewed lead commit was absorbed into shown_sha"
        assert "read-only reviewer changed HEAD" in r.stderr
        assert not marker_file(tmp_path).exists()

    def test_the_reviewer_commits_under_its_own_git_identity(self, tmp_path):
        """AC 3, asserted on the ARTIFACT: an env assertion passes against a
        harness that strips it, and AC 2 makes this identity load-bearing."""
        repo, env, g = make_repo(tmp_path)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "claude").write_text(
            "#!/bin/sh\n"
            "input=$(cat)\n"
            "p=$(printf '%s' \"$input\" | sed -n 's/^REPORT_PATH: //p')\n"
            "q=$(printf '%s' \"$input\" | sed -n 's/^PATCH_PATH: //p')\n"
            'printf \'{"fixed": ["f"], "blocking": [], "noted": []}\' > "$p"\n'
            f"printf '%s' '{FIX_PATCH}' > \"$q\"\n"
            'printf \'{"type": "result", "result": "fixed"}\'\n'
        )
        (bin_dir / "claude").chmod(0o755)
        assert close(repo, env, "review").returncode == 0
        who = g("log", "-1", "--format=%an <%ae>").stdout.strip()
        # POSITIVE and whole: `"t <t@t>" not in who` passed with EMAIL dropped and
        # NAME kept, so the half of AC 3 that says "EMAIL too" was unguarded.
        assert who == f"{REVIEWER_NAME} <{REVIEWER_EMAIL}>", who

    def test_an_inapplicable_patch_prints_findings_then_refuses_cleanly(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        before = g("rev-parse", "HEAD").stdout.strip()
        stub_reviewer(tmp_path, result="FINDINGS-SURVIVE", patch=FIX_PATCH.replace("A = 2", "NOPE"))
        r = close(repo, env, "review")
        assert r.returncode == 2 and "FINDINGS-SURVIVE" in r.stdout
        assert "does not apply cleanly" in r.stderr
        assert g("rev-parse", "HEAD").stdout.strip() == before
        assert g("status", "--porcelain").stdout == ""

    def test_review_writes_the_reviewer_diff_to_a_file_and_prints_its_path(self, tmp_path):
        """AC 4: review's stdout is the channel this session lost three times, so
        the artifact the lead's assent rests on must not live only there."""
        repo, env, _g = make_repo(tmp_path)
        self.fixing_stub(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        diffs = list((tmp_path / "data" / "reports").glob("*.diff"))
        assert diffs, "no diff artifact written"
        body = diffs[0].read_text()
        assert "x = 1" in body and "src/thing.py" in body
        assert str(diffs[0]) in r.stdout, "the path was not printed"

    def test_land_prints_the_reviewer_range_before_merging(self, tmp_path):
        """AC 4 second half: assent must be readable at the moment it is given."""
        repo, env, _g = make_repo(tmp_path)
        self.fixing_stub(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "reviewer fix" in r.stdout or "src/thing.py" in r.stdout

    def test_a_reviewer_that_touches_the_marker_is_refused(self, tmp_path):
        """AC 6: the marker gates the merge, lives OUTSIDE the repo, and no diff
        shows it — the reviewer's Bash can empty its own blocking[]."""
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report={"fixed": [], "blocking": ["B1: real"], "noted": []})
        assert close(repo, env, "review").returncode == 0
        mf = marker_file(tmp_path)
        bin_dir = tmp_path / "bin"
        (bin_dir / "claude").write_text(
            "#!/bin/sh\n"
            "p=$(sed -n 's/^REPORT_PATH: //p')\n"
            'printf \'{"fixed": [], "blocking": [], "noted": []}\' > "$p"\n'
            f"python3 -c \"import json;f='{mf}';d=json.load(open(f));"
            "d['rounds'][0]['blocking']=[];json.dump(d,open(f,'w'))\"\n"
            'printf \'{"type": "result", "result": "clean"}\'\n'
        )
        (bin_dir / "claude").chmod(0o755)
        r = close(repo, env, "review")
        assert r.returncode == 2, "the reviewer rewrote the file that gates its own merge"
        assert "marker" in r.stderr.lower()

    def test_a_patch_that_RENAMES_a_gate_file_out_of_xp_is_refused(self, tmp_path):
        """`git apply --numstat` names a rename's DESTINATION only, so scoping on it
        let a patch delete .xp/constraints.md by moving it out. Fault-injected."""
        repo, env, g = make_repo(tmp_path)
        self.fixing_stub(tmp_path, patch=RENAME_OUT_PATCH)
        r = close(repo, env, "review")
        assert r.returncode == 2 and ".xp/constraints.md" in r.stderr, r.stderr
        assert (repo / ".xp" / "constraints.md").exists(), "the gate file was deleted"
        assert g("status", "--porcelain").stdout == "", "a refused patch stayed staged"

    def test_a_reviewer_that_touches_xp_is_refused(self, tmp_path):
        """AC 6: it may fix code, never the plan."""
        repo, env, _g = make_repo(tmp_path)
        self.fixing_stub(tmp_path, patch=CONSTRAINTS_PATCH)
        r = close(repo, env, "review")
        assert r.returncode == 2 and ".xp/constraints.md" in r.stderr
        assert "Files line" in r.stderr, "refused for applicability, not for scope"

    def test_a_reviewer_that_rewrites_its_OWN_card_is_refused(self, tmp_path):
        """story-019: the plan left the repo, so `git diff` stopped covering it and
        the guard above cannot see this at all. The digest is what remains."""
        repo, env, _g = make_repo(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        self.fixing_stub(
            tmp_path,
            extra=f"printf 'sneaky\\n' >> '{plan}'\n",
        )
        r = close(repo, env, "review")
        assert r.returncode == 2, "a fixing reviewer rewrote the card it is reviewed under"
        assert "plan" in r.stderr.lower()

    def test_a_reviewer_is_NOT_blamed_for_another_lanes_card(self, tmp_path):
        """The green twin, and the reason the digest is scoped to the story's own
        card: the plan is shared per-clone now, so a whole-file digest would let
        lane B's spawn flip refuse lane A's review — the project-global mutable
        gate constraint 10 forbids, blaming the reviewer for another actor's write."""
        repo, env, _g = make_repo(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        self.fixing_stub(
            tmp_path,
            extra=(
                f"printf '#### story-777 — another lane   [in-progress]\\nVerify: true\\n'"
                f" >> '{plan}'\n"
            ),
        )
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr + r.stdout

    def _worktree_land_setup(self, tmp_path, verify="true"):
        """spawn.py's DEFAULT arrangement: the lead's tree holds the integration
        target, the story branch lives in a worktree. Returns (repo, env, g,
        tree, branch). `verify` is set BEFORE the review — editing the card after
        it moves HEAD past the reviewed head and the coverage guard refuses."""
        repo, env, g = make_repo(tmp_path, verify=verify)
        self.fixing_stub(tmp_path)
        assert close(repo, env, "review").returncode == 0
        tree = tmp_path / "wt"
        branch = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        g("checkout", "-q", "main")
        g("worktree", "add", str(tree), branch)
        return repo, env, g, tree, branch

    def test_land_from_a_worktree_merges_and_removes_the_worktree(self, tmp_path):
        """37c0fb4e. Replaces test_land_from_a_worktree_does_not_traceback, which
        asserted `returncode in (0, 2)` and was green under the bug AND the fix.
        MEASURED: `git merge --no-ff` into trunk succeeds while the story branch
        is checked out in a worktree, so landing never needed a teardown first —
        only `git branch -d` does."""
        repo, env, _g, tree, branch = self._worktree_land_setup(tmp_path)
        r = close(tree, env, "land", "--merge-mode", "local")
        assert "Traceback" not in r.stderr, r.stderr
        assert "refused" not in r.stderr, r.stderr
        assert r.returncode == 0, r.stderr
        assert not tree.exists(), "the worktree survived a completed land"
        head = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"], cwd=repo, env=env, capture_output=True, text=True
        ).stdout
        assert branch in head, head
        assert "[done]" in (tmp_path / "data" / "plan.md").read_text()

    def test_a_dirty_tree_holding_trunk_is_refused_before_verify_runs(self, tmp_path):
        """5d7388fc — the ORDERING claim, re-pointed. Its filed falsifier named
        the trunk-held refusal, which the fix above deletes; the property that
        survives is that a structural precondition costing milliseconds is
        checked before ~2 minutes of tests. The sentinel is what discriminates:
        move this guard back below Verify and the sentinel appears."""
        sentinel = tmp_path / "verify-ran"
        repo, env, _g, tree, _b = self._worktree_land_setup(tmp_path, verify=f"touch {sentinel}")
        (repo / "dirt.txt").write_text("uncommitted\n")
        r = close(tree, env, "land", "--merge-mode", "local")
        assert r.returncode == 2 and "dirty" in r.stderr, r.stderr
        assert not sentinel.exists(), "ran the tests before a milliseconds-cheap precondition"
        assert tree.exists(), "a refusal tore down the worktree"

    def test_a_completed_land_runs_verify(self, tmp_path):
        """Sentinel ABSENCE alone also passes an implementation that deleted
        Verify, so the happy path pins its presence (story-014's AC 6 shape)."""
        sentinel = tmp_path / "verify-ran"
        _repo, env, _g, tree, _b = self._worktree_land_setup(tmp_path, verify=f"touch {sentinel}")
        assert close(tree, env, "land", "--merge-mode", "local").returncode == 0
        assert sentinel.exists()

    def test_pr_mode_runs_gh_from_the_STORY_tree(self, tmp_path):
        """`gh pr create` and `gh pr merge` take no --head: gh derives the head
        branch from the CURRENT BRANCH of the cwd repo. The land fix hoisted
        os.chdir(held) above both merge arms on a plan review's advice, which put
        gh in the tree holding trunk — so it would infer `main` and refuse.

        THIS IS THE OUT-OF-THE-BOX PATH: templates/config.yml leaves sprint_branch
        commented, so integration_target() == default_branch() and close.py:489
        derives pr mode; spawn's default puts trunk in the lead's tree, so `held`
        is set. Every consuming project's first land. Untested because every
        worktree test here passes --merge-mode local and every pr test runs from
        the non-worktree repo."""
        _repo, env, g, tree, branch = self._worktree_land_setup(tmp_path)
        bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], env=env, check=True)
        g("remote", "add", "origin", str(bare))
        gh = tmp_path / "ghbin"
        gh.mkdir()
        (gh / "gh").write_text(
            "#!/bin/sh\n"
            f'echo "$(git rev-parse --abbrev-ref HEAD)" >> {tmp_path}/gh-branches\n'
            "exit 0\n"
        )
        (gh / "gh").chmod(0o755)
        env = {**env, "PATH": f"{gh}:{env['PATH']}"}
        r = subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "pr"],
            cwd=tree,
            env=env,
            capture_output=True,
            text=True,
        )
        log = tmp_path / "gh-branches"
        seen = log.read_text().split() if log.exists() else []
        assert seen, f"gh was never invoked: rc={r.returncode} {r.stderr[:300]}"
        assert all(b == branch for b in seen), (
            f"gh ran on {seen} but the story branch is {branch} — it would infer the"
            " wrong head and refuse"
        )

    def test_land_from_the_tree_holding_trunk_removes_no_worktree(self, tmp_path):
        """Without this the fix can pass by only ever handling the worktree case.
        'Unchanged' spelled out: the merge lands in cwd, the card flips, and the
        unrelated worktree is still standing."""
        repo, env, g = make_repo(tmp_path)
        self.fixing_stub(tmp_path)
        assert close(repo, env, "review").returncode == 0
        bystander = tmp_path / "other-wt"
        g("worktree", "add", "-b", "unrelated", str(bystander), "main")
        assert close(repo, env, "land", "--merge-mode", "local").returncode == 0
        assert "[done]" in (tmp_path / "data" / "plan.md").read_text()
        assert bystander.exists(), "land removed a worktree it does not own"

    def test_a_refused_land_leaves_the_worktree_standing(self, tmp_path):
        """Every refusal names a next action the lead takes IN the story tree, so
        no refusal may tear it down first. The OVERLAP refusal is the one that lands
        closest to the merge. f7dfec27, re-measured under story-018's rule: the real
        merge's conflict abort is still shielded, because a content conflict is a
        same-file property and this refusal fires on that same property first — but
        the TRIAL merge's is reachable, since rename-vs-modify conflicts on file
        names the overlap set does not pair up."""
        repo, env, g, tree, _b = self._worktree_land_setup(tmp_path)
        g("checkout", "-q", "main")
        (repo / "src" / "thing.py").write_text("A = 99\n")
        g("commit", "-qam", "trunk moves after the review")
        r = close(tree, env, "land", "--merge-mode", "local")
        assert r.returncode == 2 and "src/thing.py" in r.stderr, r.stderr
        assert tree.exists(), "a refusal destroyed the tree its remediation names"
        on = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert on == "main", f"left the tree holding trunk on {on}"

    def test_dry_run_removes_no_worktree_and_leaves_the_branch(self, tmp_path):
        repo, env, _g, tree, branch = self._worktree_land_setup(tmp_path)
        assert close(tree, env, "land", "--merge-mode", "local", "--dry-run").returncode == 0
        assert tree.exists()
        assert (
            subprocess.run(
                ["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            ).returncode
            == 0
        )

    def test_a_reviewer_may_fix_an_xp_file_the_story_itself_edits(self, tmp_path):
        """The refusal message says "the plan or the rules"; the check was the whole
        directory. Measured at story-010, whose card names .xp/system.md in Files —
        deleting the budget numbers from it IS an AC — so the reviewer refining that
        same file wedged the story: no round recorded, nine fixes left ungated.

        THE FIXTURE NOW MATCHES THE DOCSTRING: its card previously named only
        src/thing.py, so this passed on the deny-list's hole rather than on the
        story declaring the file. Its pair below is what that hole allowed."""
        repo, env, _g = make_repo(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text().replace("Files: src/thing.py", "Files: src/thing.py, .xp/system.md")
        )
        self.fixing_stub(tmp_path, patch=XP_PATCH)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr

    def test_a_reviewer_may_fix_an_xp_file_declared_on_a_wrapped_Files_line(self, tmp_path):
        """Every real card wraps its Files list; the parse read one physical
        line, so a reviewer editing a file the card declares on a continuation
        line was refused and the round not recorded — story-010's symptom back
        again, and the single-line fixture above cannot see it (bug 8d0a74c6,
        spec corrected in note 7e20e96b)."""
        repo, env, _g = make_repo(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text().replace(
                "Files: src/thing.py\n", "Files: src/thing.py,\n.xp/system.md\n"
            )
        )
        self.fixing_stub(tmp_path, patch=XP_PATCH)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr

    def test_a_reviewer_may_NOT_edit_an_xp_file_the_card_never_named(self, tmp_path):
        """The deny-list was (plan.md, constraints.md, config.yml) — .xp/system.md
        was writable by the agent under review, and spawn.py EXECUTES its
        `Worktree bootstrap:` line through subprocess.run(shell=True). So the
        reviewer could write a command the next spawn runs, with a correctly
        signed commit, a clean tree, and the round recorded."""
        repo, env, _g = make_repo(tmp_path)
        self.fixing_stub(tmp_path, patch=XP_PATCH)
        r = close(repo, env, "review")
        assert r.returncode == 2, r.stdout
        assert ".xp/system.md" in r.stderr, r.stderr

    def test_an_abort_names_the_undo_for_the_reviewer_commits(self, tmp_path):
        """AC 8: "nothing was recorded" was written for a reviewer that could not
        write. The tree now holds commits from a process refused mid-fix."""
        repo, env, g = make_repo(tmp_path)
        pre = g("rev-parse", "HEAD").stdout.strip()
        self.fixing_stub(tmp_path, extra="echo 'uncommitted' >> src/thing.py\n")
        r = close(repo, env, "review")
        assert r.returncode == 2
        assert pre[:8] in r.stderr, "the undo point was not named"
        assert "reset --hard" in r.stderr

    def test_an_abort_before_the_motion_checks_still_names_the_undo(self, tmp_path):
        """AC 8 says ANY abort path. A reviewer that fixes, commits, and then
        writes no report is the likeliest of them, and it aborts UPSTREAM of
        check_reviewer_motion — so the message that owns the undo never runs."""
        repo, env, g = make_repo(tmp_path)
        pre = g("rev-parse", "HEAD").stdout.strip()
        stub = tmp_path / "bin" / "claude"
        stub.write_text(
            "#!/bin/sh\n"
            "echo 'x = 1' >> src/thing.py\n"
            f"git -c user.name='{REVIEWER_NAME}' -c user.email='r@xp' commit -qam 'fix'\n"
            'printf \'{"type": "result", "result": "fixed it, forgot the report"}\'\n'
        )
        stub.chmod(0o755)
        r = close(repo, env, "review")
        assert r.returncode == 2
        assert g("rev-parse", "HEAD").stdout.strip() != pre, "the commit is in the tree"
        assert pre[:8] in r.stderr and "reset --hard" in r.stderr

    def test_an_abort_that_changed_nothing_offers_no_undo(self, tmp_path):
        """The other half: a reset instruction for a tree nobody touched teaches
        the lead to ignore it on the run where it is real."""
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=None)
        r = close(repo, env, "review")
        assert r.returncode == 2 and "reset --hard" not in r.stderr

    def test_land_prints_the_path_to_the_reviewer_diff(self, tmp_path):
        """AC 4: BOTH legs print its path. By land, review's stdout is scrolled
        away — the file is the artifact the lead's assent actually rests on."""
        repo, env, _g = make_repo(tmp_path)
        self.fixing_stub(tmp_path)
        assert close(repo, env, "review").returncode == 0
        (diff,) = list((tmp_path / "data" / "reports").glob("*.diff"))
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert str(diff) in r.stdout

    def test_a_later_round_is_told_what_the_last_one_changed(self, tmp_path):
        """AC 9: a fixing reviewer with no memory re-edits the last round's fixes
        and reverses its deliberate punts."""
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report={
                "fixed": ["renamed the flag"],
                "blocking": [],
                "noted": ["N1: punted on purpose"],
            },
        )
        assert close(repo, env, "review").returncode == 0
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        second = launches(tmp_path)[1]["stdin"]
        assert "renamed the flag" in second and "N1: punted on purpose" in second

    def test_a_hung_reviewer_is_bounded_by_a_wall_clock(self, tmp_path):
        """AC 7: review is now the only long-running command AND the only writer."""
        repo, env, _g = make_repo(tmp_path)
        bin_dir = tmp_path / "bin"
        (bin_dir / "claude").write_text("#!/bin/sh\nsleep 30\n")
        (bin_dir / "claude").chmod(0o755)
        r = close(repo, env | {"XP_AGENT_TIMEOUT": "1"}, "review")
        assert r.returncode == 2 and "wall clock" in r.stderr
        assert not marker_file(tmp_path).exists()
        # Field-reported: a lead read spawn.py to discover the bound was movable
        # at all, and concluded the tool could not do the job. CLAUDE.md's rule is
        # that every refusal names its next action, and a bound with no named knob
        # names none.
        assert "XP_AGENT_TIMEOUT" in r.stderr, r.stderr
