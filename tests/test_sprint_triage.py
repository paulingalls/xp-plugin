import subprocess
from pathlib import Path

import pytest
import xp
from test_land import commit, git, make_project
from xpcore import config, launch


@pytest.mark.parametrize(
    "answer",
    [
        None,
        "CLEAR\nOutside security: display copy only.\n",
        "ESCALATE\nsite.py:1 — user input reaches storage\n",
        "",
        " CLEAR\nreason",
        "CLEAR ",
        "CLEAR because\nreason",
        "clear\nreason",
        "\nCLEAR\nreason",
    ],
)
def test_sprint_security_triage(tmp_path, monkeypatch, capsys, answer):
    seats = "  angle-triage: claude/haiku\n" if answer is not None else ""
    root, data = make_project(
        tmp_path,
        monkeypatch,
        config="trunk: main\nroles:\n  reviewer: codex/astra\n  executor: codex/astra\n" + seats,
    )
    slate = "## Sprint 1 — triage\n\n#### story-001 — seam   [done]\nAcceptance: true\n"
    (data / "plan.md").write_text(slate)
    git(root, "switch", "-qc", "sprint-1")
    commit(root, {"site.py": "input()\n", "omitted.py": "print(1)\n"}, "two sites")
    folder = data / "sprints" / "1"
    folder.mkdir(parents=True)
    triage_path = folder / "triage-1.security.md"
    if answer is not None:
        triage_path.write_text("CLEAR\nstale decision\n")
    calls = []

    def run_agent(role, prompt, cwd, log_id):
        seat = config.role(role)
        output_key = "HANDBACK_PATH" if role == "fixer" else "FINDINGS_PATH"
        output = Path(
            next(
                line.split(": ", 1)[1]
                for line in prompt.splitlines()
                if line.startswith(f"- {output_key}: ")
            )
        )
        calls.append((role, log_id, prompt, output, seat))
        assert cwd == root and slate.strip() in prompt
        if role == "angle-triage":
            assert not output.exists()
            assert output == triage_path
            assert "site.py" in prompt and "omitted.py" in prompt
            assert seat == ("claude", "haiku", "")
            result = answer
        else:
            assert seat == ("codex", "astra", "")
            if log_id.endswith("-security") and answer is not None:
                assert any(c[0] == "angle-triage" for c in calls[:-1])
                assert triage_path.read_text() == answer + ("" if answer.endswith("\n") else "\n")
                assert f"Triage sites\n{answer}" in prompt
                assert "site.py" in prompt and "omitted.py" in prompt
            elif role == "angle-reviewer":
                assert "## Triage sites\n" not in prompt
            result = f"finding from {log_id}\n"
        return subprocess.CompletedProcess([], 0, result, "")

    monkeypatch.setattr(launch, "run_agent", run_agent)
    assert xp.main(["sprint", "review", "1"]) == 0
    angles = sorted(p.stem for p in (config.plugin_root() / "angles").glob("*.md"))
    clear = answer is not None and answer.split("\n")[0] == "CLEAR"
    reviewers = [c for c in calls if c[0] == "angle-reviewer"]
    assert {c[1] for c in reviewers} == {
        f"sprint-1-reviewer-1-{a}" for a in angles if a != "security" or not clear
    }
    triages = [c for c in calls if c[0] == "angle-triage"]
    assert [c[1] for c in triages] == ([] if answer is None else ["sprint-1-triage-1-security"])
    assert triage_path.exists() == (answer is not None and not clear)
    written = sorted(folder.glob("review-1.*.md"))
    assert [p.name for p in written] == [f"review-1.{a}.md" for a in angles]
    assert len(calls) == len(reviewers) + len(triages) + 1
    role, log_id, prompt, output, _ = calls[-1]
    assert role == "fixer" and log_id == "sprint-1-fixer-1"
    assert output == folder / "handback-1.md"
    for path in written:
        expected = (
            answer
            if clear and path.stem.endswith(".security")
            else (f"finding from sprint-1-reviewer-1-{path.stem.split('.')[1]}\n")
        )
        assert path.read_text() == expected
        assert path.name in prompt and expected in prompt
    report = capsys.readouterr().out
    assert all(str(p) in report for p in written) and str(output) in report
