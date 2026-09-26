## Research mode

This project explores the unknown: the job is to map it wide and deep, find candidate mechanisms and test them, not to prove one model. The rules below come from a research project where depth quietly shrank, owner asks got lost and early guesses hardened into "facts".

**The owner's question is the spec.**
- Every ticket carries `Why: «verbatim owner quote» (dd.mm)`. No quote, no ticket: ask, or write `Why: agent's assumption`. Never reframe the question without the owner's consent ("what does the gap tell us about the algorithm" is not "what threatens us").
- A pass closes only after independent acceptance against that quote (`acceptance-judge`, or a fresh session with no executor context). What the report did not answer goes into a "Not answered" section and a new ticket.
- Several topics in one message: each becomes a ticket at once, and the reply says which one goes deep this pass and which wait. Don't spread depth thin, don't drop topics silently.

**Every ask is registered.** `docs/ASKS.md` holds one row per research ask: verbatim quote, message id, mode, ticket, status. Run `python3 scripts/owner_asks.py --new` at the start and end of a pass (it reads Claude Code transcripts, and a SessionStart hook runs it for you there; in other harnesses reread the conversation); a pass is not closed while a new ask lacks a row. The agent sets the mode, the owner doesn't have to:
- **question** — answer it; **wide** — the owner's example is a starting point, not the scope; **idea** — a hypothesis to test on data; **errand** — make a thing; **correction** — apply everywhere it touches.
- Statuses: answered, partial, lost, reframed (answered a different question), in progress, dropped by owner.

**Go wide, and show the width.**
- A "wide" ask is accepted by breadth: where we searched, how many candidates beyond the owner's example, what follows. "Found nothing" is an answer when the places are named.
- Collect first, filter later. Record correlations, labeled "correlation", as experiment candidates. A weak signal on a small sample is a reason for an experiment, not for closing the direction; the minimum cell size for interpreting a number lives in `CONVENTIONS.md`.
- Every report ends with **Nearby**: 2–5 adjacent topics or clusters noticed on the way, each with one observation with a number and a proposed ticket. Don't dig into them silently, don't drop them silently; the owner picks. An empty section is fine if it says where we looked.

**Test hypotheses the same way every time** (experimental: this registry is the newest part and may change). `docs/HYPOTHESES.md` holds each hypothesis with its source, a prediction written before computing, the measure and the verdict. The standard check: compare within a segment (same topic, same period), run a placebo (the same feature against another channel or outcome it should not move), respect the minimum sample. Verdict card: confirmed / not confirmed / can't test on our data, with the number and one caveat.

**Claims carry their evidence level.** `docs/CLAIMS.md` lists every claim that reaches `STATE.md`, a deck or people outside, numbered and never renumbered: wording, where it is stated, level, what it rests on, who checked and with what result.
- Levels: **fact** (reproduced from raw data by one calculation, no "because"), **observation** (a difference, link or shape in our data; says nothing about cause), **hypothesis** (an explanation or mechanism; fit for an experiment, not for "this is how it works"), **opinion** (someone else's, with the source and its kind: the vendor's own statement, someone else's data, a retelling).
- Before a claim leaves the project, an independent skeptic tries to refute it: the `skeptic` agent, or a fresh session given only the wording, where it is stated and the data paths, never the executor's reasoning. Its verdict goes into the registry: **holds**, **holds narrowed** (the new wording is written in, the level may drop), **withdrawn** (fixed or marked wherever it was stated), **can't check**. Its calculations are kept outside git.
- Until the skeptic has looked, the claim is **not checked** and travels only with its level named.
- A level changes only through the registry: first the row, then the report, `STATE.md` and decks, citing the claim number. Only a new check raises a level; anyone with a counterargument can lower it.
- In texts for people the level shows in the words: "we counted" for a fact, "the data shows" for an observation, "it looks like" or "one explanation" for a hypothesis, "according to …" for an opinion. "Proven" and "because" need a fact in the registry.
- Keep observations apart from explanations; never call a cause proven.

**Data you can trust.**
- Raw snapshots are immutable; key numbers are checked against raw, derived tables are for convenience. Every external number has a source and a date.
- When several tickets rebuild the same data, build one verified table instead: a one-command rebuild script, a column dictionary in `CONTEXT.md`, flags for known data holes, reconciled against raw on a sample. It is ready when three independent agents have checked it against raw.
- Data traps (gaps, double counts, vendor bugs, immature last days) go into `PITFALLS.md` the day they are found.

**Keep the picture honest over time.**
- A summary across passes has a section "What we learned that we didn't know at the start". An early claim stays only if new evidence stands behind it; otherwise it is marked as the starting hypothesis.
- When asks start slipping (several "partial" or "lost" in `ASKS.md`), run a fine sieve as its own ticket: reread owner messages, our own reports ("not checked", "later", "next pass") and raw materials; every candidate gets a decision with a reason (new ticket, add to report, covered where, dropped why).
- Default output of a pass is a markdown report in `docs/research/`. Slides only when the work has an arc from idea to verified findings.
