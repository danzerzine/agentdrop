# Push loop: the agent comes to the owner, not the other way round

Status: draft for the first implementation pass, 27.09.2026.

## Why

Owner, 27.09.2026: «я не хочу быть диспетчером клянусь, я хочу наоборот чтобы агент меня теребил по задачам и желательно приходил уже с чем-то за что есть зацепиться».

What the owner's ~2000 messages to agents across their projects show:

- Dozens of status questions: "what's next", "are you done", "did we push", "which ticket are you on", "what do I type after /clear". The answer lives inside one session, and there are often six or more sessions on one project at a time.
- About 30 manual relays: the owner copies a judge's verdict into the implementer's chat and back, or carries messages between an agent on one machine and an agent on another.
- Bare codes ("what about P15") force the owner to open a markdown link. In the chat that link opens a diff view with dozens of changed files, and then they have to find the item and remember the context.
- Asks get lost when one message carries five topics. Long sessions with one topic piled on another get expensive and lose depth.

## What v1 is

Five small pieces. Each works without the ones after it. Plain files, stdlib Python, added to the single `agentdrop` script. Workflow state is JSON; project knowledge stays in the existing docs.

1. **`agentdrop status [--json]`**, deterministic, no LLM. It reads the project's TODO, STATE, QUESTIONS and LOG, plus ASKS in research mode, then git and the claims (below). Sections:
   - **Waiting for you:** open questions with their context quoted, and a recommended answer if the doc has one.
   - **Running now:** claimed tickets, which session, since when. A claim is marked stale after N hours.
   - **Done since you last looked:** LOG entries after a saved timestamp.
   - **Next up:** the top unclaimed tickets by priority, each with its "why" line.

   Every item leads with its meaning in words, with the code in parentheses.
2. **Claims:** `agentdrop claim B41` and `agentdrop release B41` write and remove `docs/.claims/B41.json` (session, start time, branch), which is gitignored. The charter tells agents to claim a ticket at the start of a pass and release it at the end. Two sessions can no longer take the same ticket or edit the same docs unknowingly.
3. **Owner brief and notifier:** `agentdrop brief` turns status into one self-contained message for a phone screen. Delivery is a command set in `~/.agentdrop/config` (for example `notify = "~/bin/tg-send"`); the default prints to stdout. The same format is written into the charter for the end of every pass: what happened, the key number or draft, options with the agent's pick, and what happens if nobody answers. The brief quotes content directly and links only to rendered pages, never to raw markdown files. One bot can carry both infrastructure alerts and briefs; every message starts with the project name and its kind (failure, brief, decision needed). Each item that needs the owner goes as its own short message, never one long sheet. The owner answers by replying to that message (Telegram's reply-to-message): the bot keeps a map from message id to the project, doc and item, and writes the answer under the item as a thread comment (`> **Name, dd.mm hh:mm:** …`), which agents already read and answer. Bot settings live in `~/.agentdrop/telegram.env` (mode 600): `TG_BOT_TOKEN`, `TG_CHAT_ID`, and `TG_RELAY_URL` / `TG_RELAY_KEY` for a machine that can't reach `api.telegram.org`. Checked 27.09 on the owner's Mac: direct sends work, and `getUpdates` returns the owner's reply with `reply_to_message.message_id` of the bot's message. The same bot sends server alerts; only agentdrop may read its updates, or replies get lost. Owner, 27.09: «мой идеальный интерфейс… когда я вижу какой-то момент в стене текста и могу пальцем показать… и ответить сразу, обмениваться простынями я просто умираю».
4. **`agentdrop accept B41`**, the acceptance loop:
   1. Run the project's checks, listed in a small `docs/checks` file with one command per line (tests, lint, `check_docs.sh`, number reconciliation). If one fails, the failure output goes back to the worker and no judge is called.
   2. If the checks pass, start a fresh judge headless (`claude -p`, the `acceptance-judge` agent). Give it the ticket's "why" quote, the spec, the diff since the claim started and the check output, but not the worker's own report. It returns JSON: `{"verdict": "PASS|REJECT|BLOCKED", "findings": [...]}`.
   3. On REJECT, a worker gets the findings and repairs. At most 2 cycles, then the ticket goes to the owner as a brief.
   4. On PASS, send a brief. The worker updates LOG, STATE and TODO as the charter already says.

   Run state lives in `docs/.runs/B41.json` (gitignored), one entry per step with the exit code and a pointer to the output. After a crash the loop resumes at the last finished step and never pretends a dead process is still alive.
5. **Dispatcher:** a scheduled run (launchd, or the Claude desktop scheduled tasks). It sends a morning brief across the registered projects, plus event briefs when a pass ends, a decision is due or a run is blocked. At most 6 messages a day, silent from 23:00 to 09:00. On its own it starts only tickets marked `autonomous` in TODO, and only when nothing else holds a claim. It takes each one through `accept` and then reports. Everything else it proposes with a draft plan.

## Not in v1

No task graph, parallel workers, git worktrees per worker, vendor runner abstraction or Herdr. No daemon, no database. The worker and judge commands are plain strings in the config (`claude -p …`, `codex exec …`). Revisit when the autonomous queue is limited by time rather than by trust.

Next after v1, owner's idea 27.09: a Telegram Mini App on the same bot for reading whole docs: tap any item or paragraph, answer right there, the comment lands under it as a thread. The base exists: one pilot's local docs reader already puts a "comment" button under every item and writes the thread line; the Mini App is that reader moved into the kit and served over HTTPS behind Telegram login.

## Invariants

- Python decides order, retries, limits and routing; an LLM only does the work and gives the verdict.
- The judge never sees the worker's self-assessment.
- Nothing becomes a DECISION without a named human; the dispatcher never marks the owner's choices for them.
- Deploys to production, messages to other people and anything paid need the owner's explicit yes, even for `autonomous` tickets.
- Every message to the owner stands on its own: meaning first, the code in parentheses, content quoted inline.

## Pilot

Two of the owner's projects, one of each kind: a research project where checks are number reconciliation and the claims registry, and a web app with tests and a beta server. Their paths go in the kickoff prompt, not in this public file.

## Acceptance

Against the owner's words above:

1. In both pilots, `agentdrop status` answers "what's next / what's running / what waits for me" with no chat round-trip. Every item is readable without opening a file.
2. In the web app pilot, one real ticket goes worker → checks → judge → (repair) → accepted with no copy-paste by the owner, and the owner gets the result as a Telegram brief.
3. For one day, the owner gets a morning brief and event briefs and doesn't have to ask "what's next".

## Order of passes

1. `status`, `claim`/`release`, charter rules for claims and the pass-end brief. Pilot in both projects.
2. `brief` and the notifier (Telegram through the owner's existing bot relay). Done 27.09: a head message plus one message per waiting item, at most 5 per brief; an item comes again when it changes or after 24 hours unanswered. Replies are collected by `status`, `brief --send` and `agentdrop replies`, so there is still no daemon; the bot confirms each saved answer, and an answer to an item closed in the meantime becomes a new item in QUESTIONS, and so does a reply to the head message. A reply to the bot's confirmation continues the same thread. Checked live 27.09: the owner's reply to an item landed under it in the research pilot. Owner, 27.09, on the first layout: «сейчас это выглядит как распечатка логов»; in a chat without bubbles the messages ran together. Now each message opens with a numbered header ("НУЖНО РЕШЕНИЕ, 2/5"), the context sits in a quote block, done work folds into an expandable quote, and long folder names get a short alias (`alias.<folder> = name` in the config).
   Owner, 27.09, after a reply about the bot landed under a ticket: «тут с routing надо поработать… it's a chat app after all». So each chat message goes through a router: a short model call (Haiku via `claude -p`, about 10 s) labels it item / project / agentdrop, and Python files it; the bot's confirmation has buttons to move it. Checked on the owner's 7 real messages of 27.09: all routed right. Items that need only an OK carry OK / Not OK buttons (owner's request). For buttons to answer at once there is an optional listener, `agentdrop replies --service on` (launchd): the one exception to "no daemon", and it only moves the owner's words into docs.
   Harvest of the owner's FEEDBACK, 27.09: «я ни черта не понял… они краткие и ссылаются за нужным контекстом в другие файлы» → charter rule: a question for the owner quotes its draft and options inline; the router files such a message under the item and keeps a copy for agentdrop. «можно такие штуки сразу сопровождать картинкой было — станет» → pictures an item names go as photos under it. «что дальше от меня нужно и какие вещи сейчас в пайплайне» → a "status" route: the bot answers with a board per project they mean.
3. `accept` in the web app pilot, then the research variant.
4. The dispatcher on a schedule.
5. Harvest: generalize whatever the pilots taught into the public kit and README.
