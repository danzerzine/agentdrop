## Project docs charter

**Precedence:** the owner's live instruction > active spec in `docs/specs/` > `docs/DECISIONS.md` > other docs. If an instruction contradicts a decision, follow the instruction, name the conflict in one line and log a new decision. Decisions tagged `[model]` change only with their author.

**Before work:** read `docs/STATE.md` and `docs/TODO.md`. Before product, architecture, data or deploy decisions, also read `docs/CONTEXT.md` and the relevant `docs/DECISIONS.md` entries. Before touching fragile code, read `docs/PITFALLS.md`. Before any UI change, read the project's design system doc named in `AGENTS.md`; sizes, spacing and colors come from its roles and tokens, not from the eye.

| File | What goes there |
|---|---|
| `docs/CONTEXT.md` | product, people, data sources, glossary, code map; changes rarely |
| `docs/DECISIONS.md` | only choices a named human made between alternatives, costly to forget: what, why, rejected, what not to undo, last line `Decided: who, where, quote` (`check_docs.sh` checks it). Bugs, UI, ops, facts and agent defaults go to their own files; same day. Superseded entries move whole to `DECISIONS.archive.md` |
| `docs/CONVENTIONS.md` | rules we always follow |
| `docs/PITFALLS.md` | traps we already fell into |
| `docs/OPERATIONS.md` | run, deploy, servers, access; names and paths only, no secrets |
| `docs/STATE.md` | what works, half-done, broken; rewrite whole when the picture changes |
| `docs/TODO.md` | tickets `B<n>` with P0–P3 (now / next / later): only what remains and its source; done → `LOG.md`, history → spec; numbers never reused |
| `docs/QUESTIONS.md` | questions for the owner or others; agent decisions the owner may revert; closed items kept a week, then deleted |
| `docs/LOG.md` | one 3–5 line entry per finished pass, newest on top |
| `docs/specs/B<n>-<name>.md` | spec for a multi-pass task; report appended at the end |
| `docs/research/` | reference studies; every number has a source and date |
| `docs/reviews/inbox/` | raw reviews and audits, any name; the `review-intake` skill (`.claude/skills/review-intake/SKILL.md`, other harnesses: read and follow it) merges duplicates, sets P0–P3 and files tickets after the owner's OK |
| `docs/archive/` | closed specs, processed reviews, outdated docs; `git mv` here, never edit |
| `LOCAL.md` | machine-specific notes, not in git |

Every markdown file lives in a place from this table or `.docs-allow`; `scripts/check_docs.sh` enforces it on commit.

**Threads in docs:** the owner comments under an item as `> **Name, dd.mm hh:mm:** …`, from `agentdrop forum` or by hand; the forum's background agent may already have replied as `> **Agent, …:**`. Answer under the comment in the same quote format, not only in chat; keep the thread until the item is archived; commit it with your pass. A thread ending in `_Thread closed._` (or `_Ветка закрыта._`) is resolved: in your next pass finish the item by the project's rules (move it to done, remove the ticket, log the decision).

**Finishing a pass:** entry in `LOG.md`; update `STATE.md` if the picture changed; remove the done ticket from `TODO.md`. Commit only your own files, no AI attribution.
