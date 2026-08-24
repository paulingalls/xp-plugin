# System Context

**Product**: <one paragraph: what this is, for whom>

**Stack**: <languages, runtimes, package managers, test runners>

**Surfaces & acceptance**: <which of: HTTP / Browser / CLI / SDK / Automation /
Message-event — and the harness that drives each at its boundary. Every story's
ACs must be executed by a surface-driving test named in its Verify.>

**Layout**: <the 5-10 paths an agent needs on day one>

**Conventions**: <the rules a reviewer should enforce that constraints.md
doesn't carry>

**Worktree bootstrap**: <one backticked command that makes a fresh worktree
runnable — e.g. `npm ci` or `uv sync` — or "none needed". Only a value that is
entirely one backticked command runs, so prose here can never execute by
accident. Anything else REFUSES the spawn — an unreadable line and an absent
one are different things, and skipping the first silently launched teammates
into unprepared trees. A nonzero exit refuses the spawn too.>

**Worktree teardown**: none needed
Same value grammar as bootstrap: ONE backticked command, or "none". It runs in
the checkout before removal; unlike bootstrap, failure is reported and removal
continues. `config.yml`'s `teardown_timeout` caps it.
