import importlib.util
from pathlib import Path

SRC = (
    Path(__file__).parent.parent
    / "plugins"
    / "xp-plugin"
    / "scripts"
    / "close"
    / "sprint_bundle.py"
)
SPEC = importlib.util.spec_from_file_location("test_sprint_bundle_module", SRC)
SPRINT_BUNDLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SPRINT_BUNDLE)


def test_record_files_use_the_shared_parser():
    record = "Files: a.py, infra/compose.yml (compose, not the chart), `b.py`\n"

    paths = SPRINT_BUNDLE._declared_files(record)

    assert paths == ["a.py", "infra/compose.yml", "b.py"]
    assert not any(set(path) & set("`()[]{}") for path in paths)


def test_unknown_remains_an_unresolved_files_declaration():
    assert SPRINT_BUNDLE._declared_files("Files: unknown\n") == []


def test_an_implausible_record_entry_returns_an_actionable_refusal(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "work.md").write_text(
        "## debt 2026-09-07T00:00:00Z\n"
        "Id: bad00bad\n"
        "Claim: malformed declaration\n"
        "Files: a.py, src.py [rationale]\n\n"
    )

    paths, missing, error = SPRINT_BUNDLE.source_files(root, ["bad00bad"])

    assert paths == []
    assert missing == []
    assert "bad00bad" in error
    assert "src.py [rationale]" in error
    assert "bare comma-separated paths" in error


def test_an_archived_record_reads_its_own_files_line_not_its_resolutions(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "archive.md").write_text(
        "# Record abc01234\n"
        "## debt 2026-09-01T00:00:00Z\n"
        "Claim: archived source\n"
        "Files: plugins/xp-plugin/scripts/close.py\n\n"
        "## resolved 2026-09-02T00:00:00Z\n"
        "Resolves: abc01234\n"
        "Files: unknown\n\n"
    )

    paths, missing, error = SPRINT_BUNDLE.source_files(root, ["abc01234"])

    assert paths == ["plugins/xp-plugin/scripts/close.py"]
    assert missing == []
    assert error == ""
