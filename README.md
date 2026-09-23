# agentdrop

**Dotfiles for your coding agents.**

You keep one set of working rules and run one command. After that, Claude Code, Codex, Gemini CLI, OpenCode and Command Code all read the same instructions. The command also sets up a new project with a docs layout that agents keep tidy.

```sh
agentdrop .          # set up the current project
```

The script is a single Python file with no dependencies and never overwrites what you wrote.

## Install

```sh
git clone https://github.com/danzerzine/agentdrop
python3 agentdrop/agentdrop --install
```

This copies the script to `~/.local/bin` and creates `~/.agentdrop/COMMON.md` (your rules) and `~/.agentdrop/kit/` (the project skeleton). It then syncs the rules into every harness's global config:

| Harness | Where the rules go |
|---|---|
| Claude Code | `~/.claude/rules/agentdrop-common.md` |
| Codex | `~/.codex/AGENTS.md` (or `AGENTS.override.md` if you use one) |
| Gemini CLI | `~/.gemini/GEMINI.md` |
| OpenCode | `~/.config/opencode/AGENTS.md` |
| Command Code | `~/.commandcode/AGENTS.md` |

Existing files keep their content. agentdrop only adds or updates a block between `<!-- AGENTDROP:… -->` markers and backs up every file to `~/.agentdrop/backups/` before it touches it.

## Everyday use

```sh
agentdrop edit              # open your rules (COMMON.md)
agentdrop sync              # push edited rules to all harnesses
agentdrop .                 # set up or refresh the project you're in
agentdrop ~/code/app        # same, for another path
agentdrop --dry-run .       # show what would change
```

## What a project gets

```
AGENTS.md                  your project notes on top, managed block below
CLAUDE.md / GEMINI.md      one-line @AGENTS.md imports
docs/
  CONTEXT.md               what the product is, who uses it, glossary
  DECISIONS.md             decision log: what, why, what was rejected
  CONVENTIONS.md           "we always do it this way"
  PITFALLS.md              traps someone already fell into
  OPERATIONS.md            how to run, deploy, access (no secrets)
  STATE.md                 what works right now
  TODO.md                  tickets B1, B2… with P0–P3
  QUESTIONS.md             what the agent needs a human for
  LOG.md                   one entry per finished pass
  specs/ research/ archive/
  reviews/inbox/           drop raw reviews here
.claude/skills/review-intake/
scripts/check_docs.sh      guard: markdown only where the map allows
.githooks/pre-commit       runs the guard on staged files
```

The managed block in `AGENTS.md` holds your common rules plus a charter. The charter tells the agent where each kind of note goes, how to run a pass, and which file wins when instructions conflict. Anything project-specific goes above the block. agentdrop never rewrites that part.

## Reviews without the mess

You ask three models to critique the project and end up with three overlapping markdown files in random places. Drop them anywhere, then tell Claude Code:

> разбери ревью (review the reviews)

The `review-intake` skill then works in two steps:

1. It collects every review file, splits them into single findings and merges duplicates across models (with a "who said it" column). It checks each finding against `DECISIONS.md` and the existing tickets, then assigns P0–P3 on its own scale and writes one summary into `docs/reviews/inbox/`. Then it stops and waits for you.
2. You answer "ok" or give corrections like "7 → P1, 12 → reject". After that it files the tickets, moves the raw reviews to `docs/archive/reviews/<date>/` and logs the pass.

`check_docs.sh` keeps new stray files from piling up. The pre-commit hook blocks a commit that adds markdown outside the map. In Claude Code, a Stop hook warns you without blocking the agent. If a project needs extra places for docs, list them as regexes in `.docs-allow`.

## Customize

- **Rules:** `agentdrop edit`, then `agentdrop sync`.
- **Charter and templates:** edit files in `~/.agentdrop/kit/`, then run `agentdrop .` in a project. Only missing files are copied; the charter block is refreshed every time.
- **Language:** the kit ships in Russian, the author's working language. Translating `kit/` into your language only changes content, so the script works the same.

## Older layouts

If a project already keeps `HANDOFF.md`, `PROGRESS.md` and similar files in the root, agentdrop leaves them as they are and doesn't add the `docs/` kit. Ask your agent to migrate the notes to `docs/`, then run `agentdrop .` again.

## License

MIT
