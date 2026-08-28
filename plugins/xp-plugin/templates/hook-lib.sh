# shared by the scaffolded hooks — tiers come from .xp/config.yml AT RUN TIME
# so config stays declared-once (editing tiers never means editing hooks)
# $1 = fast|story|full — trim with sed, never xargs (xargs eats quotes).
# Take the WHOLE value, then strip only what YAML calls a comment: one that opens
# at a whitespace-preceded `#`. Cutting at any `#` truncated `p#ss` mid-password
# into a bare VAR=value — a valid command that assigns, exits 0, and runs no test.
tier_cmd() {
  sed -n "/^tests:/,/^[^ ]/p" .xp/config.yml \
    | sed -n "s/^[[:space:]][[:space:]]*$1:\(.*\)/\1/p" | head -1 \
    | sed "s/[[:space:]][[:space:]]*#.*$//" \
    | sed "s/^[[:space:]]*//;s/[[:space:]]*$//"
}
# Both legs below REFUSE rather than warn. A gate that reports green having run
# nothing is worse than no gate: the commit it passes looks scanned and tested.
secrets_scan() {
  if ! command -v gitleaks >/dev/null 2>&1; then
    echo "xp wall: gitleaks not installed — refusing to pass a commit nothing scanned." >&2
    echo "  Install it (brew install gitleaks, or github.com/gitleaks/gitleaks), then retry." >&2
    exit 1
  fi
  gitleaks protect --staged --no-banner --redact || exit 1
}
constraints_size() {
  cap="$(sed -n 's/^constraints_chars_cap:[[:space:]]*//p' .xp/config.yml | head -1 | sed 's/[[:space:]][[:space:]]*#.*$//')"
  if [ -z "$cap" ]; then
    echo "xp wall: constraints_chars_cap is missing in .xp/config.yml — refusing." >&2
    exit 1
  fi
  case "$cap" in *[!0-9]*|0)
    echo "xp wall: constraints_chars_cap '$cap' is invalid in .xp/config.yml — use a positive integer." >&2
    exit 1;;
  esac
  if [ ! -f .xp/constraints.md ]; then
    echo "xp wall: .xp/constraints.md is missing — refusing." >&2
    exit 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "xp wall: python3 not installed — refusing to pass a commit nothing measured." >&2
    echo "  Install python3 (every xp script needs it), then retry." >&2
    exit 1
  fi
  # encoding PINNED: read_text defaults to the LOCALE's encoding, so under a C
  # locale with PEP 538 coercion off every non-ASCII BYTE decodes to its own
  # replacement char and the count becomes the byte length (measured: 11 chars
  # counted 44). A cap that changes with $LC_ALL is not a cap.
  count="$(python3 -c 'from pathlib import Path; print(len(Path(".xp/constraints.md").read_text(encoding="utf-8", errors="replace")))')"
  # An EMPTY count is `[ "" -gt N ]`, which errors and reads as "under cap": the
  # measurement failing must refuse, not pass (the rule this file opens with).
  case "$count" in ""|*[!0-9]*)
    echo "xp wall: could not measure .xp/constraints.md — refusing to pass a commit nothing measured." >&2
    echo "  The error above is python3's: make .xp/constraints.md readable, then retry." >&2
    exit 1;;
  esac
  if [ "$count" -gt "$cap" ]; then
    echo "xp wall: .xp/constraints.md is $count characters against constraints_chars_cap $cap." >&2
    echo "  retire or shorten a constraint, then retry." >&2
    exit 1
  fi
}
run_tier() {
  # EVERY tier, not just fast: pre-push RE-CHECKS what pre-commit checked, and
  # `git merge` never fires pre-commit at all. Measured before this line moved:
  # `run_tier story` exited 0 on a 5,000-char constraints.md against a cap of 10.
  constraints_size
  cmd="$(tier_cmd "$1")"
  if [ -z "$cmd" ] || [ "$cmd" = "EDIT-ME" ]; then
    echo "xp wall: tests.$1 is unset or still EDIT-ME in .xp/config.yml — refusing to" >&2
    echo "  pass a commit no test ran. Set tests.$1 to your suite's command, then retry." >&2
    exit 1
  fi
  sh -c "$cmd"
}
