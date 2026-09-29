# Tickets page

One page with every ticket and every question for you across the projects. Each item opens on
its own link (`#<project>-<code>`, e.g. `#sd-B110`, `#ss-B101`; questions `#<project>-q<hash>`), and
the owner answers by commenting on the page; a comment sent to Claude reaches the session that watches it.

Artifact: https://claude.ai/artifact/JgBHHXBkfeRNxJ5dQk9BXM (private). The hourly scheduled refresh is retired since
29.09 (a live panel shows the same board); by hand:

    agentdrop tickets --docs tools/tickets-page/docs.json > tools/tickets-page/tickets.json

then publish `tools/tickets-page/index.html` to the artifact's URL with `tickets.json`, `triage.json` and
`docs.json` as files beside it. `docs.json` holds the project .md files the items mention in backticks, so a
path like `docs/HYPOTHESES.md` in a ticket opens that document on the page (`#doc-sd-docs-HYPOTHESES.md`).
Screenshots an open ticket names (a file or a folder in backticks) are copied to `img/` as JPEG, at most
1600 px, and listed in `docs.json`; publish every `img/*` file too. Themes and my ordering of the queue live in
`themes.json`. Closed tickets come from LOG.md so a code in any ticket links somewhere. The json files are generated and
not committed (the repo is public).
