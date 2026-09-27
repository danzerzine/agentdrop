# Tickets page

One page with every ticket and every question for Daniyar across the projects. Each item opens on
its own link (`#<project>-<code>`, e.g. `#sd-B110`, `#ss-B101`; questions `#<project>-q<hash>`), and
the owner answers by commenting on the page; a comment sent to Claude reaches the session that watches it.

Artifact: https://claude.ai/artifact/JgBHHXBkfeRNxJ5dQk9BXM (private). Refresh:

    agentdrop tickets > tools/tickets-page/tickets.json

then publish `tools/tickets-page/index.html` to the artifact's URL with `tickets.json` as a file beside it.
`tickets.json` is generated and not committed.
