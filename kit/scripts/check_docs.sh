#!/usr/bin/env bash
# Сторож документации: md-файлы только в местах из карты AGENTS.md.
#   scripts/check_docs.sh              всё дерево; выход 2 — есть лишние файлы
#   scripts/check_docs.sh --staged     только добавляемое в коммит (pre-commit)
#   scripts/check_docs.sh --stop-hook  Stop-хук Claude Code: предупредить, не блокировать
# Свои разрешённые пути проекта — в .docs-allow, по регулярке (ERE) на строку.
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
  files=$(git diff --cached --name-only --diff-filter=AR -- '*.md')
else
  files=$(git ls-files -co --exclude-standard '*.md')
fi
stray=$(printf '%s\n' "$files" | grep -Ev "$allowed" | grep -v '^$' || true)
[ -z "$stray" ] && exit 0

msg="Документы вне карты AGENTS.md:
$(echo "$stray" | sed 's/^/  /')
Ревью и аудиты — скажи «разбери ревью», скилл review-intake соберёт их сам.
Остальное — слить в подходящий docs/*.md, перенести в docs/archive/ или добавить путь в .docs-allow."

if [ "$mode" = --stop-hook ]; then
  python3 -c 'import json,sys; print(json.dumps({"systemMessage": sys.argv[1]}))' "$msg"
  exit 0
fi
echo "$msg" >&2
exit 2
