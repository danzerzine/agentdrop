"""End-to-end: a project's own checks survive `agentdrop .`.

An owned kit file the project edited is kept, with a message on how to merge; untouched
copies are still refreshed; scripts/check_docs.local.sh runs from the guard and pre-commit.
Runs the real script against throwaway projects with a throwaway HOME.
    python3 -m unittest discover tests
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")
LOCAL_CHECK = """#!/usr/bin/env bash
# project check: no FORBIDDEN word in staged or tracked docs
if [ "${1:-}" = --staged ]; then files=$(git diff --cached --name-only -- docs); else files=$(git ls-files docs); fi
hits=$(printf '%s\\n' "$files" | while read -r f; do [ -f "$f" ] && grep -l FORBIDDEN "$f"; done || true)
[ -z "$hits" ] && exit 0
echo "Forbidden word in: $hits"
exit 1
"""


class ProjectChecks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.home = base / "home"
        self.root = base / "proj"
        self.home.mkdir()
        self.root.mkdir()
        # a clone without git history, so the only known versions are the ones installed here
        self.clone = base / "clone"
        shutil.copytree(REPO / "kit", self.clone / "kit")
        shutil.copy2(REPO / "agentdrop", self.clone / "agentdrop")
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.git("init", "-q")
        self.guard = self.root / "scripts" / "check_docs.sh"
        self.hook = self.root / ".githooks" / "pre-commit"

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, env=self.env, text=True, capture_output=True)

    def run_agentdrop(self):
        r = subprocess.run([sys.executable, str(self.clone / "agentdrop"), "--no-research",
                            "--docs", "track", "."], cwd=self.root, env=self.env, text=True,
                           stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def release(self, rel, line):
        """A new agentdrop release changes a kit file."""
        src = self.clone / "kit" / rel
        src.write_text(src.read_text() + line)

    def test_untouched_owned_files_get_the_new_release(self):
        self.run_agentdrop()
        self.release("scripts/check_docs.sh", "# new release\n")
        self.release(".githooks/pre-commit", "# new release\n")
        out = self.run_agentdrop()
        self.assertIn("# new release", self.guard.read_text())
        self.assertIn("# new release", self.hook.read_text())
        self.assertNotIn("kept", out)

    def test_edited_guard_and_hook_are_kept_with_a_merge_hint(self):
        self.run_agentdrop()
        own = self.guard.read_text().replace("set -euo pipefail", "set -euo pipefail\n# project's own check", 1)
        self.guard.write_text(own)
        self.hook.write_text(self.hook.read_text() + "scripts/extra_check.py --staged\n")
        self.release("scripts/check_docs.sh", "# new release\n")
        self.release(".githooks/pre-commit", "# new release\n")
        out = self.run_agentdrop()
        self.assertEqual(self.guard.read_text(), own)
        self.assertIn("scripts/extra_check.py", self.hook.read_text())
        self.assertIn("scripts/check_docs.sh", out)
        self.assertIn("kept: this project changed it", out)
        self.assertIn("scripts/check_docs.local.sh", out)
        self.assertIn(f"cp {self.home / '.agentdrop' / 'kit' / 'scripts' / 'check_docs.sh'} scripts/check_docs.sh", out)
        # the same on the next run: never overwritten, even without a new release
        self.run_agentdrop()
        self.assertEqual(self.guard.read_text(), own)

    def test_merged_copy_is_refreshed_again(self):
        self.run_agentdrop()
        self.guard.write_text(self.guard.read_text() + "# project's own check\n")
        self.release("scripts/check_docs.sh", "# new release\n")
        self.run_agentdrop()
        shutil.copy2(self.home / ".agentdrop" / "kit" / "scripts" / "check_docs.sh", self.guard)
        self.release("scripts/check_docs.sh", "# second release\n")
        self.run_agentdrop()
        self.assertIn("# second release", self.guard.read_text())

    @unittest.skipIf(BASH is None, "needs bash")
    def test_local_checks_run_from_the_guard_and_pre_commit(self):
        self.run_agentdrop()
        local = self.root / "scripts" / "check_docs.local.sh"
        local.write_text(LOCAL_CHECK)
        (self.root / "docs" / "STATE.md").write_text("# STATE\n\nFORBIDDEN here\n")
        self.git("add", "-A")
        commit = self.git("commit", "-qm", "docs")
        self.assertNotEqual(commit.returncode, 0)
        self.assertIn("Forbidden word in: docs/STATE.md", commit.stderr)
        guard = subprocess.run([BASH, "scripts/check_docs.sh"], cwd=self.root, env=self.env,
                               text=True, capture_output=True)
        self.assertEqual(guard.returncode, 2)
        self.assertIn("Forbidden word in: docs/STATE.md", guard.stderr)
        stop = subprocess.run([BASH, "scripts/check_docs.sh", "--stop-hook"], cwd=self.root,
                              env=self.env, text=True, capture_output=True)
        self.assertIn("Forbidden word", stop.stdout)
        (self.root / "docs" / "STATE.md").write_text("# STATE\n\nclean\n")
        self.git("add", "-A")
        self.assertEqual(self.git("commit", "-qm", "docs").returncode, 0)
        # agentdrop never touches the local file
        self.release("scripts/check_docs.sh", "# new release\n")
        self.run_agentdrop()
        self.assertEqual(local.read_text(), LOCAL_CHECK)
        self.assertIn("# new release", self.guard.read_text())


if __name__ == "__main__":
    unittest.main()
