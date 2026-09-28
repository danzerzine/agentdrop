"""A question for the owner in parts (`agentdrop task ask`): the form is checked before anything is written,
pictures must be files inside the project, the parts reach the tickets page, old questions in free words
still load, and a markdown project gets the same form in QUESTIONS.md.

    python3 -m unittest tests.test_ask
"""

import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_store_tasks import StoreProject  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


class Ask(StoreProject):
    def setUp(self):
        super().setUp()
        shots = self.root / "docs" / "shots"
        shots.mkdir()
        for n in ("one", "two", "before", "after"):
            (shots / f"{n}.png").write_bytes(PNG)
        (self.root.parent / "outside.png").write_bytes(PNG)
        (shots / "link.png").symlink_to(self.root.parent / "outside.png")

    def ask(self, *args, code="B7"):
        return self.run_ad("task", "ask", code, *args, session="s1")

    def refused(self, *args, says):
        r = self.ask(*args)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("was not asked", r.stderr)
        self.assertIn(says, r.stderr)
        return r

    def test_the_form_is_checked_before_anything_is_written(self):
        self.to_store()
        before = self.rows("SELECT COUNT(*) AS n FROM comments")[0]["n"], self.state("B7")
        opts = ["--option", "Yes", "--option", "No", "--pick", "1"]
        self.refused("Drop the old login page?", says="no options")
        self.refused("Drop the old login page?", "--option", "Yes", "--pick", "1", says="1 option;")
        self.refused("x" * 121 + "?", *opts, says="the question is 122 characters")
        self.refused("Ship it?", "--option", "y" * 61, "--option", "No", "--pick", "1", says="option 1 is 61 characters")
        self.refused("Is docs/specs/login.md right?", *opts, says="names docs/specs/login.md")
        self.refused("Close B9 first?", *opts, says="names B9")
        self.refused("Ship it?", "--option", "Yes, see report.md", "--option", "No", "--pick", "1", says="names report.md")
        self.refused("Ship it?", "--option", "Yes", "--option", "No", says="no pick")
        self.refused("Ship it?", "--option", "Yes", "--option", "No", "--pick", "3", says="no such option")
        self.refused("Which layout?", *opts, "--design", says="needs pictures")
        self.refused("Which layout?", *opts, "--pic", "docs/shots/one.png", says="one picture per option")
        self.refused("Which layout?", *opts, "--before", "docs/shots/before.png", says="needs both")
        # a picture must be a file inside the project, however the path gets out of it
        self.refused("Which layout?", *opts, "--pic", "../outside.png", "--pic", "docs/shots/two.png", says="outside the project")
        self.refused("Which layout?", *opts, "--pic", str(self.root.parent / "outside.png"), "--pic", "docs/shots/two.png",
                     says="outside the project")
        self.refused("Which layout?", *opts, "--pic", "docs/shots/link.png", "--pic", "docs/shots/two.png",
                     says="outside the project")
        self.refused("Which layout?", *opts, "--pic", "docs/shots/none.png", "--pic", "docs/shots/two.png", says="no such file")
        self.refused("Which layout?", *opts, "--pic", "docs/TODO.md", "--pic", "docs/shots/two.png", says="not a picture")
        self.assertEqual((self.rows("SELECT COUNT(*) AS n FROM comments")[0]["n"], self.state("B7")), before)

    def test_a_question_in_parts_reaches_the_page_and_an_old_one_still_loads(self):
        self.to_store()
        self.ok("task", "ask", "B7", "Which login page goes live?", "--option", "The new one", "--option", "The old one",
                "--pick", "a", "--details", "Spec: docs/specs/login.md, after B9.", "--design",
                "--pic", "docs/shots/one.png", "--pic", "docs/shots/two.png", session="s1")
        self.assertEqual(self.state("B7"), "waiting_you")
        row = self.rows("SELECT text, ask FROM comments WHERE task = 'B7' ORDER BY n DESC LIMIT 1")[0]
        self.assertIn("(a) The new one", row["text"])   # every other reader still gets words
        self.assertIn("My pick — (a).", row["text"])
        ask = json.loads(row["ask"])
        self.assertEqual((ask["q"], ask["options"], ask["pick"], ask["design"]),
                         ("Which login page goes live?", ["The new one", "The old one"], 0, True))
        self.assertEqual([p["path"] for p in ask["pics"]], ["docs/shots/one.png", "docs/shots/two.png"])

        page = self.root.parent / "page"
        page.mkdir()
        items = {i["code"]: i for i in json.loads(self.ok("tickets", ".", "--docs", str(page / "docs.json")))["items"]}
        got = items["B7"]["ask"]
        self.assertEqual(got["q"], "Which login page goes live?")
        self.assertEqual([p["label"] for p in got["pics"]], ["a", "b"])
        for p in got["pics"]:
            self.assertRegex(p["src"], r"^img/[0-9a-f]{10}\.\w+$")
            self.assertTrue((page / p["src"]).is_file())
        # the pictures are the question's, not repeated among the task's screenshots
        self.assertNotIn("p-B7", json.loads((page / "docs.json").read_text()).get("images", {}))
        self.assertIsNone(items["B15"]["ask"])   # a thread in free words loads as before

        self.ok("task", "comment", "B7", "Согласен: (a) The new one", "--as", "Owner")
        items = {i["code"]: i for i in json.loads(self.ok("tickets", "."))["items"]}
        self.assertIsNone(items["B7"]["ask"])   # answered: no longer an open question

    def test_a_store_from_before_questions_in_parts_gets_the_column(self):
        self.to_store()
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            CREATE TABLE c2 AS SELECT project, task, n, author, at, text FROM comments;
            DROP TABLE comments; ALTER TABLE c2 RENAME TO comments;""")
        conn.close()
        self.assertNotIn("ask", {c["name"] for c in self.rows("PRAGMA table_info(comments)")})
        items = {i["code"]: i for i in json.loads(self.ok("tickets", "."))["items"]}
        self.assertIn("Owner", [m["author"] for m in items["B15"]["thread"]])
        self.assertIn("ask", {c["name"] for c in self.rows("PRAGMA table_info(comments)")})

    def test_a_markdown_project_gets_the_same_form_in_questions_md(self):
        self.refused("Drop the old login page?", says="no options")
        self.assertEqual(self.snapshot(), self.docs)
        self.ok("task", "ask", "B7", "Drop the old login page?", "--option", "Yes, drop it", "--option", "Keep it",
                "--pick", "2", "--before", "docs/shots/before.png", "--after", "docs/shots/after.png", session="s1")
        text = (self.root / "docs" / "QUESTIONS.md").read_text(encoding="utf-8")
        owners = text.split("## For the owner", 1)[1].split("## For others", 1)[0]
        self.assertRegex(owners.lstrip(), r"^- \*\*Drop the old login page\? \(B7, \d\d\.\d\d\)\*\*\n  \(a\) Yes, drop it\n")
        self.assertIn("<!-- ask: {", owners)
        items = [i for i in json.loads(self.ok("tickets", "."))["items"] if i["kind"] == "question"]
        q = next(i for i in items if i["title"].startswith("Drop the old login page?"))
        self.assertEqual((q["state"], q["ask"]["options"], q["ask"]["pick"]), ("owner", ["Yes, drop it", "Keep it"], 1))
        self.assertEqual([p["label"] for p in q["ask"]["pics"]], ["before", "after"])
        self.assertNotIn("<!--", q["body"])
        old = next(i for i in items if i["title"].startswith("Which chart library"))
        self.assertIsNone(old["ask"])   # an item in free words loads as before


if __name__ == "__main__":
    unittest.main()
