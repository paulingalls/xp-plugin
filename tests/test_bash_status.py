"""Bash-outcome hook behavior, split from the Stop gate suite."""

import os
import pty
import subprocess
import sys

from test_stop_gate import (
    SCRIPTS,
    failure_payload,
    markers,
    repo_with_story,
    run_script,
    success_payload,
)


class TestBashStatus:
    def test_malformed_payload_is_advisory_but_visible(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "bash_status.py")],
            input="not json",
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(tmp_path / "xp")},
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0 and result.stdout == ""
        assert "JSONDecodeError" in result.stderr

    def test_failure_event_records_red_then_success_greens(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script(
            "bash_status.py",
            failure_payload("cd x && pytest -q tests/test_x.py"),
            repo,
            tmp_path,
        )
        assert [m["red"] for m in markers(tmp_path)] == [True]
        run_script("bash_status.py", success_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        assert [m["red"] for m in markers(tmp_path)] == [False]

    def test_non_verify_failure_writes_nothing(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", failure_payload("pytest -q tests/other.py"), repo, tmp_path)
        assert markers(tmp_path) == []

    def test_non_exit_failure_writes_nothing(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        payload = failure_payload("pytest -q tests/test_x.py", error="Permission denied by user")
        run_script("bash_status.py", payload, repo, tmp_path)
        assert markers(tmp_path) == []

    def test_mention_in_exit_zero_command_does_not_green(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        mention = success_payload("git commit -m 'red: pytest -q tests/test_x.py still failing'")
        run_script("bash_status.py", mention, repo, tmp_path)
        assert [m["red"] for m in markers(tmp_path)] == [True]  # mention is not invocation

    def test_success_masking_never_greens_a_red(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        for masked in (
            "pytest -q tests/test_x.py 2>&1 | tail -5",
            "pytest -q tests/test_x.py; echo done",
            "pytest -q tests/test_x.py || true",
            "pytest -q tests/test_x.py::test_one",
        ):
            run_script("bash_status.py", success_payload(masked), repo, tmp_path)
            assert [m["red"] for m in markers(tmp_path)] == [True], f"greened by: {masked}"

    def test_exact_verify_with_and_chain_greens(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        run_script(
            "bash_status.py",
            success_payload("pytest -q tests/test_x.py && git push"),
            repo,
            tmp_path,
        )
        assert [m["red"] for m in markers(tmp_path)] == [False]

    def test_multiline_command_failure_records_red(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        payload = failure_payload("cd sub\npytest -q tests/test_x.py")
        run_script("bash_status.py", payload, repo, tmp_path)
        assert [m["red"] for m in markers(tmp_path)] == [True]

    def test_matches_each_in_progress_story(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        plan = tmp_path / "xp" / "plan.md"
        plan.write_text(
            plan.read_text() + "#### story-043 — other   [in-progress]\nVerify: bun test x\n"
        )
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        run_script("bash_status.py", success_payload("bun test x"), repo, tmp_path)
        # two markers, per constraint 10: B's green cannot hide A's red
        assert sorted(m["red"] for m in markers(tmp_path)) == [False, True]

    def test_a_pipe_keeps_the_existing_empty_output_contract(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        result = run_script("bash_status.py", failure_payload("true"), repo, tmp_path)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")

    def test_a_tty_names_the_hook_and_its_json_input(self):
        master, slave = pty.openpty()
        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "bash_status.py")],
                stdin=slave,
                capture_output=True,
                text=True,
                timeout=1,
            )
        finally:
            os.close(master)
            os.close(slave)
        assert result.returncode == 0
        assert all(word in result.stdout for word in ("bash_status.py", "JSON", "stdin"))
