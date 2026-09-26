# agentdrop

**Recursive self-improvement for humans.**

AI people use that phrase for a model that makes itself smarter. agentdrop runs the same loop through you. Every project you do with a coding agent teaches something: a rule after a mistake, a trap in the data, a better way to ask. agentdrop catches those lessons in files as you work, lifts the ones that matter beyond one project into your own rules, and hands those rules to every agent in the next project. Each project starts smarter than the last, and so do you.

```
you work ──► the agent writes docs as it goes ──► lessons pile up in LOG, CONVENTIONS, PITFALLS
   ▲                                                              │
   │                                  every few passes the agent offers a harvest
   │                                                              ▼
every project and harness ◄── agentdrop sync ◄── your rules (~/.agentdrop) ──► upstream, if you share
```

It's built for people who think faster than they can keep track. Nothing depends on holding things in your head: every ask, decision and trap lands in a file the next session reads, and the agent is reminded to look.

Under the hood it's plain: one set of working rules and one command. After that, Claude Code, Codex, Gemini CLI, OpenCode and Command Code all read the same instructions, and each project gets a docs layout that agents keep tidy. Projects that explore the unknown can add a research mode on top.

```sh
agentdrop .                 # set up the current project
agentdrop --research .      # same, with research mode
```

The script is a single Python file with no dependencies and never overwrites what you wrote.

## Install

```sh
git clone https://github.com/danzerzine/agentdrop
python3 agentdrop/agentdrop --install
```

This copies the script to `~/.local/bin` and creates `~/.agentdrop/COMMON.md` (your rules) and `~/.agentdrop/kit/` (the project skeleton). It then syncs the rules into every harness's global config:

| Harness | Where the rules go |
|---|---|
| Claude Code | `~/.claude/rules/agentdrop-common.md` |
| Codex | `~/.codex/AGENTS.md` (or `AGENTS.override.md` if you use one) |
| Gemini CLI | `~/.gemini/GEMINI.md` |
| OpenCode | `~/.config/opencode/AGENTS.md` |
| Command Code | `~/.commandcode/AGENTS.md` |

Existing files keep their content. agentdrop only adds or updates a block between `<!-- AGENTDROP:… -->` markers and backs up every file to `~/.agentdrop/backups/` before it touches it.

Run the same command again after `git pull` to update. Files agentdrop installed and you never touched are replaced with the new versions. Files you edited stay as they are, and the new version lands next to them (`~/.agentdrop/kit.new/`, `COMMON.new.md`) for your agent to merge.

### Windows

```powershell
git clone https://github.com/danzerzine/agentdrop
python agentdrop\agentdrop --install
```

On Windows, `--install` puts three files into `%USERPROFILE%\.local\bin`:
- `agentdrop.py`;
- `agentdrop.cmd`, the launcher for cmd and PowerShell;
- `agentdrop`, the launcher for Git Bash.

The launchers look for a working `python`, then fall back to `py -3`. That way they skip the Microsoft Store stub and cope with pyenv-win's `.bat` shims.

The folder goes onto your user PATH directly in the registry, not through `setx`. `setx` truncates a long PATH. Open a new terminal afterwards.

Other Windows behaviour:
- Files keep their line endings and BOM.
- The console prints ASCII when it can't show `✓`.
- The kit's shell scripts are written with LF, because a clone with `core.autocrlf=true` would give them CRLF.
- `agentdrop edit` uses `$EDITOR`, then the `.md` association, then Notepad.
- The docs question needs a console. If Git Bash skips it, run agentdrop from cmd or PowerShell, or pass `--docs`. The `.git-docs` commands it prints use double quotes, so they paste into cmd as well.

The docs guard, the git hook and the SessionStart reminders need `bash`. Git for Windows ships it, and Claude Code uses it for hooks. The research reminder also needs Python; the hook tries `python3`, `python` and `py -3` and skips the Microsoft Store stub.

## Everyday use

```sh
agentdrop edit              # open your rules (COMMON.md)
agentdrop sync              # push edited rules to all harnesses
agentdrop .                 # set up or refresh the project you're in
agentdrop ~/code/app        # same, for another path
agentdrop --dry-run .       # show what would change
agentdrop --docs separate . # keep the docs out of the code repo (see below)
agentdrop --research .      # turn research mode on (the first setup asks)
agentdrop --no-research .   # turn it off; the registries stay
```

## What a project gets

```
AGENTS.md                  your project notes on top, managed block below
CLAUDE.md / GEMINI.md      one-line @AGENTS.md imports
docs/
  CONTEXT.md               what the product is, who uses it, glossary
  DECISIONS.md             choices a named person made: what, why, what was rejected
  CONVENTIONS.md           "we always do it this way"
  PITFALLS.md              traps someone already fell into
  OPERATIONS.md            how to run, deploy, access (no secrets)
  STATE.md                 what works right now
  TODO.md                  tickets B1, B2… with P0–P3, only what remains
  QUESTIONS.md             what the agent needs a human for; closed items kept a week
  LOG.md                   one entry per finished pass
  specs/ research/ archive/
  reviews/inbox/           drop raw reviews here
.claude/skills/review-intake/
.claude/skills/harvest/    moves lessons from this project into your rules
.claude/settings.json      Claude Code hooks: the guard on Stop, reminders on SessionStart
scripts/check_docs.sh      guard: markdown only where the map allows
.githooks/pre-commit       runs the guard on staged files
```

The docs templates are created once and are yours from then on. The files agentdrop owns (the guard, the git hook, the skills, the research scripts and agents) are refreshed on every `agentdrop .`, with the old copy backed up.

The managed block in `AGENTS.md` holds only the charter: where each kind of note goes, how to finish a pass, and which file wins when instructions conflict. A new entry in `DECISIONS.md` has to end with a `Decided: who, where, quote` line; the guard rejects it otherwise, so agent defaults land in `QUESTIONS.md` instead of posing as decisions. Your common rules stay in the global configs, so no session loads them twice. Anything project-specific goes above the block. agentdrop never rewrites that part.

## The loop: harvest

A project keeps learning: a convention after a mistake, a trap, a decision about how to work. Most of it is about that project. Some of it is about working at all, and that part should reach every project.

When five passes have piled up in `docs/LOG.md` since the last harvest, a SessionStart hook tells the agent, and the agent offers a harvest in one line. Other harnesses follow the same rule from the charter. The `harvest` skill then works like review intake, in two steps:

1. It reads what the project gained since the last harvest, keeps the lessons that would change how an agent works anywhere, rewrites them without project names and checks them against your rules. You get a numbered table: the lesson as it will be written, where it goes (your `COMMON.md`, the kit charter, research mode), whether it's general enough to share.
2. You answer "ok" or "3 → personal, 5 drop". It writes into `~/.agentdrop/`, runs `agentdrop sync` so every harness picks it up, and moves the harvest marker in `LOG.md`.

If you installed from a clone, agentdrop remembers where it is (`~/.agentdrop/source`). Lessons you mark as general are then prepared there on a branch with the tests run, and pushed only after a second OK. Without a clone, the skill gives you the text of an issue for this repository.

## Research mode

Some projects start from a question nobody can answer yet: why traffic fell, what a ranking algorithm rewards, which of forty ideas holds up. There the usual failure is not a bug. It's drift. The agent answers a slightly different question from the one asked, half of the owner's asides never become tickets, a correlation from week one turns into a "fact" by week three, and each pass rebuilds the data its own way. Research mode is a set of rules and registries that came out of such a project after all of this happened.

```sh
agentdrop --research .      # or answer "y" when the first setup asks
```

It adds a second managed block to `AGENTS.md` and these files:

```
docs/ASKS.md               every research ask of the owner: verbatim, message id, mode, ticket, status
docs/HYPOTHESES.md         hypothesis, source, prediction written before computing, verdict
docs/CLAIMS.md             claims that leave the project, with an evidence level and who checked
scripts/owner_asks.py      owner messages from Claude Code transcripts since the last check
.claude/agents/skeptic.md           tries to refute a claim before it goes out
.claude/agents/acceptance-judge.md  accepts a pass against the owner's quote, not the report
```

The rules, in short:
- Every ticket carries `Why:` with the owner's words and a date. A pass closes only when an independent judge confirms the report answers that quote; the rest goes into "Not answered" and a new ticket.
- The agent tags each ask as a question, a "wide" ask, an idea, an errand or a correction. A wide ask is accepted by breadth: where the agent searched and what it found beyond the owner's example.
- Collect first, filter later. Correlations are recorded as experiment candidates, and every report ends with **Nearby**: two to five neighbouring topics with a number each, for the owner to pick from.
- Hypotheses get one standard check: within a segment, a placebo on an outcome the feature shouldn't move, a minimum sample. The prediction is written before the numbers.
- Claims carry a level (fact on our data, observation, hypothesis, someone else's opinion) and change it only through the registry. The skeptic's verdict is recorded next to each: holds, holds narrowed, withdrawn. In texts for people the level shows in the words: "we counted", "the data shows", "it looks like".
- When several tickets rebuild the same data, the project builds one verified table instead, checked against raw by three independent agents.
- A summary across passes says what we learned that we didn't know at the start. An early guess stays only with new evidence behind it.

`owner_asks.py --new` reads Claude Code transcripts, including messages sent while the agent was busy, which naive readers miss. In Claude Code the SessionStart hook runs it for you and tells the agent how many of your messages still wait for a row; other harnesses reread the conversation. The mode lives in the `AGENTS.md` block: rerunning `agentdrop .` keeps it, `--no-research` removes the block and leaves the registries in place.

The skeptic and the claims registry have already been through a real project: its first run narrowed all three headline claims it checked and showed that one "step change" was noise. The hypotheses registry is the newest part and is marked experimental in the charter; harvest will refine it as projects use it.

## Docs in the code repo, or not

The first time agentdrop sets up a git project, it asks where the docs and agent files (`docs/`, `AGENTS.md`, `GEMINI.md`, `CLAUDE.md`, `.claude/`, `.githooks/`, `.docs-allow`, `scripts/check_docs.sh`) should live:

1. **track**: in the project's own repo, committed with the code. This is the default.
2. **separate**: in a second, local-only git in the same folder, `.git-docs`. The code repo ignores those paths through `.git/info/exclude`, the pre-commit guard moves to `.git-docs`, and `AGENTS.md` tells agents to commit docs with `git --git-dir=.git-docs --work-tree=. commit`. Nothing from it reaches GitHub.
3. **local**: the same paths ignored by the code repo, with no version control at all.

The answer is saved in the repo's local git config (`agentdrop.docs`), so later runs keep the docs where you put them. A folder that already has a `.git-docs` counts as "separate". To change your mind, run `agentdrop --docs track|separate|local .`. agentdrop never deletes `.git-docs` and never untracks files by itself. If docs were already committed to the code repo, it prints the `git rm --cached` command; the old commits keep them until you rewrite history with `git filter-repo`.

Without a terminal (CI, a pipe) there is no question: the docs stay in the code repo for that run and nothing is saved. Pass `--docs` there.

## Reviews without the mess

You ask three models to critique the project and end up with three overlapping markdown files in random places. Drop them anywhere, then tell your agent:

> process the reviews

The `review-intake` skill then works in two steps:

1. It collects every review file, splits them into single findings and merges duplicates across models (with a "who said it" column). It checks each finding against `DECISIONS.md` and the existing tickets, then assigns P0–P3 on its own scale and writes one summary into `docs/reviews/inbox/`. Then it stops and waits for you.
2. You answer "ok" or give corrections like "7 → P1, 12 → reject". After that it files the tickets, moves the raw reviews to `docs/archive/reviews/<date>/` and logs the pass.

`check_docs.sh` keeps new stray files from piling up. The pre-commit hook blocks a commit that adds markdown outside the map. In Claude Code, a Stop hook warns you without blocking the agent. If a project needs extra places for docs, list them as regexes in `.docs-allow`.

## Talk to the agent in your docs

Comment right under a ticket or a question, as a quote: `> **Name, 24.09 12:30:** text`. The next session answers in the same thread and commits it with its pass. End a thread with `_Thread closed._` and the agent finishes the item by the project's rules: removes the ticket, logs the pass, records the decision.

## Customize

- **Rules:** `agentdrop edit`, then `agentdrop sync`.
- **Charter and templates:** edit files in `~/.agentdrop/kit/`, then run `agentdrop .` in a project. Templates are copied only when missing; the charter block and the files agentdrop owns are refreshed every time.
- **Or let harvest do it:** most edits to your rules come from your own projects; see "The loop" above.
- **Research mode:** its block and files live in `~/.agentdrop/kit/modes/research/`. Edit `CHARTER.md` there and rerun `agentdrop .` in research projects to refresh the block.

## Older layouts

If a project already keeps `HANDOFF.md`, `PROGRESS.md` and similar files in the root, agentdrop leaves them as they are and doesn't add the `docs/` kit. Ask your agent to migrate the notes to `docs/`, then run `agentdrop .` again.

## License

MIT
