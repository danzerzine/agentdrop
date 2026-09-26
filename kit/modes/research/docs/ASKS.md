# ASKS — registry of the owner's research asks

_The reverse index to `TODO.md`: there a ticket has `Why:`, here every owner ask has a ticket and a status. An ask is not lost while it has a row here._

Checked up to: — (UTC, as in transcripts)

How to keep it (rule in the `AGENTS.md` research block):
- At the start and end of a pass: `python3 scripts/owner_asks.py --new` lists owner messages after the "Checked up to" mark. Give every research ask a row, then move the mark.
- Mode (the agent sets it): **question**, **wide**, **idea**, **errand**, **correction**.
- Status: **answered**, **partial** (the rest is in the ticket), **lost**, **reframed** (the report answered another question), **in progress**, **dropped** (by the owner).
- Infrastructure chatter and "ok"s don't go here. Closing a ticket, update the status here.

| # | Date, msg | Mode | Verbatim | Ticket | Status |
|---|---|---|---|---|---|
