---
name: harvest
description: Harvest lessons — finds what this project taught that would help every project (rules, traps, working habits), generalizes it and, after the owner's OK, writes it into their agentdrop rules and kit so all projects and harnesses get it. Use when asked to harvest lessons, when the SessionStart reminder says passes piled up, or when a pass produced a rule that isn't about this project.
---

# harvest

A project keeps learning: a convention after a mistake, a trap in `PITFALLS.md`, a decision the owner made about how to work. Most of it is about this project. Some of it is about working at all, and that part should not stay here. Harvest moves it up one level, into the owner's agentdrop, and from there into every project and every harness on the next `agentdrop sync`. It changes no code in the project.

Two passes, like review intake: the first proposes, the second writes after the owner answers.

## Where lessons live

| Level | File | Reaches |
|---|---|---|
| this project | `docs/CONVENTIONS.md`, `PITFALLS.md`, `DECISIONS.md` | this project |
| the owner, everywhere | `~/.agentdrop/COMMON.md`, then `agentdrop sync` | every project, every harness |
| the project template | `~/.agentdrop/kit/` (charter, templates, skills; research mode in `kit/modes/research/`) | new projects; the charter block refreshes on `agentdrop .` |
| everyone | the agentdrop repo, if `~/.agentdrop/source` names a clone of it | people who install agentdrop |

## Pass 1 — collect and propose

1. **Scope.** Entries in `docs/LOG.md` above the `<!-- harvest -->` marker (all entries if there is none), and what `CONVENTIONS.md`, `PITFALLS.md`, `DECISIONS.md` and the charter block's project notes gained in the same period (`git log -p` on them, or a read if there is no history).
2. **Pick candidates.** A candidate is a rule, habit or trap that would change how an agent works in an unrelated project. Test: rewrite it without this project's names, data and tools; if it still says something an agent would get wrong, it's a candidate. Skip anything about this product's domain, data quirks of one source, and one-off facts.
3. **Check against what exists.** Read `~/.agentdrop/COMMON.md`, `~/.agentdrop/kit/CHARTER.md` and, for research lessons, `~/.agentdrop/kit/modes/research/CHARTER.md`. Already said → drop. Says the opposite → a **question** for the owner, both wordings side by side.
4. **Generalize.** One rule, one or two sentences, in the style of the target file: imperative, no project names, the reason folded in when it is short. Keep the owner's own words where they carry the point.
5. **Place.** For each: COMMON (how the owner and agents work anywhere), kit charter (how project docs are kept), research charter (how unknowns are explored and claims tested), a kit template or skill. Mark whether it is general enough for everyone (upstream) or personal to the owner (a machine, a language, a taste).
6. **Show the owner** a numbered table: `# · lesson as it will be written · target · upstream? · came from (file, date, quote)`. Stop.

## Pass 2 — write

Runs on the owner's answer; their edits override the proposal ("3 → personal, 5 drop").

1. Edit `~/.agentdrop/COMMON.md` and the files in `~/.agentdrop/kit/`. Never edit the managed blocks inside projects by hand; they come from these files.
2. Run `agentdrop sync`, then `agentdrop .` in this project so the charter block refreshes. Show which harnesses were updated.
3. Upstream, only for lessons the owner marked so: if `~/.agentdrop/source` names a git clone of agentdrop, make the same edits there on a branch `harvest/<date>` (the default rules live in `DEFAULT_COMMON` in the `agentdrop` script, the rest in `kit/`), run its tests, commit. Push or open a pull request only after a second OK. Without a clone, give the owner the text of an issue for the agentdrop repository.
4. Move the `<!-- harvest -->` marker in `docs/LOG.md` to the top, above the newest entry, and log the pass: how many candidates, how many written where, what went upstream.
