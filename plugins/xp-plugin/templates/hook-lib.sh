# shared by the scaffolded hooks — tiers come from .xp/config.yml AT RUN TIME
# so config stays declared-once (editing tiers never means editing hooks)
tier_cmd() {  # $1 = fast|story|full — trim with sed, never xargs (xargs eats quotes)
  sed -n "/^tests:/,/^[^ ]/p" .xp/config.yml \
    | sed -n "s/^[[:space:]][[:space:]]*$1:\([^#]*\).*/\1/p" | head -1 \
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
run_tier() {
  cmd="$(tier_cmd "$1")"
  if [ -z "$cmd" ] || [ "$cmd" = "EDIT-ME" ]; then
    echo "xp wall: tests.$1 is unset or still EDIT-ME in .xp/config.yml — refusing to" >&2
    echo "  pass a commit no test ran. Set tests.$1 to your suite's command, then retry." >&2
    exit 1
  fi
  sh -c "$cmd"
}
