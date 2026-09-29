## Project docs charter

_The short form; the whole charter, with the docs map and the question form, is `docs/CHARTER.md`: read it once per session before your first edit._

**Precedence:** the owner's live instruction > active spec in `docs/specs/` > `docs/DECISIONS.md` > other docs. A conflict: follow the instruction, name the conflict in one line, log a new decision.

**Before work:** read `docs/STATE.md`, then run `agentdrop status`. Product, architecture, data or deploy decisions: also `docs/CONTEXT.md` and `docs/DECISIONS.md`. Fragile code: `docs/PITFALLS.md`. UI: the design doc named above; sizes, spacing and colours come from its roles.

**Tasks:** `agentdrop task where` says where they live. In the store: `agentdrop task take [B<n>]`, `task comment|ask|state|new|handin`, then `agentdrop accept B<n>` in the background; never edit `docs/TODO.md` (agentdrop prints it from the store every night) or `docs/QUESTIONS.md`. In markdown: `agentdrop claim B<n>` / `release B<n>` and the files, as `docs/CHARTER.md` says. Never work on a task another session holds.

**Markdown files** live only where the map in `docs/CHARTER.md` or `.docs-allow` says; `scripts/check_docs.sh` enforces it on commit. `AGENTS.md` stays under 6 KB: new detail goes to a doc it links.

**A rule broken three times** becomes a check (a hook, a test, a line in `docs/checks`), not a longer paragraph here.

**Questions for the owner** go through `agentdrop task ask` in parts: the question and `--context` up to 120 characters each, 2–4 `--option`s up to 60, `--pick`, codes and paths only in `--details`, and `--design` with pictures or `--no-design`.

**Finishing a pass:** entry in `docs/LOG.md`; `docs/STATE.md` if the picture changed; commit only your own files, no AI attribution; `agentdrop accept B<n>` (exit 1: fix and rerun; exit 3: it went to the owner). The last message is a brief readable on a phone: meaning first with the code in parentheses, the key number, what needs the owner with your pick.
