## Project docs charter

**Precedence:** the owner's live instruction > active spec in `docs/specs/` > `docs/DECISIONS.md` > other docs. If an instruction contradicts a decision, follow the instruction, name the conflict in one line and log a new decision. Decisions tagged `[model]` change only with their author.

**Before work:** read `docs/STATE.md` and `docs/TODO.md`. Before product, architecture, data or deploy decisions, also read `docs/CONTEXT.md` and the relevant `docs/DECISIONS.md` entries. Before touching fragile code, read `docs/PITFALLS.md`. Before any UI change, read the project's design system doc named in `AGENTS.md`; sizes, spacing and colors come from its roles and tokens, not from the eye.

**Claims:** before editing, run `agentdrop status` (what waits for the owner, what other sessions hold, what's next) and claim your ticket: `agentdrop claim B<n>`. If another session holds it, take another ticket or ask the owner; never work on a claimed ticket silently. A pass without a ticket (docs, review intake) claims nothing but still checks status for sessions editing the same docs. Release at the end of the pass, also when you stop halfway: `agentdrop release B<n>`.

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

**Threads in docs:** the owner comments under an item as `> **Name, dd.mm hh:mm:** …`. Answer under the comment in the same quote format, not only in chat; keep the thread until the item is archived; commit it with your pass. A thread ending in `_Thread closed._` (or `_Ветка закрыта._`) is resolved: in your next pass finish the item by the project's rules (move it to done, remove the ticket, log the decision).

**Finishing a pass:** entry in `LOG.md`; update `STATE.md` if the picture changed; remove the done ticket from `TODO.md`; `agentdrop release B<n>`. Commit only your own files, no AI attribution. Then `agentdrop brief --send`: your LOG entry and any new question reach the owner's phone, one message per question (without Telegram set up it sends nothing). Owner's answers from Telegram arrive as thread comments; `agentdrop status` collects them.

**Questions for the owner** (`QUESTIONS.md`, tickets waiting for an OK) go to the owner's phone as they are, one message each, so each item stands on its own: what exactly is asked, the draft, numbers or options quoted in the item itself, never "see CONVENTIONS.md" or a code without words. A choice between UI variants names its before and after pictures in the item (paths to screenshots or mockups in the project); `agentdrop brief` sends them as photos under the question.

**Pass-end brief:** your last message of a pass is a brief the owner can read on a phone without opening anything. (1) What happened, meaning first, the code in parentheses: "the mobile tooltip fix (B64) is live", never "B64 done". (2) The key number, or the draft itself, quoted inline. (3) What needs the owner: options with your pick. (4) What you will do if nobody answers. Link only rendered pages, never raw markdown files: in the owner's chat they open as a diff among dozens of files.

**Harvest:** lessons that would help any project go up into the owner's agentdrop rules, not only into this project's docs. When five or more passes sit above the `<!-- harvest -->` marker in `LOG.md` (in Claude Code a SessionStart hook says so), or a pass produced a rule that isn't about this project, offer a harvest in one line; the `harvest` skill (`.claude/skills/harvest/SKILL.md`, other harnesses: read and follow it) proposes and writes after the owner's OK.
