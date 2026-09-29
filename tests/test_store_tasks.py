"""End-to-end: a project whose tasks live in the store (`tasks.<folder> = store`). An agent takes,
asks, hands in and gets a task accepted with `agentdrop task` alone; two sessions never get the same
task; the board and the tickets page read from the store say what they said from the markdown; a
markdown project is left alone.

    python3 -m unittest discover tests
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TODO = """# TODO — tickets

## Now

- B7 P1 — Fix login on Safari. Why: «I can't log in from the iPad» (M12, 20.09). Repro on iOS 18. Spec: docs/specs/login.md.
- **B8 (P0). Deploy script.** Needs the new server. Waiting for the owner's OK on the server.
- P2: B9 export to CSV. Why: «Sasha wants a spreadsheet» (M20, 21.09).
- B14 P1 — Price feed. Waiting for the partners: the file format.

## Next

- **B10 [autonomous]. Dark theme.** Follow the system setting.
  Summary: The site turns dark when the phone does.
- **B12 (P2). Share the export.** After: B9.
- **B15 (P2). Tooltip copy.** Short text.

  > **Agent, 22.09:** Which wording?
  > **Owner, 22.09:** the short one.

## Later

- B11 P3 — Old reports cleanup. Deferred until the new server.
"""

QUESTIONS = """# QUESTIONS — what waits for a human

## For the owner

- **Q-2. Which chart library.** Two options: Recharts or ECharts. I recommend Recharts: we already use it.
- **Keep the beta open?** Beta is public since 20.09.

  > **Owner, 21.09:** yes, keep it.

- **Old question.** Settled.

  > **Owner, 20.09:** done

  _Thread closed._
- **R-1. Kept UTC in exports.** R-1, revertible: the rest of the code uses UTC.

## For others

- **Design (B9):** column order for the CSV.
"""

LOG = """# LOG — work log

## 27.09 — B6 login page redesign

- New login page, tests 40 green.

## 26.09 — B5 fixed the chart tooltip

- Tooltip stays on screen on phones.
"""

JUDGE = """import json, sys
sys.stdin.read()
print(json.dumps({'type': 'result', 'structured_output': {'verdict': 'PASS', 'summary': 'Safari logs in', 'findings': []}}))
"""

JUDGE_REJECT = """import json, sys
with open({log!r}, 'a', encoding='utf-8') as f:
    f.write(sys.stdin.read() + '\\n=====\\n')
print(json.dumps({{'type': 'result', 'structured_output': {{'verdict': 'REJECT', 'summary': 'Safari still drops the cookie',
    'findings': [{{'severity': 'blocker', 'what': 'the cookie is lost on Safari'}}]}}}}))
"""


class StoreProject(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.home, self.root, self.db = base / "home", base / "proj", base / "tasks.sqlite3"
        (self.root / "docs" / "specs").mkdir(parents=True)
        (self.home / ".agentdrop").mkdir(parents=True)
        for name, text in (("TODO.md", TODO), ("QUESTIONS.md", QUESTIONS), ("LOG.md", LOG)):
            (self.root / "docs" / name).write_text(text, encoding="utf-8")
        (self.root / "docs" / "specs" / "login.md").write_text("# Login\n", encoding="utf-8")
        (self.root / "docs" / "checks").write_text("true\n", encoding="utf-8")
        (self.home / "judge.py").write_text(JUDGE, encoding="utf-8")
        self.config(f"owner = Owner\njudge = {sys.executable} {self.home / 'judge.py'}\n")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "AGENTDROP_SESSION", "AI_AGENT")}
        self.env.update(HOME=str(self.home), USERPROFILE=str(self.home), AGENTDROP_STORE=str(self.db),
                        AGENTDROP_OFFLINE="1", GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "start")
        self.docs = self.snapshot()

    def config(self, text, append=False):
        with open(self.home / ".agentdrop" / "config", "a" if append else "w", encoding="utf-8") as f:
            f.write(text)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, env=self.env, check=True)

    def snapshot(self):
        return {n: (self.root / "docs" / n).read_bytes() for n in ("TODO.md", "QUESTIONS.md")}

    def run_ad(self, *args, session=None):
        env = dict(self.env, **({"AGENTDROP_SESSION": session} if session else {}))
        return subprocess.run([sys.executable, str(REPO / "agentdrop"), *args], cwd=self.root, env=env,
                              text=True, capture_output=True, stdin=subprocess.DEVNULL)

    def ok(self, *args, session=None):
        r = self.run_ad(*args, session=session)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def to_store(self):
        self.ok("store", "import")
        self.config("tasks.proj = store\n", append=True)

    def rows(self, sql, *params):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()

    def state(self, tid):
        return self.rows("SELECT state FROM tasks WHERE id = ?", tid)[0]["state"]


class StoreTasks(StoreProject):
    def test_board_and_page_from_the_store_equal_the_markdown(self):
        md = {k: self.ok(*k.split()) for k in ("status", "status --json", "tickets .")}
        self.to_store()
        for n in ("TODO.md", "QUESTIONS.md"):   # the store alone: the files are never read
            (self.root / "docs" / n).rename(self.root / "docs" / f"{n}.off")
        st = {k: self.ok(*k.split()) for k in md}

        # the first line carries the time, the git line counts the two files moved away
        body = lambda text: [l for l in text.split("\n")[1:] if not l.startswith("git:")]
        self.assertEqual(body(st["status"]), body(md["status"]))
        self.assertRegex(st["status"], r"waiting for other people: Price feed.*\(B14\)")

        def plain(v):   # where an item lives (a file or the store) and the clock are not the task
            if isinstance(v, dict):
                return {k: plain(x) for k, x in v.items() if k not in ("doc", "key", "generated", "git")}
            return [plain(x) for x in v] if isinstance(v, list) else v
        self.assertEqual(plain(json.loads(st["tickets ."])), plain(json.loads(md["tickets ."])))
        self.assertEqual(plain(json.loads(st["status --json"])), plain(json.loads(md["status --json"])))
        docs = {i["doc"] for i in json.loads(st["tickets ."])["items"] if i["state"] != "done"}
        self.assertEqual(docs, {"store"})

    def test_take_ask_answer_handin_accept_with_commands_only(self):
        self.to_store()
        out = self.ok("task", "take", session="s1")   # the next one: the owner answered B15 last, the agent's move
        self.assertTrue(out.startswith("Tooltip copy (B15, P2)"), out)
        self.assertIn("Owner, 22.09: the short one.", out)
        self.assertNotIn("Dark theme", out)   # one task, not the backlog

        out = self.ok("task", "take", "B7", session="s1")
        self.assertIn("why: «I can't log in from the iPad» (M12, 20.09)", out)
        self.assertIn("files it names: docs/specs/login.md", out)
        self.assertEqual(self.state("B7"), "running")
        self.assertTrue((self.root / "docs" / ".claims" / "B7.json").is_file())

        self.ok("task", "comment", "B7", "Safari rejects the cookie", session="s1")
        self.ok("task", "ask", "B7", "Drop the old login page?", "--option", "Yes, drop it", "--option", "Keep it",
                "--pick", "1", "--context", "New login: the new page is live", session="s1")
        self.assertEqual(self.state("B7"), "waiting_you")
        self.assertFalse((self.root / "docs" / ".claims" / "B7.json").exists())   # the run let go
        board = self.ok("status")
        waiting = board.split("## Waiting for you", 1)[1].split("##", 1)[0]
        self.assertIn("Fix login on Safari (B7, P1)", waiting)
        self.assertIn("waits: Drop the old login page?", waiting)

        self.ok("task", "comment", "B7", "yes, drop it", "--as", "Owner")
        self.assertEqual(self.state("B7"), "queued")   # answered: the agent's move

        self.ok("task", "take", "B7", session="s2")
        (self.root / "login.py").write_text("fixed = True\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "B7 fix")
        self.assertIn("next: `agentdrop accept B7`", self.ok("task", "handin", "B7", "cookie fixed", session="s2"))
        self.assertEqual(self.state("B7"), "accepting")
        out = self.ok("accept", "B7")
        self.assertIn("PASS", out)
        self.assertEqual(self.state("B7"), "done")
        self.assertFalse((self.root / "docs" / ".claims" / "B7.json").exists())
        self.assertNotIn("(B7,", self.ok("status"))
        self.assertIn("p-B7", {i["id"] for i in json.loads(self.ok("tickets", "."))["items"] if i["state"] == "done"})

        events = self.rows("SELECT author, what FROM events WHERE task = 'B7' AND author != 'import' ORDER BY id")
        authors = {e["author"] for e in events}
        self.assertTrue({"Owner", "judge"} <= authors, authors)
        self.assertTrue(any(a.endswith(" s1") for a in authors) and any(a.endswith(" s2") for a in authors), authors)
        self.assertEqual([c["author"] for c in self.rows("SELECT author FROM comments WHERE task = 'B7' ORDER BY n")],
                         ["shell", "shell", "Owner", "shell", "judge"])
        self.assertEqual(self.snapshot(), self.docs)   # the markdown was never touched

    def test_second_reject_in_a_row_asks_the_owner_with_two_options(self):
        self.to_store()
        (self.home / "judge.py").write_text(JUDGE_REJECT.format(log=str(self.home / "prompts.txt")), encoding="utf-8")
        self.ok("task", "take", "B7", session="s1")

        def hand_in(k):
            (self.root / "login.py").write_text(f"fixed = {k}\n", encoding="utf-8")
            self.git("add", "-A")
            self.git("commit", "-qm", f"B7 try {k}")
            self.ok("task", "handin", "B7", f"try {k}", session="s1")
            return self.run_ad("accept", "B7")

        r = hand_in(1)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.ok("task", "take", "B7", session="s1")
        r = hand_in(2)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.state("B7"), "waiting_you")
        [ask] = [json.loads(a["ask"]) for a in self.rows("SELECT ask FROM comments WHERE task = 'B7' AND ask != ''")]
        self.assertEqual(ask["kind"], "accept")
        self.assertEqual(ask["options"], ["Accept it as it is", "Rewrite the task"])
        self.assertIn("cookie", ask["q"])
        prompts = (self.home / "prompts.txt").read_text(encoding="utf-8").split("\n=====\n")
        self.assertEqual(len(prompts), 3)   # two judges, one trailing split
        self.assertNotIn("previous verdict", prompts[0])
        self.assertIn("previous verdict", prompts[1])

        r = self.run_ad("accept", "B7")   # no third round
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(len((self.home / "prompts.txt").read_text(encoding="utf-8").split("\n=====\n")), 3)

        self.ok("task", "comment", "B7", "Rewrite the task", "--as", "Owner")
        self.assertEqual(self.state("B7"), "queued")
        self.ok("task", "take", "B7", session="s2")
        r = hand_in(3)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)   # the count starts again after the owner's word
        self.ok("task", "take", "B7", session="s2")
        self.assertEqual(hand_in(4).returncode, 3)
        self.ok("task", "comment", "B7", "a", "--as", "Owner")   # the letter of «Accept it as it is»
        self.assertEqual(self.state("B7"), "done")

    def test_two_sessions_never_get_the_same_task(self):
        self.to_store()
        cmd = [sys.executable, str(REPO / "agentdrop"), "task", "take"]
        procs = [subprocess.Popen(cmd + ["B10"], cwd=self.root, env=dict(self.env, AGENTDROP_SESSION=f"s{i}"),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(5)]
        codes = [p.wait() for p in procs]
        for p in procs:
            p.stdout.close()
            p.stderr.close()
        self.assertEqual(sorted(codes), [0, 1, 1, 1, 1])
        procs = [subprocess.Popen(cmd, cwd=self.root, env=dict(self.env, AGENTDROP_SESSION=f"n{i}"),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(3)]
        firsts = [p.communicate()[0].split("\n", 1)[0] for p in procs]
        self.assertTrue(all(firsts), firsts)
        self.assertEqual(len(set(firsts)), 3, firsts)   # three different tasks
        self.assertNotIn("B10", " ".join(firsts))

    def test_a_live_claim_from_the_markdown_commands_is_respected(self):
        self.to_store()
        self.ok("claim", "B9", session="old")
        r = self.run_ad("task", "take", "B9", session="new")
        self.assertEqual(r.returncode, 1)
        self.assertIn("B9 is held by", r.stderr)

    def test_summary_line(self):
        """Every ticket carries a one-line summary: read from the markdown line, required and checked on
        `task new`, set with `task summary`, given to the tickets page."""
        self.to_store()
        self.assertEqual(self.rows("SELECT summary FROM tasks WHERE id = 'B10'"),
                         [{"summary": "The site turns dark when the phone does."}])
        self.assertNotIn("Summary:", self.rows("SELECT text FROM tasks WHERE id = 'B10'")[0]["text"])
        self.assertEqual(self.rows("SELECT summary FROM tasks WHERE id = 'B7'"), [{"summary": ""}])   # old ones load
        for bad in ([], ["--summary", "Fix B12 in docs/specs/x.md"], ["--summary", "x" * 101]):
            r = self.run_ad("task", "new", "Chart colours", *bad)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("the task was not filed", r.stderr)
        self.assertEqual(self.rows("SELECT id FROM tasks WHERE title = 'Chart colours'"), [])
        self.ok("task", "new", "Which font", "--question")   # a question for the owner needs none
        self.ok("task", "summary", "B7", "People can log in from an iPad again")
        self.assertIn("summary: People can log in from an iPad again", self.ok("task", "show", "B7"))
        self.assertEqual(self.run_ad("task", "summary", "B7", "see B9").returncode, 2)

    def test_the_weeks_main_task_goes_first_and_is_one_per_project(self):
        """`task focus` makes a task the project's main one this week: the one before stops being main, the
        next free task taken is the main one even over a higher priority, `--off` unmarks it."""
        self.to_store()
        self.ok("task", "focus", "B15")
        self.ok("task", "focus", "B9")
        self.assertEqual([r["id"] for r in self.rows("SELECT id FROM tasks WHERE focus != ''")], ["B9"])
        self.assertIn("B15", self.ok("task", "take", session="s1").splitlines()[0])   # the owner's answer first
        self.assertIn("B9", self.ok("task", "take", session="s2").splitlines()[0])   # then B9 over B7's P1
        self.ok("task", "focus", "B9", "--off")
        self.assertEqual(self.rows("SELECT id FROM tasks WHERE focus != ''"), [])

    def test_new_task_states_by_name_and_no_reimport(self):
        self.to_store()
        self.assertIn("✓ B16: Share the chart [Waits for another task]",
                      self.ok("task", "new", "Share the chart", "--after", "B12", "--priority", "P3",
                              "--summary", "People can send the chart to a colleague"))
        self.assertEqual(self.rows("SELECT after FROM links WHERE task = 'B16'"), [{"after": "B12"}])
        self.ok("task", "state", "B16", "Отложена")
        self.assertEqual(self.state("B16"), "deferred")
        self.ok("task", "state", "B8", "waiting_others", "Hosting provider: the new server")
        self.assertIn("waiting for other people: Deploy script (B8)", self.ok("status"))
        self.assertEqual(self.run_ad("task", "state", "B8", "blocked").returncode, 2)
        q = self.ok("task", "new", "Which font", "--question")
        self.assertIn("Decide: Which font [Waits for you]", q)
        self.assertIn("Which font", self.ok("status"))
        r = self.run_ad("store", "import")
        self.assertEqual(r.returncode, 2)   # the markdown is stale now; importing it would undo the above
        self.assertIn("already works from the store", r.stderr)


    def test_a_standing_list_never_closes(self):
        self.to_store()
        self.ok("task", "new", "Ideas", "--theme", "Ideas", "--summary", "Ideas from sessions, kept so none is lost")
        for args in (("task", "state", "B16", "done"), ("task", "handin", "B16")):
            r = self.run_ad(*args)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("standing list", r.stderr)
        self.ok("task", "state", "B16", "deferred")
        self.assertEqual(self.state("B16"), "deferred")

class MarkdownUntouched(StoreProject):
    def test_a_markdown_project_is_left_alone(self):
        before = {k: self.ok(*k.split()) for k in ("status --json", "tickets .")}
        self.ok("store", "import")
        self.config("tasks.other = store\n", append=True)   # another project on the store
        after = {k: self.ok(*k.split()) for k in before}
        for k in before:
            a, b = json.loads(before[k]), json.loads(after[k])
            for d in (a, b):
                d.pop("generated")
                d.get("git", {}).pop("last_commit_age", None)
            self.assertEqual(a, b, k)
        r = self.run_ad("task", "take", "B7")
        self.assertEqual(r.returncode, 2)
        self.assertIn("keeps its tasks in docs/TODO.md", r.stderr)
        self.assertEqual(self.run_ad("task", "where").returncode, 1)
        self.assertIn("claimed", self.ok("claim", "B7", session="s1"))
        self.assertEqual(self.snapshot(), self.docs)


WORKER = """import json, os, re, subprocess, sys, time, uuid
prompt = sys.stdin.read()   # as `claude -p` gets it
sid = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else str(uuid.uuid4())
print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}), flush=True)
tid = re.search(r"^1\\. .*\\((B\\d+), ", prompt, re.M).group(1)
subprocess.run([sys.executable, AGENTDROP_PATH, "task", "take", tid], env=dict(os.environ, AGENTDROP_SESSION=sid),
               stdout=subprocess.DEVNULL)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Half of {tid} done."}]}}),
      flush=True)
child = subprocess.Popen(["sleep", "60"])   # a tool the agent runs: it dies with the run
open(f"child-{tid}.pid", "w").write(str(child.pid))
time.sleep(60)
"""


class Runs(StoreProject):
    """Start a run for one task, stop only that run, continue with what the earlier runs did."""

    def setUp(self):
        super().setUp()
        self.to_store()
        (self.home / "worker.py").write_text(WORKER.replace("AGENTDROP_PATH", repr(str(REPO / "agentdrop"))),
                                             encoding="utf-8")
        self.config(f"pack_worker = {sys.executable} {self.home / 'worker.py'}\n", append=True)
        self.addCleanup(lambda: [self.kill(f.read_text()) for f in (self.root / "docs" / ".runs" / "pack").glob("*.pid")])

    @staticmethod
    def kill(pid):
        try:
            os.killpg(int(pid), 9)
        except OSError:
            pass

    @staticmethod
    def alive(pid):
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return False
        r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
        return not r.stdout.strip().startswith("Z")

    def wait(self, cond, what):
        for _ in range(100):
            if cond():
                return
            time.sleep(0.1)
        self.fail(f"timed out waiting for {what}")

    def run_of(self, tid):
        runs = self.root / "docs" / ".runs" / "pack"
        return max((f for f in runs.glob("*.prompt.md") if f"({tid}, " in f.read_text()), key=lambda f: f.stat().st_mtime)

    def test_start_stop_only_this_run_continue_with_history(self):
        self.ok("pack", "--only", "B7", "--run")
        self.wait(lambda: (self.root / "child-B7.pid").exists(), "the B7 run's tool")
        self.ok("pack", "--only", "B9", "--run")   # another task's run goes beside it
        self.wait(lambda: (self.root / "child-B9.pid").exists(), "the B9 run's tool")
        self.assertEqual(self.run_ad("pack", "--only", "B7", "--run").returncode, 2)   # not twice for one task
        self.assertEqual(self.state("B7"), "running")

        b7, b9 = self.run_of("B7").name.split(".")[0], self.run_of("B9").name.split(".")[0]
        runs = self.root / "docs" / ".runs" / "pack"
        pids = {t: (runs / f"{s}.pid").read_text() for t, s in (("B7", b7), ("B9", b9))}
        tools = {t: (self.root / f"child-{t}.pid").read_text() for t in ("B7", "B9")}
        out = self.ok("pack", "--stop", b7)
        self.assertIn("back in the queue: B7", out)
        self.assertFalse(self.alive(pids["B7"]) or self.alive(tools["B7"]))
        self.assertTrue(self.alive(pids["B9"]) and self.alive(tools["B9"]))   # only this run's processes
        self.assertEqual((self.state("B7"), self.state("B9")), ("queued", "running"))
        self.assertFalse((self.root / "docs" / ".claims" / "B7.json").exists())
        events = [e["what"] for e in self.rows("SELECT what FROM events WHERE task = 'B7' ORDER BY id")]
        self.assertEqual(events[-5:], ["run started", "state", "taken", "state", "run stopped"])
        self.assertEqual(self.run_ad("pack", "--stop", b7).returncode, 1)   # already stopped

        prompt = self.ok("pack", "--only", "B7")   # continuing: the new run is told what the earlier one did
        self.assertIn("This continues earlier runs", prompt)
        self.assertRegex(prompt, r"- B7, \d\d\.\d\d \d\d:\d\d, \d+ min, stopped by Owner\. Its last words: Half of B7 done\.")
        self.assertNotIn("Half of B9", prompt)
        self.assertIn("run stopped", self.ok("task", "show", "B7"))   # and the task's history shows the runs
        self.ok("pack", "--only", "B7", "--run")
        self.wait(lambda: self.state("B7") == "running" and len(list(runs.glob("*.prompt.md"))) == 3, "the next B7 run")

    def test_the_owners_reply_continues_the_session_of_the_last_run(self):
        runs = self.root / "docs" / ".runs" / "pack"
        self.assertEqual(self.run_ad("pack", "--reply", "B7").returncode, 1)   # nothing written yet
        self.ok("pack", "--only", "B7", "--run")
        self.wait(lambda: (self.root / "child-B7.pid").exists(), "the B7 run")
        first = self.run_of("B7").name.split(".")[0]
        sid = json.loads((runs / f"{first}.jsonl").read_text().splitlines()[0])["session_id"]
        self.ok("task", "comment", "B7", "--as", "Owner", "Use the March numbers, not April.")
        self.assertEqual(self.run_ad("pack", "--reply", "B7", "--run").returncode, 2)   # waits for the run to end
        self.ok("pack", "--stop", first)

        prompt = self.ok("pack", "--reply", "B7")
        self.assertIn("This continues your run", prompt)
        self.assertIn("] Use the March numbers, not April.", prompt)
        self.assertRegex(prompt, r"(?m)^1\. .*\(B7, ")
        self.ok("pack", "--reply", "B7", "--run")
        self.wait(lambda: self.state("B7") == "running" and len(list(runs.glob("*.prompt.md"))) == 2, "the reply run")
        second = self.run_of("B7").name.split(".")[0]
        self.assertEqual(json.loads((runs / f"{second}.jsonl").read_text().splitlines()[0])["session_id"], sid)
        started = [json.loads(e["detail"]) for e in self.rows(
            "SELECT detail FROM events WHERE task = 'B7' AND what = 'run started' ORDER BY id")]
        self.assertEqual((started[-1]["reply"], started[-1]["resumed"]), (1, sid))
        self.ok("pack", "--stop", second)
        self.assertEqual(self.run_ad("pack", "--reply", "B7").returncode, 1)   # delivered: nothing unread

    def test_a_reply_to_a_task_never_run_starts_a_fresh_run_with_it(self):
        self.ok("task", "comment", "B9", "--as", "Owner", "Start with the cheap half.")
        prompt = self.ok("pack", "--reply", "B9")
        self.assertIn("Autonomous run", prompt)
        self.assertIn("] Start with the cheap half.", prompt)


class OldStore(StoreProject):
    def test_a_store_from_before_the_eighth_state_is_widened(self):
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            CREATE TABLE projects (name TEXT PRIMARY KEY, root TEXT NOT NULL);
            CREATE TABLE tasks (project TEXT NOT NULL REFERENCES projects(name), id TEXT NOT NULL,
              kind TEXT NOT NULL CHECK (kind IN ('ticket', 'question')), title TEXT NOT NULL,
              text TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
              state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'waiting_you', 'waiting_task', 'accepting',
                                                   'done', 'deferred')),
              priority TEXT NOT NULL DEFAULT '', theme TEXT NOT NULL DEFAULT '',
              mode TEXT NOT NULL DEFAULT '' CHECK (mode IN ('', 'auto', 'human')), waits TEXT NOT NULL DEFAULT '',
              section TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
              updated TEXT NOT NULL, PRIMARY KEY (project, id));
            INSERT INTO projects VALUES ('proj', 'x');
            INSERT INTO tasks (project, id, kind, title, state, created, updated) VALUES ('proj', 'B1', 'ticket', 'Old', 'queued', 'x', 'x');
        """)
        conn.close()
        self.ok("store", "import")
        self.assertIn("waiting_others", self.rows("SELECT sql FROM sqlite_master WHERE name = 'tasks'")[0]["sql"])
        self.assertEqual(self.state("B1"), "queued")   # kept
        self.assertEqual(self.state("B14"), "waiting_others")


if __name__ == "__main__":
    unittest.main()
