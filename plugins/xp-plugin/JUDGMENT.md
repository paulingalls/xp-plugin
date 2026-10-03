# Judgment
- See red; never fake it. No-red commit: why. Never bypass hooks.
- **Comments** — restatement/history → delete · WHAT → rename · claim → test. Keep why/external constraints/rejected designs.
- **Review** — responsibilities/boundaries: co-change, interference, exposed internals; contracts/authoritative knowledge: caller promises, rule owners, copies; necessary complexity: required behavior/callers/repeated change. Findings: code, cost/failure now, XP value, cheapest sufficient fix. Principles ≠ proof. Like lines need not duplicate knowledge; no imagined use/mandatory split. Red → green → refactor; prep only if safer/simpler here, behavior preserved: named existing checks unchanged, green before/after. Generalization/uncovered behavior/resolved conflict: round if silent or corrupting (false green, corrupted record, unreviewed merge); loud does not.
- **New information** — restate purpose; no drift.
Fix; reasoned drop or debt under BOTH bars. Drop too-big loud.
Escalate reserved choices; ACs/blockers unwaivable. LLMs judge; hooks validate.
## Records (`work.py` only)
- **bug** — claim + red falsifier + files; fix now. No red: judge.
- **debt** — claim + green falsifier + files; BOTH too big (doubles card/crosses concern/separate design) AND too important (silent/corrupting/privacy/user harm). `debt`/renewed `keep --ref ID`: restate reasons via `--too-big`/`--too-important`.
- **resolve** — green replacement evidence; lead only, close, landed tree. Suite owns regression; only open claims recur.
- **note** — tradeoff/discovery, never deferred findings; promote/archive at close; next-story: card.
- **Polarity** — debt: green=still OK; red=materialised; green from flaw=inverted.
Telemetry: remeasure; never record.
