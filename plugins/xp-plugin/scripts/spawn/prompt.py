"""Build the executor prompt from shipped prose and the story card."""

from pathlib import Path

from close import fail
from handoff import draft_path
from work import data_root


def build_prompt(sections: list[tuple[str, str]]) -> str:
    return "\n".join(f"## {title}\n\n{body}\n" for title, body in sections)


def teammate_sections(
    card: str,
    story_id: str,
    handoff: str,
    plugin_root: Path,
    shipped_root: Path,
    brief: str | None = None,
    multifile: bool = True,
) -> list[tuple[str, str]]:
    brief = _read_shipped(shipped_root / "EXECUTOR.md") if brief is None else brief
    guidance = (
        "- **Use the reviewed plan.** The lead owns **slate review**. Spawn stages a planner\n"
        "  and **execution plan review** before multi-file work. Re-read the reviewed plan\n"
        "  at `{PLAN_PATH}` and route human-only questions to lead."
        if multifile
        else "- **Use the card.** The lead owns **slate review**. "
        "There is no execution plan by design;\n"
        "  the card is the authority. Route human-only questions to lead."
    )
    brief = brief.replace("{PLAN_GUIDANCE}", guidance)
    sections = [
        ("VALUES", _read_shipped(shipped_root / "VALUES.md")),
        ("JUDGMENT", _read_shipped(shipped_root / "JUDGMENT.md")),
        # the escalation command must be runnable: work.py is not on PATH, and
        # spawn inlines this as raw prompt text, so ${CLAUDE_PLUGIN_ROOT} would
        # arrive literal. A teammate hitting "command not found" guesses instead.
        (
            "How you work",
            brief.replace("{PLUGIN_ROOT}", str(plugin_root)).replace(
                "{PLAN_PATH}", str(draft_path(data_root(), story_id))
            ),
        ),
        ("Your story card", card),
        ("Constraints", _read(Path(".xp/constraints.md"))),
    ]
    if handoff:
        sections.append(("Predecessor handoff", handoff))
    return sections


def _read(path: Path) -> str:
    """Project-owned files: a consuming project may legitimately lack them."""
    return path.read_text() if path.exists() else f"(missing: {path})"


def _read_shipped(path: Path) -> str:
    """Plugin-owned prose: absence is a broken install, not a project variation.
    Soft-reading it hands the teammate "(missing: ...)" as its VALUES section."""
    if not path.exists():
        raise SystemExit(fail(f"refused: {path} is missing — the plugin install is broken"))
    return path.read_text()
