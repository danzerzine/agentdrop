"""End-to-end: `agentdrop store import` and `store check` copy a throwaway markdown project into a
temporary task store and compare the two.

    python3 -m unittest discover tests
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TODO = """# TODO — tickets

## Now

- B7 P1 — Fix login on Safari. Why: «I can't log in from the iPad» (M12, 20.09). Repro on iOS 18.
- **B8 (P0). Deploy script.** Needs the new server. Waiting for the owner's OK on the server.
- **B9 (P1) [export]. Export to CSV.** Why: «Sasha wants a spreadsheet» (M20, 21.09).

  > **Agent, 22.09:** Which columns first?
  > **Owner, 22.09:** Date, then sum.

## Next

- **B10 [autonomous]. Dark theme.** Follow the system setting.
- B13 P2 — Share the export. After: B9.

## Later

- B11 P3 — Old reports cleanup. Deferred until the new server.
"""

QUESTIONS = """# QUESTIONS — what waits for a human

## For the owner

- **Q-2. Which chart library.** Recharts or ECharts. I recommend Recharts: we already use it.
- **Keep the beta open?** Beta is public since 20.09.

  > **Owner, 21.09:** yes, keep it.

- **Old question.** Settled.

  > **Owner, 20.09:** done

  _Thread closed._

## For others

- **Design (B9):** column order for the CSV.
"""

LOG = """# LOG — work log

## 27.09 — B5 fixed the chart tooltip

- Tooltip stays on screen on phones.
"""


class Store(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.home, self.root, self.db = base / "home", base / "proj", base / "tasks.sqlite3"
        (self.root / "docs").mkdir(parents=True)
        self.home.mkdir()
        for name, text in (("TODO.md", TODO), ("QUESTIONS.md", QUESTIONS), ("LOG.md", LOG)):
            (self.root / "docs" / name).write_text(text, encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "AGENTDROP_SESSION", "AI_AGENT")}
        self.env.update(HOME=str(self.home), USERPROFILE=str(self.home), AGENTDROP_STORE=str(self.db),
                        AGENTDROP_OFFLINE="1")

    def run_ad(self, *args):
        return subprocess.run([sys.executable, str(REPO / "agentdrop"), *args], cwd=self.root, env=self.env,
                              text=True, capture_output=True, stdin=subprocess.DEVNULL)

    def store(self, *args):
        r = self.run_ad("store", *args)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return r

    def rows(self, sql, *params):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()

    def task(self, tid):
        return self.rows("SELECT * FROM tasks WHERE id = ?", tid)[0]

    def test_import_copies_tickets_questions_threads_and_links(self):
        before = {f.name: f.read_bytes() for f in (self.root / "docs").iterdir()}
        r = self.store("import")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("proj: 7 tickets (1 done), 4 questions as tasks, 5 comments, 1 «after» link.", r.stdout)
        self.assertEqual(before, {f.name: f.read_bytes() for f in (self.root / "docs").iterdir()})   # markdown untouched

        b7 = self.task("B7")
        self.assertEqual((b7["kind"], b7["title"], b7["state"], b7["priority"]), ("ticket", "Fix login on Safari", "queued", "P1"))
        self.assertEqual(b7["source"], "«I can't log in from the iPad» (M12, 20.09)")
        self.assertIn("Repro on iOS 18", b7["text"])
        self.assertEqual(self.task("B8")["state"], "waiting_you")   # waits for the owner's OK
        b9 = self.task("B9")
        self.assertEqual((b9["theme"], b9["state"]), ("export", "queued"))   # the owner answered last: the agent's move
        self.assertEqual(self.rows("SELECT author, at, text FROM comments WHERE task = 'B9' ORDER BY n"),
                         [{"author": "Agent", "at": "22.09", "text": "Which columns first?"},
                          {"author": "Owner", "at": "22.09", "text": "Date, then sum."}])
        b10 = self.task("B10")
        self.assertEqual((b10["mode"], b10["theme"], b10["priority"]), ("auto", "", "P2"))
        self.assertEqual(self.task("B13")["state"], "waiting_task")
        self.assertEqual(self.rows("SELECT task, after FROM links"), [{"task": "B13", "after": "B9"}])
        self.assertEqual(self.task("B11")["state"], "deferred")
        b5 = self.task("B5")
        self.assertEqual((b5["state"], b5["title"]), ("done", "Fixed the chart tooltip"))

        qs = {q["title"]: q for q in self.rows("SELECT * FROM tasks WHERE kind = 'question'")}
        self.assertEqual({t: q["state"] for t, q in qs.items()},
                         {"Decide: Which chart library (Q-2)": "waiting_you",
                          "Decide: Keep the beta open?": "queued",
                          "Decide: Old question": "done",
                          "Decide: Design (B9):": "waiting_others"})   # a question for other people
        self.assertIn("I recommend Recharts", qs["Decide: Which chart library (Q-2)"]["text"])
        self.assertEqual(len(self.rows("SELECT * FROM events WHERE what = 'created'")), 11)

        r = self.store("check")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("the store and the markdown match", r.stdout)

    def test_import_again_adds_nothing(self):
        self.store("import")
        count = lambda: {t: len(self.rows(f"SELECT * FROM {t}")) for t in ("tasks", "comments", "links", "events")}
        first = count()
        r = self.store("import")
        self.assertIn("0 new, 0 changed, 11 unchanged, 0 comments added, 0 events", r.stdout)
        self.assertEqual(count(), first)

    def test_an_answer_in_markdown_shows_in_check_then_lands_as_one_event(self):
        self.store("import")
        todo = self.root / "docs" / "TODO.md"
        todo.write_text(TODO.replace("  > **Owner, 22.09:** Date, then sum.\n",
                                     "  > **Owner, 22.09:** Date, then sum.\n  > **Agent, 23.09:** Done that way.\n"),
                        encoding="utf-8")
        r = self.store("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("B9 thread:", r.stdout)
        r = self.store("import")
        self.assertIn("0 new, 1 changed", r.stdout)
        events = self.rows("SELECT what, author, detail FROM events WHERE task = 'B9' ORDER BY id")
        self.assertEqual([e["what"] for e in events], ["created", "comment"])
        self.assertTrue(all(e["author"] == "import" for e in events))
        self.assertIn("Done that way.", events[-1]["detail"])
        self.assertEqual(self.store("check").returncode, 0)

    def test_the_journal_is_append_only(self):
        self.store("import")
        conn = sqlite3.connect(self.db)
        self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("UPDATE events SET author = 'someone'")
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM events")

    def test_a_russian_project_asks_to_decide_in_russian(self):
        (self.root / "docs" / "TODO.md").write_text("# TODO\n\n## Сейчас\n\n- B1 P1 — Починить вход.\n", encoding="utf-8")
        (self.root / "docs" / "QUESTIONS.md").write_text("# QUESTIONS\n\n## К владельцу\n\n- **Какой шрифт.** Два варианта.\n",
                                                         encoding="utf-8")
        self.store("import")
        q = self.rows("SELECT title, state FROM tasks WHERE kind = 'question'")
        self.assertEqual(q, [{"title": "Решить: Какой шрифт", "state": "waiting_you"}])


if __name__ == "__main__":
    unittest.main()
