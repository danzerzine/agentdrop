---
name: review-intake
description: Review and audit intake — gathers scattered review files, merges duplicates across models, sets P0–P3, files tickets after the owner's OK. Use when reviews sit in docs/reviews/inbox/ or elsewhere, when asked to process reviews, or when the owner replies to a triage.
---

# review-intake

The owner drops reviews carelessly: three files on one topic from different models, in the root, in `docs/`, under any name. Intake turns the pile into **one** deduplicated list of findings sorted by priority. The owner looks only at the result. This skill changes no code.

Two passes: the first collects and proposes; the second files into docs, only after the owner answers.

## Pass 1 — collect and propose

1. **Collect.** Sources: everything in `docs/reviews/inbox/` plus whatever `scripts/check_docs.sh` reports. Names and locations don't matter, content does. A file is a review if it makes claims against the project; leave anything else and mention it to the owner. `git mv` every review into the inbox as `YYYY-MM-DD-<topic>-<source>.md`, inferring topic and source (model, skill) from the text. Done when no review is left outside the inbox.
2. **Split.** Each finding is one checkable claim with a location (file, screen, number), tagged with its source: `claude-ui #3`.
3. **Merge duplicates.** The same problem in different words becomes one finding with a "who" column. Test: fixing one would fix the other. Similar but distinct findings (same place, different cause) stay separate. When sources disagree, it's one finding with status **question**, both positions in one line.
4. **Check against project memory.**
   - contradicts `docs/DECISIONS.md` → **reject**, citing the entry; `[model]` decisions are not the reviewer's to overturn;
   - already in `docs/TODO.md` → **duplicate** of `B<n>`;
   - already fixed (code, `docs/LOG.md`) → **closed**;
   - otherwise verify in code or the live product: **ticket**, **not confirmed**, or **question** when it's the owner's call (taste, scope, reversing a decision).
   Done when every merged finding has exactly one status.
5. **Set priority** for confirmed findings. Intake decides; the reviewer's severity is a hint.
   - **P0** — wrong data shown to users, data loss or corruption, a leak, prod down.
   - **P1** — security without an active leak; a broken core flow; misleading UI.
   - **P2** — awkward but usable; tech debt that will bite soon.
   - **P3** — polish.
   Agreement of two or three sources raises one step, but not above P1 without verification. A single-source finding that wasn't reproduced stays at P2 or below.
6. **Group into tickets.** P0 and P1: one ticket per finding. P2 and P3 of one theme: one ticket with a list. Name them as they'll appear in TODO: "new B11 (P2): table polish — 3, 5, 9".
7. **Write the triage** to `docs/reviews/inbox/YYYY-MM-DD-triage.md`: proposed tickets by priority on top, then a table "# · gist in five words · who · status · priority · where · why", sorted the same way. Commit the inbox and moved files.
8. **Show the owner** and stop.

If an unanswered triage already sits in the inbox and new reviews arrive, add them to it rather than starting a second one.

## Pass 2 — file

Runs on the owner's answer. Their edits to numbers and priorities override the proposal.

1. Tickets → `docs/TODO.md`: P0–P1 in Now, P2 in Next, P3 in Later. Source: `archive/reviews/YYYY-MM-DD/<file>, #N`. For duplicates, add the source to the existing ticket.
2. Questions → `docs/QUESTIONS.md`, "For the owner". New traps → `docs/PITFALLS.md`.
3. Drop "(proposal)" from the triage title, set statuses as approved, `git mv` all inbox files to `docs/archive/reviews/YYYY-MM-DD/`. One `docs/LOG.md` entry: files, findings before and after merging, tickets, rejections.
4. Check: `scripts/check_docs.sh` is silent, the inbox holds only `.gitkeep`. Commit only these files.

## Report after pass 1

Path to the triage and at most seven lines: how many files from where, findings before and after merging, P0 and P1 by name, what's rejected and why in a word, where you're unsure. End with: "Reply OK or edits by number, e.g. '7 → P1, 12 → reject'." Write the report in the owner's language.
