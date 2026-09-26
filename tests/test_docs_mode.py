"""End-to-end: where project docs live relative to git (agentdrop --docs).

Runs the real script against throwaway git repos with a throwaway HOME.
    python3 -m unittest discover tests
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pty   # POSIX only; on Windows the prompt test is skipped
except ImportError:
    pty = None

SCRIPT = Path(__file__).resolve().parent.parent / "agentdrop"


class DocsMode(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.root = Path(tmp.name) / "proj"
        self.home.mkdir()
        self.root.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.git("init", "-q")
        (self.root / "main.py").write_text("print(1)\n")
        self.git("add", "main.py")
        self.git("commit", "-qm", "init")

    def git(self, *args, docs=False):
        pre = ["git", "--git-dir=.git-docs", "--work-tree=."] if docs else ["git"]
        return subprocess.run(pre + list(args), cwd=self.root, env=self.env,
                              text=True, capture_output=True).stdout.strip()

    def run_agentdrop(self, *args, answer=None):
        if answer is not None and not {"--research", "--no-research"} & set(args):
            args = ("--no-research", *args)   # only the docs question here; research has its own tests
        cmd = [sys.executable, str(SCRIPT), *args, "."]
        if answer is None:
            r = subprocess.run(cmd, cwd=self.root, env=self.env, text=True,
                               stdin=subprocess.DEVNULL, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout
        # a real terminal, so agentdrop asks
        if pty is None:
            self.skipTest("no pty on Windows")
        master, slave = pty.openpty()
        os.write(master, answer.encode() + b"\n")
        r = subprocess.run(cmd, cwd=self.root, env=self.env, text=True,
                           stdin=slave, capture_output=True)
        os.close(slave)
        os.close(master)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def exclude(self):
        path = self.root / ".git" / "info" / "exclude"
        return path.read_text() if path.exists() else ""

    def code_status(self):
        return self.git("status", "--porcelain").splitlines()

    def test_no_terminal_keeps_docs_in_code_repo_without_saving(self):
        out = self.run_agentdrop()
        self.assertIn("no terminal to ask", out)
        self.assertEqual(self.git("config", "agentdrop.docs"), "")
        self.assertEqual(self.git("config", "core.hooksPath"), ".githooks")
        self.assertIn("?? AGENTS.md", self.code_status())

    def test_separate_then_rerun_keeps_docs_out(self):
        out = self.run_agentdrop(answer="2")
        self.assertIn("Where should the project docs", out)
        self.assertEqual(self.git("config", "agentdrop.docs"), "separate")
        self.assertEqual(self.git("config", "core.hooksPath"), "")
        self.assertEqual(self.git("config", "core.hooksPath", docs=True), ".githooks")
        self.assertEqual(self.git("config", "status.showUntrackedFiles", docs=True), "no")
        self.assertIn("A  docs/STATE.md", self.git("status", "--porcelain", docs=True))
        self.assertIn("Two repos in one folder", (self.root / "AGENTS.md").read_text())
        self.assertEqual(self.code_status(), ["?? .gitattributes"])
        self.git("commit", "-qm", "docs", docs=True)

        out = self.run_agentdrop()   # no terminal, no flag: the saved answer wins
        self.assertIn("Docs mode: separate", out)
        self.assertEqual(self.git("config", "core.hooksPath"), "")
        self.assertEqual(self.code_status(), ["?? .gitattributes"])
        self.assertIn("Two repos in one folder", (self.root / "AGENTS.md").read_text())
        self.assertEqual(self.exclude().count("/docs/"), 1)

    def test_switch_local_then_track(self):
        self.run_agentdrop("--docs", "separate")
        out = self.run_agentdrop("--docs", "local")
        self.assertIn(".git-docs left in place", out)
        agents = (self.root / "AGENTS.md").read_text()
        self.assertIn("Docs outside git", agents)
        self.assertNotIn("Two repos", agents)
        self.assertEqual(self.git("config", "agentdrop.docs"), "local")

        self.run_agentdrop("--docs", "track")
        self.assertNotIn("agentdrop", self.exclude())
        self.assertEqual(self.git("config", "core.hooksPath"), ".githooks")
        self.assertNotIn("Docs outside git", (self.root / "AGENTS.md").read_text())
        self.assertIn("?? AGENTS.md", self.code_status())

    def test_already_tracked_docs_get_an_untrack_hint(self):
        self.run_agentdrop("--docs", "track")
        self.git("add", "-A")
        self.git("commit", "-qm", "docs")
        out = self.run_agentdrop("--docs", "local")
        self.assertIn("still tracked in the code repo", out)
        self.assertIn("git rm -r -q --cached -- AGENTS.md", out)

    def test_hand_made_docs_repo_is_detected(self):
        # the LayoutFix setup: .git-docs and exclude lines written by hand, no saved answer
        self.git("init", "-q", docs=True)
        (self.root / ".git" / "info").mkdir(exist_ok=True)
        (self.root / ".git" / "info" / "exclude").write_text(
            ".git-docs/\ndocs/\nAGENTS.md\nGEMINI.md\nCLAUDE.md\nLOCAL.md\n.docs-allow\n"
            ".githooks/\nscripts/check_docs.sh\n.claude/\n")
        out = self.run_agentdrop()
        self.assertIn("Docs mode: separate", out)
        self.assertEqual(self.git("config", "agentdrop.docs"), "separate")
        self.assertNotIn("agentdrop", self.exclude())   # every path was already listed
        self.assertEqual(self.code_status(), ["?? .gitattributes"])

    def test_dry_run_changes_nothing(self):
        out = self.run_agentdrop("--dry-run", "--docs", "separate")
        self.assertIn("would create the local docs repo", out)
        self.assertFalse((self.root / ".git-docs").exists())
        self.assertEqual(self.exclude().count("agentdrop"), 0)
        self.assertEqual(self.git("config", "agentdrop.docs"), "")


if __name__ == "__main__":
    unittest.main()
