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
