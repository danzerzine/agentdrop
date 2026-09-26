# DECISIONS — decisions that must not be undone by accident

_Chronological, newest at the bottom. Tag decisions that change only with their author as `[model]`._

_An entry goes here only if all three hold:_

1. _**A human chose.** Between two or more options, and the entry names them and the source.
   A passing remark, "go ahead" on an agent's list, or silence is not a choice. An agent is never the author._
2. _**Costly to forget.** Undoing it by accident would force rework or spoil the numbers._
3. _**It is not something else.** A bug fix goes to `PITFALLS.md`, screen looks to the design system doc,
   servers and builds to `OPERATIONS.md`, facts about data or people to `CONTEXT.md`, "we always do X"
   to `CONVENTIONS.md`, what was done to `LOG.md`._

_A rule the agent made up goes to `QUESTIONS.md` as an agent default and lands here only once a human picks it.
An entry without a named author can't be cited to reject a review or the owner's request._

_Format: `## DD.MM.YYYY — title`, then Decision, Why, Rejected, Don't undo, and the last line
`Decided: who, where, quote`; `scripts/check_docs.sh` blocks new entries without it. Up to 15 lines, details in a spec.
A superseded entry moves whole to `DECISIONS.archive.md` the day it is superseded; the new entry names what it replaced._
