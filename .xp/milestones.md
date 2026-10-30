# Milestones

## Leads keep their eyes on the prize
Goal: "When the smaller things run into trouble, pop your head up, look at the goal, and
decide: take another tack, delete and try something different, or ask for help." (#200)
Measure: python3 -c 'import re; from pathlib import Path; xp=[p.parent for p in Path("..").glob("*/.xp") if p.parent.resolve()!=Path.cwd().resolve()]; left=[p.name for p in xp if not re.search(r"^Measure: *[^<\s]", (p/".xp/milestones.md").read_text() if (p/".xp/milestones.md").is_file() else "", re.M)]; print(f"distance={len(left)} of {len(xp)} sibling projects without a Measure: {chr(32).join(sorted(left))}")'
Candidates: once consumers carry Measures, measure stalls reported before a third flat land (the legacy replay in sprint eyes-on-the-prize found 10-16).
