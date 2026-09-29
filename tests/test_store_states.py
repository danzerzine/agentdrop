"""The state rules the store keeps by itself (B40), on the five cases where the states went wrong on 29.09:
an owner's decision an agent quoted, a decision on a question asked for a ticket, answered questions nobody
took, and tasks left in work by a session that ended.

    python3 -m unittest tests.test_store_states
"""

import json
import os
import time
import unittest

from test_store_tasks import StoreProject

MORE = """
- **Password in the code.** The database password sits in a script.

  > **Agent, 27.09:** Owner 27.09: we keep the passwords, only move it to .env.

- **Hand photo picking to the dev team? (B8, 28.09)** Options: (a) now, (b) after the test.

  > **Owner, 28.09:** I pick: (b) after the test.

- **Context in the summaries: close the topic or dig on? (28.09)** Options: (a) close, (b) a wider sample.

  > **Owner, 28.09:** I pick: (b) a wider sample.
  > **Agent, 28.09:** No gain in spring either.
  > **Owner, 28.09:** can we use my GPU?
  > **Agent, 28.09:** Ran the whole year on it: no gain.

- **Which server for the deploy? (B8)** Options: (a) the old one, (b) a new one.
"""


class StoreStates(StoreProject):
    def setUp(self):
        super().setUp()
        q = self.root / "docs" / "QUESTIONS.md"
        text = q.read_text(encoding="utf-8")
        q.write_text(text.replace("## For others", MORE.strip() + "\n\n## For others"), encoding="utf-8")
        self.to_store()

    def q(self, start):
        return self.rows("SELECT id, state FROM tasks WHERE kind = 'question' AND title LIKE ?", f"%{start}%")[0]

    def thread(self, tid):
        return [r["text"] for r in self.rows("SELECT text FROM comments WHERE task = ? ORDER BY n", tid)]

    def test_a_decision_an_agent_quoted_does_not_wait_for_the_owner(self):   # q62f202
        self.assertEqual(self.q("Password in the code")["state"], "queued")
        self.assertNotIn("\n- Password in the code", self.ok("status"))

    def test_an_answer_goes_into_the_ticket_it_was_asked_for(self):   # qc2467a
        q = self.q("Hand photo picking")
        out = self.ok("store", "states", "--tidy")
        self.assertIn(f"{q['id']}: queued → done, answer in B8", out)
        self.assertEqual(self.q("Hand photo picking")["state"], "done")
        self.assertIn("I pick: (b) after the test.", self.thread("B8")[-1])
        self.assertEqual(self.state("B8"), "queued")

    def test_the_owners_answer_on_the_panel_moves_it_at_once(self):
        q = self.q("Which server for the deploy")
        self.assertEqual(q["state"], "waiting_you")
        self.ok("task", "comment", q["id"], "(b) a new one", "--as", "Owner")
        self.assertEqual(self.q("Which server for the deploy")["state"], "done")
        self.assertIn("(b) a new one", self.thread("B8")[-1])
        self.assertEqual(self.state("B8"), "queued")

    def test_an_answered_question_with_no_ticket_is_taken(self):   # qee5f55, qf0e53b
        self.assertEqual(self.q("Context in the summaries")["state"], "queued")   # the agent spoke last, the owner decided
        self.ok("task", "take", "B8", session="s0")   # B8 is not the point here
        self.assertIn("Tooltip copy (B15", self.ok("task", "take", session="s1"))   # the owner wrote last on B15
        taken = [self.ok("task", "take", session=s).splitlines()[0] for s in ("s2", "s3", "s4", "s5")]
        self.assertTrue(all(t.startswith("Decide:") for t in taken), taken)
        self.assertIn("Fix login on Safari (B7", self.ok("task", "take", session="s6"))

    def test_a_task_left_in_work_by_a_session_that_ended_is_queued_again(self):   # B168, B184
        tr = self.home / ".claude" / "projects" / "x"
        tr.mkdir(parents=True)
        long_ago = time.time() - 2 * 3600
        for sid, tid in (("dead", "B7"), ("dead", "B9"), ("busy", "B10"), ("codex", "B12")):
            self.ok("task", "take", tid, session=sid)
            f = self.root / "docs" / ".claims" / f"{tid}.json"
            c = json.loads(f.read_text(encoding="utf-8"))
            c["started"] = "2026-01-01T10:00:00+00:00" if sid != "codex" else c["started"]
            f.write_text(json.dumps(c), encoding="utf-8")
        for sid in ("dead", "busy"):
            (tr / f"{sid}.jsonl").write_text("{}\n", encoding="utf-8")
            os.utime(tr / f"{sid}.jsonl", (long_ago, long_ago))
        (tr / "busy" / "subagents").mkdir(parents=True)   # the session works in a subagent: alive
        (tr / "busy" / "subagents" / "a.jsonl").write_text("{}\n", encoding="utf-8")
        bad = json.loads(self.run_ad("store", "states", "--json").stdout)["breaches"]
        self.assertEqual(sorted(b["task"] for b in bad if b["rule"] == "quiet"), ["B7", "B9"])
        self.run_ad("store", "states", "--tidy")
        self.assertEqual([self.state(t) for t in ("B7", "B9", "B10", "B12")], ["queued", "queued", "running", "running"])
        self.assertFalse((self.root / "docs" / ".claims" / "B7.json").exists())
        self.assertIn("The session has been quiet 2 h", self.thread("B7")[-1])

    def test_a_revertible_decision_is_done_and_the_counts_agree(self):
        self.assertEqual(self.q("Kept UTC")["state"], "done")
        self.ok("store", "states", "--tidy")
        self.assertEqual(self.run_ad("store", "states").returncode, 0)


if __name__ == "__main__":
    unittest.main()
