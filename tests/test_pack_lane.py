"""A running pack's last line is the session's own words, never a subagent's working notes.

    python3 -m unittest tests/test_pack_lane.py
"""
import json
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_loader = SourceFileLoader("agentdrop_lane", str(REPO / "agentdrop"))
ad = module_from_spec(spec_from_loader(_loader.name, _loader))
_loader.exec_module(ad)


def said(text, parent=None):
    return json.dumps({"type": "assistant", "parent_tool_use_id": parent,
                       "message": {"content": [{"type": "text", "text": text}]}})


def ran(command):
    return json.dumps({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": command}}]}})


class PackLane(unittest.TestCase):
    def test_tickets_include_those_the_run_claimed(self):
        # a run given B173 that went on to «Next up» ran B174 and B170 too; its words about B9 are not a claim
        d = Path(tempfile.mkdtemp())
        f = d / "20260928-1538.jsonl"
        (d / "20260928-1538.prompt.md").write_text("1. Как Google классифицирует (B173, P2). Why: …\n", encoding="utf-8")
        f.write_text("\n".join([ran("agentdrop claim B173"), said("Беру agentdrop claim B9 позже."),
                                 ran("cd /x && agentdrop claim B174 && git status"), ran("agentdrop claim B170"),
                                 ran("agentdrop claim B174")]) + "\n", encoding="utf-8")
        self.assertEqual(ad.pack_tickets_of(f), ["B173", "B174", "B170"])

    def test_last_skips_subagent_text(self):
        d = Path(tempfile.mkdtemp())
        f = d / "20260928-1538.jsonl"
        f.write_text("\n".join([said("Разметка идёт, пишу анализ."), said("done  100", parent="toolu_1")]) + "\n",
                     encoding="utf-8")
        (d / "20260928-1538.pid").write_text(str(os.getpid()))
        lane = ad.pack_lane(f)
        self.assertTrue(lane["running"])
        self.assertEqual(lane["last"], "Разметка идёт, пишу анализ.")


if __name__ == "__main__":
    unittest.main()
