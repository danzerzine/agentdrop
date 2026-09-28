"""`agentdrop plug`: one command puts a project on the panel. Its tasks move to the store (a markdown board is
imported first), the config says so, and `agentdrop tickets` lists it; plugging twice changes nothing.

    python3 -m unittest discover tests
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class Plug(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.home, self.root = base / "home", base / "new-app"
        self.root.mkdir()
        (self.home / ".agentdrop").mkdir(parents=True)
        (self.home / ".agentdrop" / "config").write_text("owner = Owner\n", encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "AGENTDROP_SESSION", "AI_AGENT")}
        self.env.update(HOME=str(self.home), USERPROFILE=str(self.home), AGENTDROP_STORE=str(base / "tasks.sqlite3"),
                        AGENTDROP_OFFLINE="1")

    def ok(self, *args):
        r = subprocess.run([sys.executable, str(REPO / "agentdrop"), *args], cwd=self.root, env=self.env,
                           text=True, capture_output=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def config(self):
        return (self.home / ".agentdrop" / "config").read_text(encoding="utf-8")

    def listed(self):
        return [p["root"] for p in json.loads(self.ok("tickets"))["projects"]]

    def test_empty_project_plugs_in(self):
        self.assertNotIn(str(self.root), self.listed())
        out = self.ok("plug")
        self.assertIn("new-app", out)
        self.assertIn("tasks.new-app = store", self.config())
        self.assertIn(str(self.root), self.listed())
        self.ok("task", "new", "Export the report", "--summary", "The weekly report goes out as a spreadsheet")
        self.assertIn("B1", self.ok("task", "show", "B1"))
        self.ok("plug")   # again: nothing new
        self.assertEqual(self.config().count("tasks.new-app"), 1)
        self.assertIn("B1", self.ok("task", "show", "B1"))

    def test_first_task_speaks_its_own_language(self):
        self.ok("plug")
        out = self.ok("task", "new", "Выгрузить отчёт", "--summary", "Недельный отчёт уходит таблицей", "--priority", "P1")
        self.assertIn("В очереди", out)
        with sqlite3.connect(self.env["AGENTDROP_STORE"]) as db:
            self.assertEqual(db.execute("SELECT section FROM tasks WHERE id = 'B1'").fetchone()[0], "Сейчас")

    def test_markdown_board_is_imported(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "TODO.md").write_text(
            "# TODO\n\n## Now\n\n- **B4 (P1). Fix login.** Safari.\n", encoding="utf-8")
        out = self.ok("plug")
        self.assertIn("1", out)
        self.assertIn("Fix login", self.ok("task", "show", "B4"))

    def test_listed_projects_get_the_new_one(self):
        (self.home / ".agentdrop" / "config").write_text("owner = Owner\nprojects = ~/elsewhere\n", encoding="utf-8")
        self.ok("plug")
        self.assertIn(f"projects = ~/elsewhere, {self.root}", self.config())


if __name__ == "__main__":
    unittest.main()
