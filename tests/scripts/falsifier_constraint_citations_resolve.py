#!/usr/bin/env python3
"""A constraint index cited in SHIPPED prose must mean the same rule in the
reader's repo as it does in ours.

Constraint indices are project-local. `xp-setup` seeds a starter constraints.md
and every project then grows its own, so our "(constraint 10)" lands in a tree
where 10 is a different rule. Measured against ../legacy: our 10 is marker
scoping, theirs is "Secrets never enter history". A dangling pointer would be
loud; this resolves to a real rule and teaches it.
CONSTRUCTED, not grepped for a token: scaffold a real consumer with setup.py,
then resolve each citation against THAT file and compare the rule it lands on to
the rule we meant. Reds while any citation resolves differently or not at all.
CITE spans every spelling this tree has actually used — `constraint 10`,
`constraints #6`, `constraints.md #10`, `constraints 12-15` — because a pattern
narrower than the defect certifies the citations it cannot see.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "xp-plugin"
CITE = re.compile(r"constraints?(?:\.md)? *#? *(\d+)", re.I)


def headlines(path):
    out = {}
    for line in path.read_text().splitlines():
        if m := re.match(r"(\d+)\.\s+\*\*(.+?)\*\*", line.strip()):
            out[int(m.group(1))] = m.group(2)
    return out


with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp) / "consumer"
    repo.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "XP_DATA": str(Path(tmp) / "data")}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
    subprocess.run(
        [sys.executable, str(PLUGIN / "scripts" / "setup.py")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    scaffolded = repo / ".xp" / "constraints.md"
    if not scaffolded.exists():
        print(f"setup.py scaffolded no constraints.md at {scaffolded}")
        sys.exit(1)
    theirs = headlines(scaffolded)

ours = headlines(ROOT / ".xp" / "constraints.md")
bad = []
for path in sorted(PLUGIN.rglob("*")):
    if path.suffix not in {".py", ".md", ".sh"} or "__pycache__" in path.parts:
        continue
    if path.name == "constraints.md":
        continue
    for n in {int(x) for x in CITE.findall(path.read_text())}:
        mine, theirs_n = ours.get(n), theirs.get(n)
        if mine != theirs_n:
            bad.append((path.relative_to(ROOT), n, mine, theirs_n))

print(f"ours: {len(ours)} constraints · a freshly scaffolded consumer: {len(theirs)}")
print(f"citations by index in shipped files that resolve to a different rule: {len(bad)}")
for rel, n, mine, th in bad[:4]:
    print(f"  {rel}: 'constraint {n}' — we mean {mine!r}, they read {th!r}")
sys.exit(1 if bad else 0)
