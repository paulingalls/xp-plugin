from sprint_helpers import PLUGIN

ANGLES = PLUGIN / "scripts" / "angles"

CANDIDATES = {
    "fixed": [],
    "blocking": ["a silent one"],
    "schema": 2,
    "dropped": [{"finding": item, "reason": "fixture reason"} for item in ["a loud one"]],
    "debt": [],
}

SURVIVES = {"fixed": [], "blocking": ["a silent one"], "schema": 2, "dropped": [], "debt": []}

# A refusing commit gate framed the way lefthook frames one: the cause is the LAST
# line, behind escape codes. Constructed, never observed.
LEFTHOOK = [
    "\\033[1m\\033[38;2;0;0;0m│ lefthook │\\033[0m",
    "summary: (done)",
    "\\033[31mformat: src.py would be reformatted\\033[0m",
]


def angle_names():
    return sorted(p.stem for p in ANGLES.glob("*.md"))
