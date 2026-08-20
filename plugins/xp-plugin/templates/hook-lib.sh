# shared by the scaffolded hooks — tiers come from .xp/config.yml AT RUN TIME
# so config stays declared-once (editing tiers never means editing hooks)
tier_cmd() {  # $1 = fast|story|full
  sed -n "/^tests:/,/^[^ ]/p" .xp/config.yml | sed -n "s/^  $1:\([^#]*\).*/\1/p" | head -1 | xargs echo
}
secrets_scan() {
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks protect --staged --no-banner --redact || exit 1
  else
    echo "xp wall: gitleaks not installed — secrets scan SKIPPED (install gitleaks)" >&2
  fi
}
run_tier() {
  cmd="$(tier_cmd "$1")"
  if [ -z "$cmd" ] || [ "$cmd" = "EDIT-ME" ]; then
    echo "xp wall: tests.$1 is unset in .xp/config.yml — edit it (running nothing)" >&2
    return 0
  fi
  sh -c "$cmd"
}
