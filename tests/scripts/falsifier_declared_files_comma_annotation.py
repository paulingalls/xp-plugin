import sys

sys.path.insert(0, "plugins/xp-plugin/scripts")
from review import declared_files

card = "Files: a.py, infra/compose.yml (compose, not the chart), b.py\nAC:\n"
got = declared_files(card)
missing = "infra/compose.yml" not in got
junk = [f for f in got if "(" in f or ")" in f]
if missing or junk:
    print(f"RED: declared_files dropped the annotated path; got {sorted(got)}")
    raise SystemExit(1)
print("GREEN: annotated path survives, no junk entries")
