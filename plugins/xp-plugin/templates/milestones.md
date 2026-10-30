# Milestones

A user-facing goal is measured where users are.

Each Measure is one shell line run from the repository root. It prints the
remaining distance in one line: a cheap read over records or files, never a test
run. A dated source prints its own trend. If no record holds what the Measure
needs, the milestone's first card adds that recording. Candidates are optional
discoveries belonging to this goal; start the next slate there.

## <title>
Goal: <the user's words, or a link to the repo document holding them>
Measure: <one shell line printing distance and, for dated sources, trend>
Candidates: <discoveries for the next slate>

<!-- Worked examples, not live milestones. Replace the placeholder above.

## Fewer selected gates
Goal: "Reach the same checks while selecting fewer gates."
Input: gates.csv, date,selected,reachable header; chronological rows
2026-10-29,83,1 and 2026-10-30,12,1. Distance is selected minus reachable;
trend is the change from the previous distance. Prints distance=11; trend=-71,
or distance=82 with only the first row.
Measure: python3 -c 'import csv; r=list(csv.DictReader(open("gates.csv"))); d=[int(x["selected"])-int(x["reachable"]) for x in r]; print(f"distance={d[-1]}"+(f"; trend={d[-1]-d[-2]}" if len(d)>1 else ""))'

## Build the designed screens
Goal: "Build the screens we designed."
Input: designed/*.md and built/*.tsx, matched by stem. Retain the design
inventory when building screens. With designed cart,
checkout, receipt and built cart, prints distance=2; all three built prints
distance=0. This measures construction; a user-facing goal needs usage records.
Measure: python3 -c 'from pathlib import Path; d={p.stem for p in Path("designed").glob("*.md")}; b={p.stem for p in Path("built").glob("*.tsx")}; print(f"distance={len(d-b)}")'
-->
