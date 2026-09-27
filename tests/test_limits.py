"""End-to-end: `agentdrop limits` reads the rate-limit events in run logs and answers whether an
autonomous run may start.

Runs the real script with a throwaway HOME and hand-written run logs.
    python3 -m unittest discover tests
"""

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def event(five, seven, seven_reset):
    return json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
        "five_hour": {"utilization": five, "resetsAt": int(seven_reset - 86400)},
        "seven_day": {"utilization": seven, "resetsAt": int(seven_reset)}}}})


class Limits(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.home = base / "home"
        self.proj = base / "proj"
        self.logs = self.home / ".agentdrop" / "scheduled" / "logs"
        self.logs.mkdir(parents=True)
        (self.proj / "docs" / ".runs" / "pack").mkdir(parents=True)
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home), "AGENTDROP_OFFLINE": "1"}
        self.now = dt.datetime.now().replace(second=0, microsecond=0)
        self.reset = (self.now + dt.timedelta(days=2)).timestamp()   # the week resets in two days

    def log(self, minutes_ago, five, seven, where=None, name="page-{}", written_ago=None):
        """A run started `minutes_ago` whose log was last written `written_ago` minutes ago (by default then too)."""
        at = self.now - dt.timedelta(minutes=minutes_ago)
        f = (where or self.logs) / (name.format(at.strftime("%Y%m%d-%H%M")) + ".jsonl")
        f.write_text('{"type":"system"}\n' + event(five, seven, self.reset) + "\n", encoding="utf-8")
        w = (self.now - dt.timedelta(minutes=minutes_ago if written_ago is None else written_ago)).timestamp()
        os.utime(f, (w, w))

    def limits(self):
        r = subprocess.run([sys.executable, str(REPO / "agentdrop"), "limits", "--json", str(self.proj)],
                           env=self.env, capture_output=True, text=True, timeout=60)
        return r.returncode, json.loads(r.stdout)

    def test_no_measurement_means_no(self):
        code, v = self.limits()
        self.assertEqual((code, v["can_start"], v["reason"]), (1, False, "no_reading"))

    def test_fresh_and_roomy_means_yes(self):
        self.log(min(self.now.hour * 60 + self.now.minute, 30), 0.10, 0.40)
        code, v = self.limits()
        self.assertEqual((code, v["can_start"], v["reason"]), (0, True, "ok"))
        self.assertEqual(v["five_hour"]["used"], 0.10)
        self.assertAlmostEqual(v["today"]["share"], 0.30, places=2)   # 60% free over two days

    def test_five_hour_window_over_70_means_no(self):
        self.log(1, 0.71, 0.40)
        code, v = self.limits()
        self.assertEqual((code, v["reason"]), (1, "five_hour"))
        self.log(0, 0.70, 0.40, name="page-{}-b")   # exactly 70% is still allowed
        self.assertEqual(self.limits()[1]["reason"], "ok")

    def test_daily_share_used_up_means_no(self):
        if self.now.hour < 1:
            self.skipTest("needs two measurements on the same day")
        self.log(self.now.minute + 50, 0.20, 0.40)          # the day's first measurement: 60% free, 30% a day
        self.log(0, 0.20, 0.70, where=self.proj / "docs" / ".runs" / "pack", name="{}-1")   # a pack run's log
        code, v = self.limits()
        self.assertEqual((code, v["reason"]), (1, "daily_share"))
        self.assertAlmostEqual(v["today"]["spent"], 0.30, places=2)

    def test_long_run_measures_by_its_last_write(self):
        self.log(180, 0.10, 0.40, written_ago=5)   # started three hours ago, still writing
        code, v = self.limits()
        self.assertEqual((code, v["reason"]), (0, "ok"))
        self.assertLess(v["age_min"], 10)

    def test_old_measurement_means_no(self):
        self.log(120, 0.10, 0.40)
        code, v = self.limits()
        self.assertEqual((code, v["reason"]), (1, "stale"))
        self.assertGreaterEqual(v["age_min"], 120)


if __name__ == "__main__":
    unittest.main()
