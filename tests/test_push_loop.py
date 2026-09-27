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

    def test_tickets_blocked_on_others_are_not_next(self):
        todo = self.root / "docs" / "TODO.md"
        todo.write_text(TODO.replace("## Next\n", "## Next\n\n- **B12 (P0). Plan for the client.** Sent 26.09. Waiting for the client's answer.\n"),
                        encoding="utf-8")
        s = self.status()
        self.assertNotIn("B12", [t["id"] for t in s["next"]["tickets"]])
        self.assertEqual([t["id"] for t in s["next"]["blocked"]], ["B12"])
        self.assertIn("waiting for other people: Plan for the client (B12)", self.run_ad("status").stdout)

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
                raw = self.rfile.read(int(self.headers["content-length"]))
                method = self.path.rsplit("/", 1)[-1]
                if self.headers.get("content-type", "").startswith("multipart/"):
                    n = raw.count(b"attach://")
                    fake.calls.append((method, {"photos": n, "raw": raw}))
                    ids = []
                    for _ in range(n):
                        fake.next_id += 1
                        ids.append({"message_id": fake.next_id})
                    return self.reply(200, {"ok": True, "result": ids})
                body = json.loads(raw or b"{}")
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


class WithTelegram(Project):
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
            "msg = p.split('Their message:', 1)[1]\n"
            "opts = re.findall(r'^- \"([^\"]+)\"', p, re.M)\n"
            "r = 'status' if 'going on' in msg else 'unclear' if 'loose' in msg else 'agentdrop' if 'bot' in msg else next((o for o in opts if o.startswith('project')), '') "
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


class Brief(WithTelegram):
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

    def test_status_question_gets_the_board(self):
        self.run_ad("brief", "--send")
        self.tg.answer("what's going on and what do you need from me?")
        self.run_ad("replies")
        board = self.tg.sent[-1]["text"]
        self.assertTrue(board.startswith("<b>📊 proj · NOW</b>"))
        self.assertIn("1. Which chart library (Q-2)\n2. Deploy script (B8)", board)
        self.assertIn("1. Fix login on Safari <i>(B7, P1)</i>", board)
        self.assertNotIn("going on", (self.root / "docs" / "QUESTIONS.md").read_text(encoding="utf-8"))

    def test_before_and_after_pictures_go_under_the_item(self):
        shots = self.root / "docs" / "shots"
        shots.mkdir()
        for name in ("before.png", "after.png"):
            (shots / name).write_bytes(b"\x89PNG fake")
        q = self.root / "docs" / "QUESTIONS.md"
        q.write_text(QUESTIONS.replace("I recommend Recharts: we already use it.",
                                       "I recommend Recharts: we already use it. Now `shots/before.png`, "
                                       "then shots/after.png; shots/missing.png is gone."), encoding="utf-8")
        self.run_ad("brief", "--send")
        album = [b for m, b in self.tg.calls if m == "sendMediaGroup"]
        self.assertEqual(len(album), 1)
        self.assertEqual(album[0]["photos"], 2)
        self.assertIn(b"before.png", album[0]["raw"])
        q2 = self.by_text("Q-2")["message_id"]
        self.assertIn(f'"message_id": {q2}'.encode(), album[0]["raw"])   # under the item's message

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


JUDGE = """import json, os, sys
home = os.path.dirname(os.path.abspath(__file__))
prompt = sys.stdin.read()
n = len([f for f in os.listdir(home) if f.startswith('prompt')])
open(os.path.join(home, f'prompt{n}.txt'), 'w').write(prompt)
verdicts = open(os.path.join(home, 'verdicts.txt')).read().split()
v = verdicts[min(n, len(verdicts) - 1)]
print(json.dumps({'type': 'result', 'total_cost_usd': 0.5, 'structured_output': {
    'verdict': v, 'summary': f'judge says {v}',
    'findings': [] if v == 'PASS' else [{'severity': 'blocker', 'what': 'Safari still fails', 'evidence': 'x.py:3'}]}}))
"""


class Accept(WithTelegram):
    def setUp(self):
        super().setUp()
        (self.home / "judge.py").write_text(JUDGE, encoding="utf-8")
        with open(self.home / ".agentdrop" / "config", "a", encoding="utf-8") as f:
            f.write(f"judge = {sys.executable} {self.home / 'judge.py'}\n")
        todo = self.root / "docs" / "TODO.md"
        todo.write_text(TODO.replace("Repro on iOS 18.", "Repro on iOS 18. Spec: docs/specs/login.md."), encoding="utf-8")
        (self.root / "docs" / "checks").write_text("# fast ones first\ntest -f ok.flag\n", encoding="utf-8")
        self.env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        self.git("add", "-A")
        self.git("commit", "-qm", "start")
        self.assertEqual(self.run_ad("claim", "B7", session="s1").returncode, 0)
        (self.root / "login.py").write_text("fixed = True\n", encoding="utf-8")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, env=self.env, check=True)

    def verdicts(self, *v):
        (self.home / "verdicts.txt").write_text(" ".join(v), encoding="utf-8")

    def prompts(self):
        return sorted(self.home.glob("prompt*.txt"))

    def test_failed_check_goes_back_without_a_judge(self):
        self.verdicts("PASS")
        r = self.run_ad("accept", "B7")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("test -f ok.flag", r.stdout)
        self.assertEqual(self.prompts(), [])
        run = json.loads((self.root / "docs" / ".runs" / "B7.json").read_text(encoding="utf-8"))
        self.assertEqual(run["state"], "checks_failed")
        self.assertEqual(self.tg.sent, [])

    def test_pass_is_not_messaged_by_default(self):
        self.verdicts("PASS")
        (self.root / "ok.flag").write_text("", encoding="utf-8")
        r = self.run_ad("accept", "B7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.tg.sent, [])   # a PASS shows on the board and in the brief, not on the phone

    def test_pass_tells_the_owner_once(self):
        with open(self.home / ".agentdrop" / "config", "a", encoding="utf-8") as f:
            f.write("accept_tell_pass = yes\n")
        self.verdicts("PASS")
        (self.root / "ok.flag").write_text("", encoding="utf-8")
        r = self.run_ad("accept", "B7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        prompt = self.prompts()[0].read_text(encoding="utf-8")
        self.assertIn("I can't log in from the iPad", prompt)   # the owner's why is the bar
        self.assertIn("docs/specs/login.md", prompt)
        self.assertIn("login.py", prompt)                          # the new file is in the change
        self.assertIn("`test -f ok.flag` → exit 0", prompt)
        [msg] = self.tg.sent
        self.assertIn("ACCEPTED", msg["text"])
        self.assertIn("Fix login on Safari", msg["text"])
        # same code again: no checks, no judge, no second message
        r = self.run_ad("accept", "B7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("already passed on this code", r.stdout)
        self.assertEqual(len(self.prompts()), 1)
        self.assertEqual(len(self.tg.sent), 1)
        # the owner's reply lands under the ticket
        self.tg.answer("great, ship it", reply_to=msg["message_id"])
        self.assertEqual(self.run_ad("replies").returncode, 0)
        self.assertIn("great, ship it", (self.root / "docs" / "TODO.md").read_text(encoding="utf-8"))

    def test_no_checks_file_goes_straight_to_the_judge(self):
        self.git("rm", "-q", "docs/checks")
        self.git("commit", "-qm", "no project checks")
        self.verdicts("PASS")
        r = self.run_ad("accept", "B7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no docs/checks", r.stdout)
        [prompt] = self.prompts()
        self.assertIn("the project has no docs/checks", prompt.read_text(encoding="utf-8"))

    def test_third_reject_goes_to_the_owner(self):
        self.verdicts("REJECT")
        (self.root / "ok.flag").write_text("", encoding="utf-8")
        for k in (1, 2):
            r = self.run_ad("accept", "B7")
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("Safari still fails", r.stdout)
            self.assertEqual(self.tg.sent, [])
            (self.root / "login.py").write_text(f"fixed = {k}\n", encoding="utf-8")   # a repair
        r = self.run_ad("accept", "B7")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        [msg] = self.tg.sent
        self.assertIn("NEEDS YOU", msg["text"])
        self.assertIn("rejected it 3 times", msg["text"])
        self.assertIn("Safari still fails", msg["text"])

    def test_a_dead_judges_answer_is_kept(self):
        (self.root / "ok.flag").write_text("", encoding="utf-8")
        runs = self.root / "docs" / ".runs"
        (runs / "B7").mkdir(parents=True)
        (runs / "B7" / "2-judge.json").write_text(json.dumps({"structured_output": {
            "verdict": "PASS", "summary": "fine", "findings": []}}), encoding="utf-8")
        dead = subprocess.Popen([sys.executable, "-c", ""])
        dead.wait()
        import platform
        (runs / "B7.json").write_text(json.dumps({"steps": [{
            "step": "judge", "fp": "old", "pid": dead.pid, "host": platform.node(),
            "started": "2026-09-27T10:00:00+03:00", "log": "docs/.runs/B7/2-judge.json"}]}), encoding="utf-8")
        self.verdicts("REJECT")
        r = self.run_ad("accept", "B7")
        self.assertIn("died", r.stdout)
        run = json.loads((runs / "B7.json").read_text(encoding="utf-8"))
        self.assertEqual(run["steps"][0]["verdict"], "PASS")
        self.assertTrue(run["steps"][0]["died"])

    def test_a_live_run_is_not_started_twice(self):
        import platform
        runs = self.root / "docs" / ".runs"
        runs.mkdir(parents=True)
        (runs / "B7.json").write_text(json.dumps({"steps": [{
            "step": "check", "cmd": "sleep 100", "pid": os.getpid(), "host": platform.node(),
            "started": "2026-09-27T10:00:00+03:00", "log": "docs/.runs/B7/1-check1.log"}]}), encoding="utf-8")
        r = self.run_ad("accept", "B7")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already running", r.stderr)
        self.assertEqual(self.prompts(), [])


WORKER = """import json, os, sys
home = os.path.dirname(os.path.abspath(__file__))
prompt = sys.stdin.read()
n = len([f for f in os.listdir(home) if f.startswith('work')])
open(os.path.join(home, f'work{n}.txt'), 'w').write(prompt)
if prompt.startswith('Morning tidy'):
    print(json.dumps({'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'git log', 'description': 'Look at recent commits'}}]}}),
        flush=True)
    with open('docs/LOG.md', 'a') as f:
        f.write('\\n## 27.09 — tidy closed B11\\n\\n- Done long ago.\\n')
    print(json.dumps({'type': 'result', 'total_cost_usd': 0.3, 'structured_output': {
        'closed': ['B11'], 'changed': [], 'notes': 'closed one', 'report': [
            {'text': 'Old reports cleanup (B11) closed: done in May', 'ticket': 'B11', 'check': False},
            {'text': 'Dark theme (B10): I read your OK as system setting, not a toggle', 'ticket': 'B10', 'check': True}]}}))
else:
    print(json.dumps({'type': 'result', 'result': 'accepted, exit 0'}))
"""


class Dispatch(WithTelegram):
    def setUp(self):
        super().setUp()
        (self.home / "worker.py").write_text(WORKER, encoding="utf-8")
        with open(self.home / ".agentdrop" / "config", "a", encoding="utf-8") as f:
            f.write(f"worker = {sys.executable} {self.home / 'worker.py'}\nprojects = {self.root}\n")

    def works(self):
        return [p.read_text(encoding="utf-8") for p in sorted(self.home.glob("work*.txt"))]

    def test_owner_answer_under_a_ticket_is_the_agents_turn(self):
        todo = self.root / "docs" / "TODO.md"
        todo.write_text(TODO.replace("Repro on iOS 18.", "Repro on iOS 18.\n\n  > **Owner, 27.09 06:21:** it works now, close it"),
                        encoding="utf-8")
        (self.home / ".agentdrop" / "config").write_text("owner = Owner\n", encoding="utf-8")
        s = self.status()
        self.assertNotIn("B7", [t["id"] for t in s["next"]["tickets"]])
        self.assertIn("Fix login on Safari (B7)", s["waiting"]["your_turn"])

    def test_tidy_then_brief(self):
        r = self.run_ad("dispatch", "--now")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [prompt] = self.works()
        self.assertIn("B7: Fix login on Safari", prompt)
        self.assertIn("Never deploy", prompt)
        self.assertIn("closed B11", r.stdout)
        self.assertIn("Bash: Look at recent commits", r.stdout)   # each step shows as it happens
        self.assertFalse((self.root / "docs" / ".claims" / "TIDY.json").exists())
        report, check, head = (m["text"] for m in self.tg.sent[:3])
        self.assertIn("MORNING TIDY", report)   # what the tidy pass did, in plain words, first
        self.assertIn("Old reports cleanup (B11) closed", report)
        self.assertIn("TAKE A LOOK", check)      # a reading of the owner's words gets its own message
        self.assertIn("system setting, not a toggle", check)
        self.assertIn("BRIEF", head)
        self.assertNotIn("tidy closed B11", head)   # its LOG entry isn't repeated in the brief
        self.tg.answer("no, a toggle", reply_to=self.tg.sent[1]["message_id"])
        self.assertEqual(self.run_ad("replies").returncode, 0)
        self.assertIn("no, a toggle", (self.root / "docs" / "TODO.md").read_text(encoding="utf-8"))
        self.assertTrue((self.home / ".agentdrop" / "dispatch.log").is_file())

    def test_a_claimed_project_gets_only_the_brief(self):
        self.assertEqual(self.run_ad("claim", "B9", session="s1").returncode, 0)
        r = self.run_ad("dispatch", "--now")
        self.assertIn("someone is working there (B9", r.stdout)
        self.assertEqual(self.works(), [])
        self.assertTrue(self.tg.sent)

    def test_autonomous_ticket_goes_through_accept(self):
        todo = self.root / "docs" / "TODO.md"
        todo.write_text(TODO.replace("**B10. Dark theme.**", "**B10. Dark theme.** [autonomous]"), encoding="utf-8")
        r = self.run_ad("dispatch", "--now")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tidy, auto = self.works()
        self.assertIn("agentdrop claim B10 --session dispatcher", auto)
        self.assertIn("agentdrop accept B10", auto)
        self.assertIn("B10 exit 0", r.stdout)

    def test_daily_cap(self):
        with open(self.home / ".agentdrop" / "config", "a", encoding="utf-8") as f:
            f.write("day_cap = 2\n")
        self.run_ad("dispatch", "--now", "--no-work")
        self.assertEqual(len(self.tg.sent), 2)
        r = self.run_ad("dispatch", "--now", "--no-work", "--project", str(self.root))
        self.assertEqual(len(self.tg.sent), 2)
        self.assertIn("held back", r.stdout)

    def test_quiet_hours_and_dry_run_do_nothing(self):
        r = self.run_ad("dispatch", "--dry-run")
        self.assertIn("would tidy", r.stdout)
        self.assertEqual(self.works(), [])
        self.assertEqual(self.tg.sent, [])


if __name__ == "__main__":
    unittest.main()
