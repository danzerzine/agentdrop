#!/usr/bin/env bash
# Docs guard: markdown files only where the AGENTS.md map allows.
#   scripts/check_docs.sh              whole tree; exit 2 if stray files
#   scripts/check_docs.sh --staged     only files added in this commit (pre-commit)
#   scripts/check_docs.sh --stop-hook  Claude Code Stop hook: warn, don't block
# Project-specific allowed paths: .docs-allow, one ERE per line.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
mode=${1:-}

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
[ -z "$stray" ] && exit 0

msg="Docs outside the AGENTS.md map:
$(echo "$stray" | sed 's/^/  /')
Reviews and audits: ask to process reviews, the review-intake skill collects them.
Anything else: merge into a docs/*.md, move to docs/archive/, or add the path to .docs-allow."

if [ "$mode" = --stop-hook ]; then
  python3 -c 'import json,sys; print(json.dumps({"systemMessage": sys.argv[1]}))' "$msg"
  exit 0
fi
echo "$msg" >&2
exit 2
