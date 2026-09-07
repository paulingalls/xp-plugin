"""Shipped coverage guidance stays independent of project test runners."""

from pathlib import Path


def test_shipped_coverage_guidance_names_no_test_runner_or_selection_syntax():
    plugin = Path(__file__).parent.parent / "plugins/xp-plugin"
    # Every file rather than a suffix whitelist: the two githooks-* templates carry
    # no extension, and a shell hook is exactly where a runner name would land.
    shipped = {
        path: path.read_text(errors="replace")
        for path in plugin.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert len(shipped) > 40, "scanned nothing — a green here would certify (constraint 2)"
    forbidden = ("pytest", "py.test", "bun test", "unittest", "node id", "::")
    named = [
        f"{path.relative_to(plugin)} names {term!r}"
        for path, text in shipped.items()
        for term in forbidden
        if term in text.lower()
    ]
    assert not named, named
