"""Profile accounting for teammate prompts."""

from pathlib import Path
from typing import Callable

DEFAULT_PROFILE_TARGET = 806


def component_metadata_chars(plugin_root: Path) -> int:
    """Count always-loaded skill and agent frontmatter, excluding lazy-loaded bodies."""
    total = 0
    paths = sorted(plugin_root.glob("skills/*/SKILL.md")) + sorted(plugin_root.glob("agents/*.md"))
    for path in paths:
        parts = path.read_text().split("---", 2)
        if len(parts) > 2:
            total += len(parts[1])
    return total


def profile_target(config_has: Callable[[str], bool], config_flat: Callable[[str], str]) -> int:
    if not config_has("profile_target"):
        return DEFAULT_PROFILE_TARGET
    raw = config_flat("profile_target")
    if raw.isdecimal():
        return int(raw)
    received = "empty" if not raw else repr(raw)
    raise ValueError(
        f"profile_target in .xp/config.yml is {received}; expected a non-negative integer"
        " number of story-card tokens"
    )


def profile_report(
    card: str,
    prompt: str,
    handoff: str,
    plugin_root: Path,
    read: Callable[[Path], str],
    target: int,
) -> tuple[str, str]:
    project = {
        "the story card": len(card),
        "constraints.md": len(read(Path(".xp/constraints.md"))),
        "CLAUDE.md": len(read(Path("CLAUDE.md"))),
    }
    if handoff:
        project["predecessor handoff"] = len(handoff)
    total_chars = len(prompt) + project["CLAUDE.md"] + component_metadata_chars(plugin_root)
    total = total_chars // 4
    plugin = total_chars - sum(project.values())
    shares = " · ".join(f"{key} {value // 4}" for key, value in project.items())
    line = f"profile: total {total} tokens · plugin share {plugin // 4}/{total} · {shares}"
    card_tokens = len(card) // 4
    if card_tokens <= target:
        return line, ""
    return line, (
        f"note: story card is {card_tokens} tokens, over the {target} story-card token"
        " allowance (profile_target). Shorten the story card or raise that configured allowance."
    )
