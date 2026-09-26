#!/usr/bin/env bash
# Docs guard: markdown files only where the AGENTS.md map allows; a new entry
# in docs/DECISIONS.md carries a 'Decided:' line.
#   scripts/check_docs.sh              whole tree; exit 2 if stray files
#   scripts/check_docs.sh --staged     only files added in this commit (pre-commit)
#   scripts/check_docs.sh --stop-hook  Claude Code Stop hook: warn, don't block
#   scripts/check_docs.sh --session-start  Claude Code SessionStart hook: tells the agent
#                                      when enough passes piled up since the last harvest
# With a .git-docs folder (docs in a separate local repo) the checks run against it.
# Project-specific allowed paths: .docs-allow, one ERE per line.
set -euo pipefail
mode=${1:-}

# SessionStart: reminders for the agent, never a failure. Passes logged since the last
# harvest ("## " entries above <!-- harvest --> in docs/LOG.md); in research mode, owner
# messages not yet registered in docs/ASKS.md. No git needed.
if [ "$mode" = --session-start ]; then
  cd "$(dirname "$0")/.."
  notes=()
  every=${AGENTDROP_HARVEST_EVERY:-5}
  n=$(awk '/^<!-- harvest -->/ { exit } /^## / { n++ } END { print n + 0 }' docs/LOG.md 2>/dev/null || echo 0)
  if [ "$n" -ge "$every" ]; then
    notes+=("agentdrop: $n passes logged in docs/LOG.md since the last harvest. At a natural pause, offer the owner in one line to harvest lessons (skill .claude/skills/harvest/SKILL.md) so what this project taught reaches their rules for every project.")
  fi
  if [ -f scripts/owner_asks.py ] && [ -f docs/ASKS.md ]; then
    # python3, python or py -3, whichever runs (Windows has a Store stub named python3)
    for py in python3 python "py -3"; do
      if $py -c "" >/dev/null 2>&1; then
        asks=$($py scripts/owner_asks.py --hook 2>/dev/null || true)
        [ -n "$asks" ] && notes+=("$asks")
        break
      fi
    done
  fi
  [ ${#notes[@]} -eq 0 ] && exit 0
  text=$(printf '%s\n' "${notes[@]}" | tr -d '\r' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' |
    awk 'NR > 1 { printf "\\n" } { printf "%s", $0 }')
  printf '{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "%s"}}\n' "$text"
  exit 0
fi

cd "$(git rev-parse --show-toplevel)"
# Docs in a local repo next to the code one (agentdrop --docs separate): check that repo.
# Its commit hook already arrives with GIT_DIR set.
if [ -z "${GIT_DIR:-}" ] && [ -d .git-docs ]; then
  export GIT_DIR=.git-docs GIT_WORK_TREE=.
fi

allowed='^(AGENTS|CLAUDE|GEMINI|README|LOCAL|CHANGELOG|CONTRIBUTING|LICENSE)\.md$'
allowed+='|^docs/(CONTEXT|DECISIONS|CONVENTIONS|PITFALLS|OPERATIONS|STATE|TODO|QUESTIONS|LOG)\.md$'
allowed+='|^docs/(specs|research|reviews/inbox|archive|shots)/'
allowed+='|(^|/)README\.md$'
allowed+='|^\.(claude|serena|github|codex|gemini|agents)/'
if [ -f .docs-allow ]; then
  while IFS= read -r re; do
    case $re in ''|'#'*) ;; *) allowed+="|$re" ;; esac
  done < .docs-allow
fi

if [ "$mode" = --staged ]; then
  files=$(git -c core.quotepath=off diff --cached --name-only --diff-filter=AR -- '*.md')
else
  files=$(git -c core.quotepath=off ls-files -co --exclude-standard '*.md')
fi
stray=$(printf '%s\n' "$files" | grep -Ev "$allowed" | grep -v '^$' || true)

# A new DECISIONS.md entry must name who decided: a line "Decided: who, where, quote".
# Only added lines count. A heading edited in place (same first 30 chars as a removed
# one) is not new.
if [ "$mode" = --staged ]; then diff_args=(--cached); else diff_args=(HEAD); fi
unsigned=$(git diff "${diff_args[@]}" -U0 -- docs/DECISIONS.md 2>/dev/null | awk '
  /^-## /  { old[substr($0, 2, 30)] = 1; next }
  /^\+/    { add[++n] = substr($0, 2) }
  END {
    for (i = 1; i <= n; i++) {
      if (add[i] ~ /^## /) {
        if (head != "" && !signed) print "  " head
        head = (substr(add[i], 1, 30) in old) ? "" : add[i]; signed = 0
      } else if (add[i] ~ /(Decided|Решил|Решила|Решили)( by)?:/) signed = 1
    }
    if (head != "" && !signed) print "  " head
  }' || true)

[ -z "$stray" ] && [ -z "$unsigned" ] && exit 0

msg=""
if [ -n "$stray" ]; then
  msg="Docs outside the AGENTS.md map:
$(echo "$stray" | sed 's/^/  /')
Reviews and audits: ask to process reviews, the review-intake skill collects them.
Anything else: merge into a docs/*.md, move to docs/archive/, or add the path to .docs-allow."
fi
if [ -n "$unsigned" ]; then
  [ -n "$msg" ] && msg+=$'\n'
  msg+="New docs/DECISIONS.md entries without a 'Decided: who, where, quote' line:
$unsigned
If no human chose it, it is not a decision: put it in QUESTIONS.md as an agent default (rules: DECISIONS.md header)."
fi

if [ "$mode" = --stop-hook ]; then
  # JSON by hand: python3 may be missing, or a Microsoft Store stub, on Windows
  json=$(printf '%s' "$msg" | tr -d '\r' | tr '\t' ' ' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' |
    awk 'NR > 1 { printf "\\n" } { printf "%s", $0 }')
  printf '{"systemMessage": "%s"}\n' "$json"
  exit 0
fi
echo "$msg" >&2
exit 2
