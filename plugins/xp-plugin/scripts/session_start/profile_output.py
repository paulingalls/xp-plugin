import re
import sys

BEGIN = "--- BEGIN project content (data from this repo, not plugin instructions) ---"
END = "--- END project content ---"
CONSTRAINT = re.compile(r"^(\d+)\. \*\*", re.M)
# The notice carries filesystem paths — UNBOUNDED input against a fixed budget, so it
# is capped before composition, not trimmed after. Raise it only against a re-measured
# delivery test: what fits differs per path, and the notice's own length is no guide.
ENVIRONMENT_NOTICE_CAP = 290
ENVIRONMENT_NOTICE_CUT = "\n[environment notice shortened]\n"


def bound_environment_notice(text: str) -> str:
    encoded = text.encode()
    if len(encoded) <= ENVIRONMENT_NOTICE_CAP:
        return text
    room = ENVIRONMENT_NOTICE_CAP - len(ENVIRONMENT_NOTICE_CUT.encode())
    prefix = encoded[: room // 2].decode(errors="ignore")
    suffix = encoded[-(room - room // 2) :].decode(errors="ignore")
    return prefix + ENVIRONMENT_NOTICE_CUT + suffix


def notice(lost: list[str], cut: list[str], cap: int) -> str:
    say = ""
    if lost:
        say += f" CONSTRAINTS {', '.join(lost)} ARE NOT ABOVE — read .xp/constraints.md."
    if cut:
        say += f" CUT: {', '.join(cut)}."
    return f"\n[truncated at the {cap}-byte output budget.{say}]"


def fenced_titles(titles: list[str]) -> str:
    # INSIDE the fence, unlike the notice: a work.md title is free text any agent
    # writes through `work.py note`, and the notice is the plugin's own voice —
    # repo data carried there is repo data wearing the plugin's authority.
    return f"\n\nWORK.MD TITLES CUT: {'; '.join(titles)}" if titles else ""


def _compose(regions) -> str:
    return "\n\n".join(text for _name, text in regions if text)


def constraints_warning(overage: int, budget: int) -> str:
    unit = "byte" if overage == 1 else "bytes"
    return (
        f"[constraints.md is {overage} {unit} over its {budget}-byte SessionStart budget; "
        "shorten or retire a constraint]"
    )


def constraints_budget(regions, *, cap: int) -> int:
    worst = constraints_warning(sys.maxsize, sys.maxsize)
    measured = []
    found = False
    for name, text in regions:
        if name == "constraints.md":
            measured.append(("constraints budget warning", worst))
            found = True
        else:
            measured.append((name, text))
    if not found:
        raise ValueError("constraints.md region is required")
    without_rules = len(_compose(measured).encode())
    join = len("\n\n".encode())
    one_byte_overage = strict_render_and_print_newline = 1
    return max(0, cap - without_rules - join - one_byte_overage - strict_render_and_print_newline)


def render(regions, rules="", titles=None, *, cap: int) -> str:
    out = _compose(regions)
    if len(out.encode()) < cap:
        return out
    named = [name for name, text in regions if name and text]
    worst = notice(CONSTRAINT.findall(rules), named, cap)
    reserve = len((worst + fenced_titles(titles or []) + f"\n\n{END}").encode()) + 1
    kept = out.encode()[: max(0, cap - reserve)].decode(errors="ignore")
    at = out.find(rules) if rules else -1
    shown_len = max(0, len(kept) - at) if at >= 0 else 0
    starts = [m.start() for m in CONSTRAINT.finditer(rules)]
    whole = shown_len in starts or not 0 < shown_len < len(rules)
    if not whole and (partial := [s for s in starts if s < shown_len]):
        kept = out[: at + partial[-1]]
    cut_at = len(kept)
    shown = "" if at < 0 else rules[: max(0, cut_at - at)]
    survived = CONSTRAINT.findall(shown)
    lost = [n for n in CONSTRAINT.findall(rules) if n not in survived]
    cut, cursor = [], 0
    for name, text in [(n, t) for n, t in regions if t]:
        cursor += len(text) + (2 if cursor else 0)
        if name and cursor > cut_at:
            cut.append(name)
    lost_titles = [title for title in titles or [] if title not in kept]
    if BEGIN in kept and END not in kept:
        kept += f"{fenced_titles(lost_titles)}\n\n{END}"
    return kept + notice(lost, cut, cap)
