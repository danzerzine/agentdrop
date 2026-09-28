---
name: grill
description: Turn an idea, a pasted brief or a pile of scattered asks into a shared plan by questioning the owner in rounds, each question with the agent's recommended answer, and writing every answer down as it lands (glossary, decisions, then a spec and tickets). Use when the owner brings something new and fuzzy, when several asks pull in different directions, when a brief contradicts how the project works, or when asked to grill, interview or "разобрать по вопросам".
---

# grill

The owner thinks faster than they write things down: an idea arrives as a paragraph, a pasted brief or five asks in one message. Building from that means guessing, and the guesses surface weeks later as rework. This skill replaces the guessing with a short interview. The owner answers by pointing at an option; every answer goes into the project's docs at once, so the picture holds together on paper, not only in one chat. Adapted from Matt Pocock's `grilling` and `domain-modeling` skills (github.com/mattpocock/skills, MIT).

## Before the first round

1. Read the input whole: the brief, the owner's messages, the raw asks it concerns (open items in `docs/TODO.md` and `docs/QUESTIONS.md` that touch the topic). Quote the owner's own words later; never paraphrase them into a decision.
2. Read `docs/CONTEXT.md` (the glossary especially), the `docs/DECISIONS.md` entries in the area, and the code the topic touches.
3. Look for contradictions yourself: between the brief and the code, the brief and a past decision, two asks. Each one is a question for round one.

## Research projects

When the project exists to find things out (a study, an audit, a market or data investigation) rather than to build something, its tickets close without telling the owner what was learned, and after a few autonomous days the findings reach them in scraps. Add these to round one, each with your pick like any other question:

1. **Blocks.** What blocks of knowledge does the research split into, and what is the one main question of each? Propose the split from the brief and the existing docs; four to seven blocks is usual.
2. **Key questions.** Which questions inside each block matter, and what counts as answered? A block's progress is the share of its key questions answered (a partial answer counts half), never the share of tickets closed.
3. **Findings on close.** When a ticket closes, the agent writes one or two sentences on what was found out, with the numbers, and names the block it feeds. Propose where this line lives (the ticket's close note, `docs/LOG.md` or a findings file).
4. **The map.** Where the map of blocks, questions and answers lives, and who updates it when a finding lands. Propose one file in `docs/` that agents keep current.
5. **Briefing.** How the owner wants to hear about progress: a daily or evening briefing (what was found out, what waits for them, whether the course should change, how each block moved), an on-demand catch-up for a chosen period, or both.

Write the answers into the spec and the charter's docs map, so later passes keep the map and the findings line going without being asked.

## Rounds

Map the plan as a tree of decisions: each decision opens the ones that hang off it. The **frontier** is every decision whose prerequisites are settled. Ask the whole frontier in one round, usually 3–6 questions, then wait. A question whose answer depends on another question in the same round waits for the next round.

Format each question so it can be answered with a word:

```
❓ **Q1. <short title>.** <the question in plain words; the options as a) b) c) when there are options; what the code or data says, when it matters>

➡️ <your pick and why, in one or two sentences>
```

- Facts are yours, decisions are the owner's. Never ask what you can look up: files, code, logs, what is installed, how many tickets. Look it up first, and bring a fact that changes a question (for example a limit already at 68%) into the round.
- Challenge fuzzy words. When the owner says "status", "board" or "review", propose one precise term and the words to avoid.
- Stress-test with a concrete scenario when a boundary is unclear: "the judge rejects it a third time at night; who sees it, and when?"
- Keep your own technical choices out of the questions; list them at the end of a round as "I'll decide these unless you object".
- The owner's answer may be a copied recommendation, a letter or a new idea. A new idea reshapes the tree; recompute the frontier.

## Write as answers land

After each round, before the next one:

- **Glossary:** each settled term goes into `docs/CONTEXT.md` under Glossary: the term, one or two sentences on what it is (not how it is built), and the words to avoid. Only terms of this project, never general programming words.
- **Decisions:** a choice that is hard to undo, would surprise a later reader and had real alternatives goes into `docs/DECISIONS.md` in its format, with the owner's words and the question number in the `Decided:` line. Easy-to-reverse choices stay in the spec.
- Commit these with a short message; the round's answers are now safe even if the chat ends.

## Finish

The interview ends when the frontier is empty: every branch visited, nothing silently assumed. Say so, list the decisions you took yourself, and ask the owner to confirm the picture. Then:

1. Write the spec to `docs/specs/B<n>-<name>.md`: the problem and the solution from the owner's side, a long numbered list of user stories ("As <who>, I want <what>, so that <why>"), the decisions (modules, interfaces, data, what is reused), how it will be tested (the highest seams that show real behavior, and the prior tests to copy), and what is out of scope. Use the glossary's terms throughout.
2. Offer to cut it into tickets in `docs/TODO.md`: thin slices that each give something the owner can see or check, ordered with `После: B<n>` / `After: B<n>` where one waits for another, each with its "why" quote and its one-line summary (plain words, at most 100 characters, no codes or paths). Show the list first; file after the owner's OK.
3. The raw asks the spec covers get a line under them pointing to the spec, and close once the tickets exist.
