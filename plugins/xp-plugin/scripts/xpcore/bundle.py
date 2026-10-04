"""One agent's prompt: the values, its charter, the project's rules, and the inputs it judges."""

import re
from pathlib import Path

from xpcore import config

# Harness metadata for interactive use; a headless agent reads only the instructions.
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)


def _read(path: Path) -> str:
    return path.read_text().strip() if path.is_file() else ""


def charter(role: str) -> str:
    path = config.plugin_root() / "agents" / f"{role}.md"
    if not path.is_file():
        config.refuse(f"no charter {path} for role {role}; reinstall the plugin")
    return FRONTMATTER.sub("", path.read_text()).strip()


def prompt(
    role: str,
    *,
    card=None,
    slate: str = "",
    plan: str = "",
    findings: str = "",
    angle: str = "",
    extra: str = "",
    paths: dict[str, str] | None = None,
) -> str:
    """`card` is a cards.Card or its text; `slate` is a sprint's section of plan.md. `paths`
    names such as PLAN_PATH, FINDINGS_PATH, HANDBACK_PATH, CARD_ID are listed for the agent;
    DATA is always among them."""
    root, project = config.plugin_root(), config.repo_root() / ".xp"
    body, named = charter(role), {"DATA": str(config.data_root()), **(paths or {})}
    parts = (
        ("Values", _read(root / "VALUES.md")),
        ("Judgment", _read(root / "JUDGMENT.md")),
        (f"Your charter: {role}", body),
        ("Project constraints (.xp/constraints.md)", _read(project / "constraints.md")),
        ("Project system (.xp/system.md)", _read(project / "system.md")),
        ("Card", str(getattr(card, "text", card or "")).strip()),
        ("Slate", slate.strip()),
        ("Plan", plan.strip()),
        ("Findings", findings.strip()),
        ("Angle", angle.strip()),
        ("Context", extra.strip()),
        ("Paths (<data> is DATA)", "\n".join(f"- {k}: {v}" for k, v in named.items())),
    )
    return "\n\n".join(f"===== {title} =====\n{text}" for title, text in parts if text) + "\n"
