"""End-to-end: `agentdrop status`, `claim` and `release` on a throwaway project.

    python3 -m unittest discover tests
"""

import json
import os
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


class PushLoop(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
