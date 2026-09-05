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
# The scanners below REFUSE rather than warn. A gate that reports green having run
# nothing is worse than no gate: the commit it passes looks scanned and tested.
secrets_require_gitleaks() {
  if ! command -v gitleaks >/dev/null 2>&1; then
    echo "xp wall: gitleaks not installed — refusing to pass a Git path nothing scanned." >&2
    echo "  Install it (brew install gitleaks, or github.com/gitleaks/gitleaks), then retry." >&2
    return 1
  fi
}
secrets_scan_index() {
  secrets_require_gitleaks || return 1
  if ! gitleaks protect --staged --no-banner --redact; then
    echo "xp wall: remove the secret from staged content, re-stage, and retry." >&2
    return 1
  fi
}
secrets_scan_push() {
  secrets_require_gitleaks || return 1
  refs=0
  while read -r local_ref local_sha remote_ref remote_sha; do
    refs=$((refs + 1))
    case "$local_sha" in
      ""|*[!0]*) ;;
      *) echo "xp wall: ref deletion ($local_ref); no outgoing commits to scan." >&2; continue;;
    esac
    case "$remote_sha" in
      ""|*[!0]*)
        # gitleaks EXITS 0 on a range git cannot resolve (measured on 8.30.1: a
        # force-push over unfetched remote motion printed `Invalid revision
        # range` and `no leaks found`, and the push landed unscanned), so the
        # range has to be proved resolvable HERE or the wall passes what it
        # never read.
        if ! git rev-parse --quiet --verify "$remote_sha^{commit}" >/dev/null 2>&1; then
          echo "xp wall: $remote_ref is at $remote_sha, which this clone does not have —" >&2
          echo "  nothing could be scanned. Run \`git fetch\`, then retry." >&2
          return 1
        fi
        scan_range="$remote_sha..$local_sha";;
      *) scan_range="$local_sha --not --remotes";;
    esac
    if ! gitleaks git --log-opts="$scan_range" --no-banner --redact </dev/null; then
      echo "xp wall: rewrite the outgoing history to remove the secret, then retry." >&2
      return 1
    fi
  done
  # Zero ref lines is `nothing to push` AND `stdin never arrived`; the second is a
  # wall that greens having read nothing, so the state gets named rather than
  # inferred from the silence.
  [ "$refs" -gt 0 ] || echo "xp wall: git sent no ref updates — nothing to push, or stdin never reached this hook." >&2
}
constraints_size() {
  cap="$(sed -n 's/^constraints_chars_cap:[[:space:]]*//p' .xp/config.yml | head -1 | sed 's/[[:space:]][[:space:]]*#.*$//')"
  if [ -z "$cap" ]; then
    echo "xp wall: constraints_chars_cap is missing in .xp/config.yml — refusing." >&2
    echo "  Add \`constraints_chars_cap: 4500\` to .xp/config.yml, then retry." >&2
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
    echo "refused: tests.$1 is unset or still EDIT-ME in .xp/config.yml — no test tier ran. Set tests.$1 to your suite's command, then retry" >&2
    exit 1
  fi
  sh -c "$cmd"
}
