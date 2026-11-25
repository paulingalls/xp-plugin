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
Measure: python3 -c 'import hashlib,os,re,subprocess as s; from pathlib import Path as P; on=[p.parent for p in P("..").glob("*/.xp") if p.parent.resolve()!=P.cwd().resolve() and re.search(r"(?m)^github_issues: *on\b",(p/"config.yml").read_text() if (p/"config.yml").is_file() else "")]; c=[s.run(["git","-C",str(r),"rev-parse","--path-format=absolute","--git-common-dir"],capture_output=True,text=True).stdout.strip() for r in on]; f=[P.home()/".xp/data"/hashlib.sha256(os.path.realpath(x).encode()).hexdigest()[:12]/"plan.md" for x in c if x]; b=[k for q in f if q.is_file() for k in re.split(r"(?m)^(?=#### )",q.read_text())[1:] if re.match(r"#### \S+ .*\[(planned|in-progress)\]",k)]; n=sum(not re.search(r"(?m)^Issue: *#\d",k) for k in b); print(f"distance={n} of {len(b)} open cards not shared as issues in {len(on)} sibling clones with github_issues on")'
Reading: 2026-11-23, project root: distance=0 of 0 open cards not shared as issues in 0 sibling clones with github_issues on. No opted-in sibling clones; this is no cross-machine reading.
Candidates: the closing reads of Evidence cards; release-waiting state beyond a merged PR.

## Projects learn from their retros
Goal: "nothing really changes as a result, neither in the next session nor is there later
analysis done across multiple retros looking for patterns or anything to learn ... an
opportunity here for a project to improve itself" (Paul, 2026-11-25)
Measure: python3 -c 'import re,subprocess as s; from pathlib import Path as P; sib=[p.parent for p in P("..").glob("*/.xp") if p.parent.resolve()!=P.cwd().resolve()]; url=lambda r: s.run(["git","-C",str(r),"remote","get-url","origin"],capture_output=True,text=True).stdout.strip().lower(); slug=lambda r: "/".join(m.groups()) if (m:=re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url(r))) else ""; proj=sorted({slug(r) for r in sib}-{""}); led={k:P.home()/".xp/projects"/k/"lessons.md" for k in proj}; none=[k for k in proj if not led[k].is_file()]; stale=sum(1 for k in proj if led[k].is_file() for ln in led[k].read_text().splitlines() if re.match(r"- L\d+ \[(sighting|proposed)\]",ln) and (m:=re.search(r"\(seen: ([^)]*)\)",ln)) and len(m[1].split(","))>=3); print(f"distance={len(none)+stale}: {len(none)} of {len(proj)} sibling projects without a lessons ledger, {stale} lessons seen 3+ times with no applied change")'
Candidates: fixes the retros already ask for (sprint retro-fixes); a cross-project read of
sibling ledgers for what the plugin itself should change.
