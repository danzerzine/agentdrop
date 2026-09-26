"""End-to-end: research mode, the SessionStart reminders and kit updates.

Runs the real script against throwaway projects with a throwaway HOME.
    python3 -m unittest discover tests
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pty   # POSIX only; on Windows the prompt test is skipped
except ImportError:
    pty = None

REPO = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")


class Research(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.home = base / "home"
        self.root = base / "proj"
        self.home.mkdir()
        self.root.mkdir()
        self.script = REPO / "agentdrop"
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "GIT_CONFIG_NOSYSTEM": "1"}
        subprocess.run(["git", "init", "-q"], cwd=self.root, env=self.env, check=True)

    def run_agentdrop(self, *args, answers=None, target="."):
        cmd = [sys.executable, str(self.script), *args, "--docs", "track", target]
        if answers is None:
            r = subprocess.run(cmd, cwd=self.root, env=self.env, text=True,
                               stdin=subprocess.DEVNULL, capture_output=True)
        else:
            if pty is None:
                self.skipTest("no pty on Windows")
            master, slave = pty.openpty()
            os.write(master, "".join(a + "\n" for a in answers).encode())
            r = subprocess.run(cmd, cwd=self.root, env=self.env, text=True,
                               stdin=slave, capture_output=True)
            os.close(slave)
            os.close(master)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def agents(self):
        return (self.root / "AGENTS.md").read_text()

    def hooks(self):
        data = json.loads((self.root / ".claude" / "settings.json").read_text())
        return {event: [h["command"] for g in groups for h in g["hooks"]]
                for event, groups in data["hooks"].items()}

    def session_start(self):
        r = subprocess.run([BASH, "scripts/check_docs.sh", "--session-start"], cwd=self.root,
                           env=self.env, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    def test_flag_adds_block_registries_and_hooks(self):
        out = self.run_agentdrop("--research")
        self.assertIn("research: added block", out)
        text = self.agents()
        # the research block sits right under the charter block
        self.assertLess(text.index("AGENTDROP:PROJECT:END"), text.index("AGENTDROP:RESEARCH:START"))
        for rel in ("docs/ASKS.md", "docs/HYPOTHESES.md", "docs/CLAIMS.md", "scripts/owner_asks.py",
                    ".claude/agents/skeptic.md", ".claude/agents/acceptance-judge.md",
                    ".claude/skills/harvest/SKILL.md"):
            self.assertTrue((self.root / rel).exists(), rel)
        self.assertIn("^docs/(ASKS|HYPOTHESES|CLAIMS)\\.md$", (self.root / ".docs-allow").read_text())
        hooks = self.hooks()
        self.assertTrue(any("--stop-hook" in c for c in hooks["Stop"]))
        self.assertTrue(any("--session-start" in c for c in hooks["SessionStart"]))
        if BASH:   # the docs guard accepts the registries
            subprocess.run(["git", "add", "-A"], cwd=self.root, env=self.env, check=True)
            r = subprocess.run([BASH, "scripts/check_docs.sh"], cwd=self.root, env=self.env,
                               text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_rerun_keeps_mode_and_no_research_removes_block_only(self):
        self.run_agentdrop("--research")
        self.run_agentdrop()
        self.assertIn("AGENTDROP:RESEARCH:START", self.agents())
        out = self.run_agentdrop("--no-research")
        self.assertIn("removed research block", out)
        self.assertNotIn("AGENTDROP:RESEARCH", self.agents())
        self.assertTrue((self.root / "docs" / "ASKS.md").exists())

    def test_first_setup_in_a_terminal_asks(self):
        out = self.run_agentdrop(answers=["y"])
        self.assertIn("Is this a research project?", out)
        self.assertIn("AGENTDROP:RESEARCH:START", self.agents())
        out = self.run_agentdrop(answers=[""])   # set up already: no second question
        self.assertNotIn("Is this a research project?", out)

    def test_plain_setup_without_terminal_does_not_turn_research_on(self):
        self.run_agentdrop()
        self.assertNotIn("AGENTDROP:RESEARCH", self.agents())
        self.assertFalse((self.root / "docs" / "ASKS.md").exists())

    @unittest.skipUnless(BASH, "needs bash")
    def test_session_start_reminds_to_harvest_after_five_passes(self):
        self.run_agentdrop()
        log = self.root / "docs" / "LOG.md"
        head, marker = log.read_text().split("\n<!-- harvest -->")
        entries = "".join(f"## 0{i}.10.2026 — B{i} pass\n\n- done\n\n" for i in range(1, 5))
        log.write_text(head + entries + "\n<!-- harvest -->" + marker)
        self.assertEqual(self.session_start(), "")            # four passes: quiet
        log.write_text(head + "## 05.10.2026 — B5 pass\n\n" + entries + "\n<!-- harvest -->" + marker)
        self.assertIn("5 passes", self.session_start())

    @unittest.skipUnless(BASH, "needs bash")
    def test_session_start_counts_unregistered_owner_messages(self):
        self.run_agentdrop("--research")
        asks = self.root / "docs" / "ASKS.md"
        asks.write_text(asks.read_text().replace("Checked up to: —", "Checked up to: 2026-09-26T10:00"))
        transcripts = self.home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(self.root))
        transcripts.mkdir(parents=True)
        rows = [{"type": "user", "timestamp": "2026-09-26T09:00:00Z", "message": {"content": "old ask"}},
                {"type": "user", "timestamp": "2026-09-26T11:00:00Z", "message": {"content": "look wider"}},
                {"type": "user", "timestamp": "2026-09-26T11:05:00Z", "message": {"content": "<command>x"}}]
        (transcripts / "s1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.assertIn("1 owner messages", self.session_start())

    def test_owned_files_are_refreshed_templates_are_not(self):
        self.run_agentdrop()
        guard = self.root / "scripts" / "check_docs.sh"
        guard.write_text("#!/usr/bin/env bash\n# old guard\n")
        (self.root / "docs" / "STATE.md").write_text("# STATE\n\nmine\n")
        out = self.run_agentdrop()
        self.assertIn("scripts/check_docs.sh", out)
        self.assertIn("--session-start", guard.read_text())
        self.assertEqual((self.root / "docs" / "STATE.md").read_text(), "# STATE\n\nmine\n")

    def test_kit_update_replaces_untouched_files_and_keeps_edits(self):
        clone = self.home.parent / "clone"
        shutil.copytree(REPO / "kit", clone / "kit")
        shutil.copy2(REPO / "agentdrop", clone / "agentdrop")
        self.script = clone / "agentdrop"
        self.run_agentdrop()                                   # first run installs the kit
        kit = self.home / ".agentdrop" / "kit"
        (kit / "docs" / "STATE.md").write_text("# my own STATE template\n")
        for rel in ("docs/STATE.md", "docs/TODO.md"):          # a new release changes both
            src = clone / "kit" / rel
            src.write_text(src.read_text() + "\nnew line from upstream\n")
        out = self.run_agentdrop()
        self.assertIn("new line from upstream", (kit / "docs" / "TODO.md").read_text())
        self.assertEqual((kit / "docs" / "STATE.md").read_text(), "# my own STATE template\n")
        self.assertIn("new line from upstream",
                      (self.home / ".agentdrop" / "kit.new" / "docs" / "STATE.md").read_text())
        self.assertIn("Kept your edited versions", out)


if __name__ == "__main__":
    unittest.main()
