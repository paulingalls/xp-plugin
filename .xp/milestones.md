# Milestones

## Leads keep their eyes on the prize
Goal: "When the smaller things run into trouble, pop your head up, look at the goal, and
decide: take another tack, delete and try something different, or ask for help." (#200)
Measure: python3 -c 'import re; from pathlib import Path; xp=[p.parent for p in Path("..").glob("*/.xp") if p.parent.resolve()!=Path.cwd().resolve()]; left=[p.name for p in xp if not re.search(r"^Measure: *[^<\s]", (p/".xp/milestones.md").read_text() if (p/".xp/milestones.md").is_file() else "", re.M)]; print(f"distance={len(left)} of {len(xp)} sibling projects without a Measure: {chr(32).join(sorted(left))}")'
Candidates: once consumers carry Measures, measure stalls reported before a third flat land (the legacy replay in sprint eyes-on-the-prize found 10-16).

## Seats stop paying to re-read
Goal: "cutting seat token spend" (Paul, via legacy2-mini, 2026-11-04); first cause: agents
re-reading what their prompt already holds, or whole files where a search would do.
Measure: python3 tests/scripts/read_cost.py | tail -1
Candidates: long lead sessions; executor run length times growing context (legacy2-mini's
later causes).

## Clones share one work state
Goal: When several clones of one project work at once, on one machine or several, every clone's lead can see the same work state and act on it without anyone relaying text by hand. (#231)
Measure: python3 -c 'import hashlib,os,re,subprocess as s,sys; from pathlib import Path as P; sys.path.insert(0,"plugins/xp-plugin/scripts"); from xpcore.cards import publish_moves; on=[p.parent for p in P("..").glob("*/.xp") if p.parent.resolve()!=P.cwd().resolve() and re.search(r"(?m)^github_issues: *on\b",(p/"config.yml").read_text() if (p/"config.yml").is_file() else "")]; c=[s.run(["git","-C",str(r),"rev-parse","--path-format=absolute","--git-common-dir"],capture_output=True,text=True).stdout.strip() for r in on]; f=[P.home()/".xp/data"/hashlib.sha256(os.path.realpath(x).encode()).hexdigest()[:12]/"plan.md" for x in c if x]; t=[q.read_text() for q in f if q.is_file()]; n=sum(publish_moves(m[1],x) for x in t for m in re.finditer(r"(?m)^#### (\S+) .*\[planned\]",x)); print(f"distance={n} planned non-slate cards still local in {len(on)} sibling clones with github_issues on")'
Reading: 2026-11-27, project root: distance=13 planned non-slate cards still local in 5 sibling clones with github_issues on (legacy 7, legacy3 5, legacy2 1). Slate and in-progress cards stay local by design and are not counted; a published card leaves plan.md.
Candidates: the closing reads of Evidence cards; release-waiting state beyond a merged PR.

## Projects learn from their retros
Goal: "nothing really changes as a result, neither in the next session nor is there later
analysis done across multiple retros looking for patterns or anything to learn ... an
opportunity here for a project to improve itself" (Paul, 2026-11-25)
Measure: python3 -c 'exec("import re, subprocess as s, sys, tempfile\nfrom pathlib import Path as P\nprojects = {}\nfor xp in P(\"..\").glob(\"*/.xp\"):\n    root = xp.parent\n    config = xp/\"config.yml\"\n    if root.resolve() == P.cwd().resolve():\n        continue\n    url = s.run([\"git\", \"-C\", str(root), \"remote\", \"get-url\", \"origin\"], capture_output=True, text=True).stdout.strip()\n    match = re.search(r\"[:/]([^/:]+)/([^/]+?)(?:\\.git)?$\", url)\n    if not match:\n        continue\n    key = \"/\".join(match.groups()).lower()\n    on = bool(re.search(r\"(?m)^github_issues: *on\\b\", config.read_text() if config.is_file() else \"\"))\n    if key not in projects or on:\n        projects[key] = (url, on)\nmissing = stale = 0\nfor key, (url, on) in sorted(projects.items()):\n    with tempfile.TemporaryDirectory() as temp:\n        ledger = P.home()/\".xp/projects\"/key/\"lessons.md\"\n        if on:\n            wiki = re.sub(r\"(?:\\.git)?$\", \".wiki.git\", url, count=1)\n            clone = s.run([\"git\", \"clone\", \"--quiet\", \"--depth\", \"1\", wiki, temp], capture_output=True, text=True)\n            if clone.returncode:\n                print(f\"{key}: cannot read wiki\\n{clone.stderr.strip()}\", file=sys.stderr)\n                missing += 1\n                continue\n            ledger = P(temp)/\"Lessons.md\"\n        if not ledger.is_file():\n            missing += 1\n            continue\n        stale += sum(1 for line in ledger.read_text().splitlines() if re.match(r\"- L\\d+ \\[(sighting|proposed)\\]\", line) and (m := re.search(r\"\\(seen: ([^)]*)\\)\", line)) and len(m[1].split(\",\")) >= 3)\nprint(f\"distance={missing+stale}: {missing} of {len(projects)} sibling projects without a lessons ledger, {stale} lessons seen 3+ times with no applied change\")\n")'
Reading: 2026-11-27, before migration, /Users/paulingalls/src/projects/xp-plugin: distance=7: 7 of 7 sibling projects without a lessons ledger, 0 lessons seen 3+ times with no applied change. No project diagnostics. The reading after the by-hand migration remains a release follow-up.
Candidates: fixes the retros already ask for (sprint retro-fixes); a cross-project read of
sibling ledgers for what the plugin itself should change.
