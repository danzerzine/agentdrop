"""End-to-end: `agentdrop status`, `claim`, `release`, `brief` and Telegram replies on a throwaway
project, with a fake Telegram Bot API on localhost standing in for the relay.

    python3 -m unittest discover tests
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TODO = """# TODO — tickets

## Now

- B7 P1 — Fix login on Safari. Why: «I can't log in from the iPad» (M12, 20.09). Repro on iOS 18.
- **B8 (P0). Deploy script.** Needs the new server. Waiting for the owner's OK on the server.
- P2: B9 export to CSV. Why: «Sasha wants a spreadsheet» (M20, 21.09).

## Next

- **B10. Dark theme.** Follow the system setting.

## Later

- B11 P3 — Old reports cleanup.
"""

QUESTIONS = """# QUESTIONS — what waits for a human

## For the owner

- **Q-2. Which chart library.** Two options: Recharts or ECharts. I recommend Recharts: we already use it.
- **Keep the beta open?** Beta is public since 20.09.

  > **Owner, 21.09:** yes, keep it.

- **Old question.** Settled.

  > **Owner, 20.09:** done
  > **Agent, 20.09:** thanks

  _Thread closed._
- **R-1. Kept UTC in exports.** R-1, revertible: the rest of the code uses UTC.

## For others

- **Design (B9):** column order for the CSV.

## Closed

- **Something old.** Answered.
"""

LOG = """# LOG — work log

<!-- harvest -->

## 27.09 — B6 login page redesign

- New login page, tests 40 green.

## 27.09 — B5 fixed the chart tooltip

- Tooltip stays on screen on phones.

## 26.09 — B4 older pass

- Old.
"""


class Project(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.home = base / "home"
        self.root = base / "proj"
        (self.root / "docs").mkdir(parents=True)
        self.home.mkdir()
        for name, text in (("TODO.md", TODO), ("QUESTIONS.md", QUESTIONS), ("LOG.md", LOG)):
            (self.root / "docs" / name).write_text(text, encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "AGENTDROP_SESSION", "AI_AGENT")}
        self.env.update(HOME=str(self.home), USERPROFILE=str(self.home), GIT_CONFIG_NOSYSTEM="1")
        subprocess.run(["git", "init", "-q"], cwd=self.root, env=self.env, check=True)

    def run_ad(self, *args, session=None):
        env = dict(self.env, **({"AGENTDROP_SESSION": session} if session else {}))
        return subprocess.run([sys.executable, str(REPO / "agentdrop"), *args], cwd=self.root, env=env,
                              text=True, capture_output=True, stdin=subprocess.DEVNULL)

    def status(self):
        r = self.run_ad("status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)


class PushLoop(Project):
    def test_next_up_is_ordered_by_priority_and_quotes_why(self):
        s = self.status()
        ids = [t["id"] for t in s["next"]["tickets"]]
        self.assertEqual(ids, ["B7", "B9", "B10", "B11"])   # B8 waits for the owner
        b7 = s["next"]["tickets"][0]
        self.assertEqual(b7["title"], "Fix login on Safari")
        self.assertEqual(b7["why"], "«I can't log in from the iPad» (M12, 20.09)")
        self.assertEqual(s["next"]["tickets"][2]["priority"], "P2")   # no priority: from its section

    def test_waiting_for_owner(self):
        w = self.status()["waiting"]
        titles = [q["title"] for q in w["questions"]]
        self.assertEqual(titles, ["Which chart library (Q-2)"])
        self.assertIn("I recommend Recharts", w["questions"][0]["pick"])
        self.assertEqual(w["your_turn"], ["Keep the beta open?"])
        self.assertEqual((w["revertible"], w["people"]), (1, 1))
        self.assertEqual([t["id"] for t in w["tickets"]], ["B8"])
        self.assertIsNone(w["asks"])

    def test_done_since_seen(self):
        s = self.status()
        self.assertFalse(s["done"]["since_seen"])
        self.assertEqual(len(s["done"]["entries"]), 2)   # the newest day only
        self.assertEqual(self.run_ad("status", "--mark-seen").returncode, 0)
        log = self.root / "docs" / "LOG.md"
        log.write_text(LOG.replace("<!-- harvest -->\n", "<!-- harvest -->\n\n## 28.09 — B7 Safari login\n\n- Fixed.\n"),
                       encoding="utf-8")
        s = self.status()
        self.assertTrue(s["done"]["since_seen"])
        self.assertEqual([e["heading"] for e in s["done"]["entries"]], ["28.09 — B7 Safari login"])

    def test_claim_blocks_other_sessions_and_stays_out_of_git(self):
        r = self.run_ad("claim", "b7", session="aaaa1111")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_ad("claim", "B7", session="bbbb2222")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already claimed", r.stderr)
        self.assertEqual(self.run_ad("release", "B7", session="bbbb2222").returncode, 1)

        s = self.status()
        claim = s["running"]["claims"][0]
        self.assertEqual((claim["ticket"], claim["session"], claim["title"]), ("B7", "aaaa1111", "Fix login on Safari"))
        self.assertFalse(claim["stale"])
        self.assertNotIn("B7", [t["id"] for t in s["next"]["tickets"]])
        self.assertIn("Fix login on Safari (B7)", self.run_ad("status").stdout)

        porcelain = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=self.root,
                                   env=self.env, text=True, capture_output=True).stdout
        self.assertNotIn(".claims", porcelain)

        self.assertEqual(self.run_ad("release", "B7", session="aaaa1111").returncode, 0)
        self.assertEqual(self.status()["running"]["claims"], [])

    def test_stale_claim_can_be_taken_over(self):
        (self.home / ".agentdrop").mkdir()
        (self.home / ".agentdrop" / "config").write_text("stale_hours = 0\n", encoding="utf-8")
        self.run_ad("claim", "B7", session="aaaa1111")
        self.assertTrue(self.status()["running"]["claims"][0]["stale"])
        r = self.run_ad("claim", "B7", session="bbbb2222")
        self.assertIn("--force", r.stderr)
        self.assertEqual(self.run_ad("claim", "B7", "--force", session="bbbb2222").returncode, 0)
        self.assertEqual(self.status()["running"]["claims"][0]["session"], "bbbb2222")


class FakeTelegram:
    """Bot API stand-in: records sendMessage, serves queued getUpdates, checks the relay key."""

    def __init__(self):
        self.sent, self.updates, self.calls, self.next_id, self.bad_key = [], [], [], 100, 0
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])) or b"{}")
                method = self.path.rsplit("/", 1)[-1]
                if self.headers.get("x-relay-key") != "k" or not self.path.startswith("/botT0K:x/"):
                    fake.bad_key += 1
                    return self.reply(404, {"ok": False, "description": "not found"})
                if method == "sendMessage":
                    fake.next_id += 1
                    fake.sent.append({**body, "message_id": fake.next_id})
                    return self.reply(200, {"ok": True, "result": {"message_id": fake.next_id}})
                if method == "getUpdates":
                    ups = [u for u in fake.updates if u["update_id"] >= body.get("offset", 0)]
                    return self.reply(200, {"ok": True, "result": ups})
                fake.calls.append((method, body))
                self.reply(200, {"ok": True, "result": True})

            def reply(self, code, data):
                raw = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def react(self, message_id, emoji, chat=42):
        self.updates.append({"update_id": 500 + len(self.updates), "message_reaction": {
            "chat": {"id": chat}, "message_id": message_id, "date": int(time.time()), "user": {"id": chat},
            "old_reaction": [], "new_reaction": [{"type": "emoji", "emoji": emoji}]}})

    def press(self, message_id, data, chat=42):
        self.updates.append({"update_id": 500 + len(self.updates), "callback_query": {
            "id": f"q{len(self.updates)}", "data": data, "message": {"message_id": message_id, "chat": {"id": chat}}}})

    def answer(self, text, reply_to=None, chat=42):
        m = {"message_id": 900 + len(self.updates), "date": int(time.time()), "chat": {"id": chat}, "text": text}
        if reply_to:
            m["reply_to_message"] = {"message_id": reply_to, "from": {"is_bot": True}}
        self.updates.append({"update_id": 500 + len(self.updates), "message": m})


class Brief(Project):
    def setUp(self):
        super().setUp()
        self.tg = FakeTelegram()
        self.addCleanup(self.tg.server.shutdown)
        (self.home / ".agentdrop").mkdir()
        # the router stand-in: "bot" → agentdrop, "new task" → a new question, else the item
        router = self.home / "router.py"
        router.write_text(
            "import json, re, sys\n"
            "p = sys.stdin.read()\n"
            "msg = p.split('His message:', 1)[1]\n"
            "opts = re.findall(r'^- \"([^\"]+)\"', p, re.M)\n"
            "r = 'unclear' if 'loose' in msg else 'agentdrop' if 'bot' in msg else next((o for o in opts if o.startswith('project')), '') "
            "if 'new task' in msg else ('item' if 'item' in opts else opts[0])\n"
            "print('```json\\n' + json.dumps({'route': r, 'why': 'test'}) + '\\n```')\n", encoding="utf-8")
        self.source = self.home / "agentdrop-src"
        (self.source / "docs").mkdir(parents=True)
        (self.home / ".agentdrop" / "source").write_text(str(self.source), encoding="utf-8")
        (self.home / ".agentdrop" / "config").write_text(f"router = {sys.executable} {router}\n", encoding="utf-8")
        (self.home / ".agentdrop" / "telegram.env").write_text(
            f"TG_BOT_TOKEN=T0K:x\nTG_CHAT_ID=42\nTG_RELAY_URL={self.tg.url}\nTG_RELAY_KEY=k\n", encoding="utf-8")

    def by_text(self, needle):
        return next(m for m in self.tg.sent if needle in m["text"])

    def test_one_message_per_item_then_nothing_new(self):
        r = self.run_ad("brief", "--send")
        self.assertEqual(r.returncode, 0, r.stderr)
        texts = [m["text"] for m in self.tg.sent]
        self.assertEqual(len(texts), 3)   # head, the chart question, the ticket blocked on the owner
        self.assertTrue(texts[0].startswith("<b>📋 proj · BRIEF</b>"))
        self.assertIn("<b>⏳ Waiting for you: 2</b>\n2 below, one message each", texts[0])
        self.assertIn("<b>✅ Done: 2</b>\n<blockquote expandable>• 27.09 — B6 login page redesign\n", texts[0])
        self.assertLess(texts[0].index("Done: 2"), texts[0].index("Waiting for you"))   # the owner's order
        # a question with the agent's proposal and a ticket waiting for an OK: both settle with a 👍
        self.assertIn("<b>👍 proj · YOUR OK, 1/2</b>\n\n<b>Which chart library</b>\n<i>Q-2</i>", texts[1])
        self.assertIn("<blockquote>Two options: Recharts or ECharts.</blockquote>", texts[1])
        self.assertIn("<b>💡 Proposal:</b> I recommend Recharts: we already use it.", texts[1])
        self.assertIn("A button below or a 👍 on this message", texts[1])
        self.assertEqual(self.tg.sent[1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "ok")
        self.assertNotIn("reply_markup", self.tg.sent[0])
        self.assertIn("<b>Deploy script</b>\n<i>B8, P0</i>", texts[2])
        self.assertIn("goes under the item in <code>TODO.md</code>", texts[2])
        self.assertEqual(self.tg.bad_key, 0)

        r = self.run_ad("brief", "--send")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nothing new", r.stdout)
        self.assertEqual(len(self.tg.sent), 3)

    def test_reply_lands_under_its_item_and_is_acknowledged(self):
        self.run_ad("brief", "--send")
        q2 = self.by_text("Q-2")["message_id"]
        b8 = self.by_text("B8, P0")["message_id"]
        head = self.tg.sent[0]["message_id"]
        self.tg.answer("Recharts.\nKeep it simple.", reply_to=q2)
        self.tg.answer("OK, take the new server", reply_to=b8)
        self.tg.answer("what about this?", reply_to=head)
        self.tg.answer("hi from a stranger", reply_to=q2, chat=7)
        sent_before = len(self.tg.sent)

        r = self.run_ad("status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Saved under «Which chart library (Q-2)» in proj, QUESTIONS.md", r.stderr)
        questions = (self.root / "docs" / "QUESTIONS.md").read_text(encoding="utf-8")
        self.assertIn("I recommend Recharts: we already use it.\n\n  > **Owner, ", questions)
        self.assertIn(":** Recharts.  \n  > Keep it simple.\n- **Keep the beta open?**", questions)
        self.assertNotIn("stranger", questions)
        todo = (self.root / "docs" / "TODO.md").read_text(encoding="utf-8")
        self.assertIn("Waiting for the owner's OK on the server.\n\n  > **Owner, ", todo)
        self.assertIn(":** OK, take the new server\n- P2: B9", todo)

        s = json.loads(r.stdout)
        self.assertEqual(s["waiting"]["questions"], [])
        self.assertIn("Which chart library (Q-2)", s["waiting"]["your_turn"])

        acks = self.tg.sent[sent_before:]
        self.assertEqual(len(acks), 3)   # two under items, one as a new item; the stranger gets nothing
        self.assertEqual(acks[0]["reply_parameters"]["message_id"], 900)
        self.assertIn("Saved in proj as a new item in QUESTIONS.md", acks[2]["text"])
        self.assertIn("- **From Telegram, ", questions)
        self.assertIn(":** what about this?", questions)

        self.run_ad("status")   # the same updates are never written twice
        self.assertEqual(questions, (self.root / "docs" / "QUESTIONS.md").read_text(encoding="utf-8"))

    def test_reply_to_an_ack_continues_the_thread_and_hints_are_rare(self):
        self.run_ad("brief", "--send")
        self.tg.answer("Recharts", reply_to=self.by_text("Q-2")["message_id"])
        self.run_ad("replies")
        ack = self.by_text("Saved under")["message_id"]
        self.tg.answer("and keep ECharts in mind", reply_to=ack)
        self.tg.answer("loose thought one")
        self.tg.answer("loose thought two")
        before = len(self.tg.sent)
        r = self.run_ad("replies")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.root / "docs" / "QUESTIONS.md").read_text(encoding="utf-8")
        self.assertIn(":** Recharts\n  > **Owner, ", text)
        self.assertIn(":** and keep ECharts in mind\n- **Keep the beta open?**", text)
        hints = [m for m in self.tg.sent[before:] if "which project" in m["text"]]
        self.assertEqual(len(hints), 1)   # one hint, not one per loose message
        self.assertNotIn("loose thought", text)

        self.tg.answer("new task: export to PDF")   # no reply: the router picks the project
        self.run_ad("replies")
        text = (self.root / "docs" / "QUESTIONS.md").read_text(encoding="utf-8")
        self.assertIn("- **From Telegram, ", text)
        self.assertIn(":** new task: export to PDF", text)

    def test_thumbs_up_is_the_owners_ok(self):
        self.run_ad("brief", "--send")
        self.tg.react(self.by_text("B8, P0")["message_id"], "👍")
        self.tg.react(self.by_text("Q-2")["message_id"], "😁")   # not an answer
        self.tg.react(self.tg.sent[0]["message_id"], "👍")       # the head: nothing to OK
        r = self.run_ad("replies")
        self.assertEqual(r.returncode, 0, r.stderr)
        todo = (self.root / "docs" / "TODO.md").read_text(encoding="utf-8")
        self.assertIn("Waiting for the owner's OK on the server.\n\n  > **Owner, ", todo)
        self.assertIn(":** OK (👍 in Telegram)\n- P2: B9", todo)
        self.assertEqual(QUESTIONS, (self.root / "docs" / "QUESTIONS.md").read_text(encoding="utf-8"))
        self.assertIn("OK (👍 in Telegram). ✅ Saved under «Deploy script»", self.tg.sent[-1]["text"])

    def test_reply_to_the_brief_goes_on_top_of_the_open_list(self):
        path = self.root / "docs" / "QUESTIONS.md"
        path.write_text("# Q\n\n## For the owner\n\n### Open\n\n- **Q-2. Which chart library.** Recharts?\n\n"
                        "### Closed\n\n- **Old.** Done.\n\n## For others\n", encoding="utf-8")
        self.run_ad("brief", "--send")
        self.tg.answer("start with what was done overnight", reply_to=self.tg.sent[0]["message_id"])
        self.run_ad("replies")
        text = path.read_text(encoding="utf-8")
        self.assertIn("### Open\n\n- **From Telegram, ", text)
        self.assertIn(":** start with what was done overnight\n\n- **Q-2.", text)
        self.assertEqual(len(self.status()["waiting"]["questions"]), 1)   # the agent's turn, not lost under Closed
        self.assertIn("From Telegram", self.status()["waiting"]["your_turn"][0])

    def test_words_about_the_bot_go_to_agentdrop_and_a_button_moves_them_back(self):
        self.run_ad("brief", "--send")
        todo = (self.root / "docs" / "TODO.md").read_text(encoding="utf-8")
        self.tg.answer("the bot should add OK buttons", reply_to=self.by_text("B8, P0")["message_id"])
        self.run_ad("replies")
        feedback = (self.source / "docs" / "FEEDBACK.md").read_text(encoding="utf-8")
        self.assertIn("- **", feedback)
        self.assertIn("proj, «Deploy script»**\n\n  > **Owner, ", feedback)
        self.assertEqual(todo, (self.root / "docs" / "TODO.md").read_text(encoding="utf-8"))
        ack = self.tg.sent[-1]
        self.assertIn("That's about the bot", ack["text"])
        moves = [b[0]["callback_data"] for b in ack["reply_markup"]["inline_keyboard"]]
        self.assertEqual(moves, ["mv:item", "mv:project"])

        self.tg.press(ack["message_id"], "mv:item")
        self.run_ad("replies")
        self.assertNotIn("OK buttons", (self.source / "docs" / "FEEDBACK.md").read_text(encoding="utf-8"))
        self.assertIn(":** the bot should add OK buttons\n- P2: B9",
                      (self.root / "docs" / "TODO.md").read_text(encoding="utf-8"))
        edits = [b for m, b in self.tg.calls if m == "editMessageText"]
        self.assertIn("Saved under «Deploy script»", edits[-1]["text"])

    def test_ok_and_not_ok_buttons(self):
        self.run_ad("brief", "--send")
        b8 = self.by_text("B8, P0")["message_id"]
        q2 = self.by_text("Q-2")["message_id"]
        self.tg.press(b8, "ok")
        self.tg.press(q2, "no")
        self.run_ad("replies")
        self.assertIn(":** OK (button in Telegram)\n- P2: B9", (self.root / "docs" / "TODO.md").read_text(encoding="utf-8"))
        marks = [b for m, b in self.tg.calls if m == "editMessageReplyMarkup"]
        self.assertEqual(marks[0]["reply_markup"]["inline_keyboard"][0][0]["text"], "✅ OK saved")
        prompt = self.tg.sent[-1]
        self.assertTrue(prompt["reply_markup"]["force_reply"])
        self.tg.answer("the bot says ECharts is lighter", reply_to=prompt["message_id"])   # forced: no router
        self.run_ad("replies")
        self.assertIn(":** the bot says ECharts is lighter", (self.root / "docs" / "QUESTIONS.md").read_text(encoding="utf-8"))
        self.assertFalse((self.source / "docs" / "FEEDBACK.md").exists())
        self.assertEqual(len([m for m, _ in self.tg.calls if m == "answerCallbackQuery"]), 2)

    def test_answer_to_a_closed_item_becomes_a_new_question(self):
        self.run_ad("brief", "--send")
        q2 = self.by_text("Q-2")["message_id"]
        path = self.root / "docs" / "QUESTIONS.md"
        path.write_text(QUESTIONS.replace("- **Q-2. Which chart library.** Two options: Recharts or ECharts. "
                                          "I recommend Recharts: we already use it.\n", ""), encoding="utf-8")
        self.tg.answer("ECharts after all", reply_to=q2)
        r = self.run_ad("replies")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("is gone from proj", r.stdout)
        text = path.read_text(encoding="utf-8")
        self.assertIn("- **Answer from Telegram about «Which chart library (Q-2)» (QUESTIONS.md)**\n\n"
                      "  > **Owner, ", text)
        self.assertLess(text.index("ECharts after all"), text.index("## For others"))

    def test_print_without_send_touches_nothing(self):
        r = self.run_ad("brief")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("proj · YOUR OK", r.stdout)
        self.assertEqual(self.tg.sent, [])
        self.assertFalse((self.home / ".agentdrop" / "telegram.json").exists())


if __name__ == "__main__":
    unittest.main()
