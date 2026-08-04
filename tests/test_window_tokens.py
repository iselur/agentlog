"""Tokens spent inside the window, not over the session's whole life.

Every other number in a day's digest is clipped to that day — the commands, the
files, the turns, the errors, the active time.  The token counts were not.  A
session that ran all week put its entire week's spend into each day it touched,
sitting on the line directly under a correctly clipped `3 commands`.

Measured on the real logs the day this was written, `agentlog today`:

    4ef1361b   88,336,687 reported     14,176,360 spent today    6.2x
    251407af  309,614,450 reported    210,414,033 spent today    1.5x

Same shape as the busiest-hour defect and the same reason it survives: one line
disagreeing with a screenful that agrees with itself.  Nobody checks the token
count against anything, because there is nothing on screen to check it against.

The fix records what each turn cost *and when*, so a window can add up its own.
Both agents can say: Claude writes a usage block per assistant message, Codex a
running total per turn whose successive differences are the same thing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog import cli, parser, render  # noqa: E402

SID = "1a1a1a1a-0000-4000-8000-000000000001"
CID = "019f80fa-4d34-7513-8add-a5368508ba77"


class Case(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-wintok-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.dir = os.path.join(self.home, ".claude", "projects", "-home-you-api")
        os.makedirs(self.dir)
        self.codex_dir = os.path.join(self.home, ".codex", "sessions")
        os.makedirs(self.codex_dir)
        self.midnight = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0)
        self.records = []

    def spend(self, when, tokens_in, tokens_out, msg_id=None, repeat=1):
        """An assistant message costing ``tokens_in``/``tokens_out`` at ``when``.

        ``repeat`` writes the same message id more than once, which is what
        Claude Code does when one reply is split across records: the usage block
        is repeated verbatim and must be counted once.
        """
        i = len(self.records)
        mid = msg_id or ("msg_%d" % i)
        for n in range(repeat):
            self.records.append({
                "type": "assistant", "uuid": "u%d_%d" % (i, n), "sessionId": SID,
                "cwd": "/home/you/api", "timestamp": when.isoformat(),
                "message": {"role": "assistant", "id": mid, "model": "claude-opus-5",
                            "usage": {"input_tokens": tokens_in,
                                      "cache_creation_input_tokens": 0,
                                      "cache_read_input_tokens": 0,
                                      "output_tokens": tokens_out},
                            "content": [{"type": "tool_use", "id": "t%d_%d" % (i, n),
                                         "name": "Bash",
                                         "input": {"command": "step %d" % i}}]}})

    def write(self):
        with open(os.path.join(self.dir, SID + ".jsonl"), "w") as fh:
            for r in self.records:
                fh.write(json.dumps(r) + "\n")

    def day(self, offset=0):
        self.write()
        start = self.midnight - timedelta(days=offset)
        found, _sources, _unusable = parser.find_sessions(self.home)
        return cli._filter_sessions(found, start, start + timedelta(days=1))

    def lifetime(self):
        self.write()
        found, _sources, _unusable = parser.find_sessions(self.home)
        return found

    def digest(self, *args):
        self.write()
        p = subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home, *args],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100"))
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout


class TestTheDayGetsTheDaysSpend(Case):

    def setUp(self):
        super().setUp()
        # A thousand yesterday, a hundred today.
        self.spend(self.midnight - timedelta(hours=6), 1000, 40)
        self.spend(self.midnight + timedelta(hours=9), 100, 4)

    def test_today_counts_only_today(self):
        got, = self.day(0)
        self.assertEqual(got["tokens_in"], 100)
        self.assertEqual(got["tokens_out"], 4)

    def test_yesterday_counts_only_yesterday(self):
        got, = self.day(1)
        self.assertEqual(got["tokens_in"], 1000)
        self.assertEqual(got["tokens_out"], 40)

    def test_the_digest_prints_the_clipped_number(self):
        # The per-session view is where the token line appears.
        out = self.digest("--sessions", "today")
        self.assertIn("in: 100", out)
        self.assertNotIn("1,100", out)

    def test_the_days_add_up_to_the_lifetime(self):
        whole, = self.lifetime()
        days = sum(s["tokens_in"] for n in (0, 1) for s in self.day(n))
        self.assertEqual(days, whole["tokens_in"])
        self.assertEqual(whole["tokens_in"], 1100)


class TestADayItSpentNothing(Case):
    """The quiet-day rule again: an empty window is an answer, not a gap."""

    def test_a_day_between_two_busy_ones_spent_nothing(self):
        self.spend(self.midnight - timedelta(days=2) + timedelta(hours=9), 500, 20)
        self.spend(self.midnight + timedelta(hours=9), 500, 20)
        quiet, = self.day(1)
        self.assertEqual(quiet["tokens_in"], 0)
        self.assertEqual(quiet["tokens_out"], 0)

    def test_and_the_digest_says_so_rather_than_the_lifetime(self):
        self.spend(self.midnight - timedelta(days=2) + timedelta(hours=9), 500, 20)
        self.spend(self.midnight + timedelta(hours=9), 500, 20)
        self.assertNotIn("in: 1,000", self.digest("yesterday"))


class TestWhatDidNotChange(Case):

    def test_an_unclipped_view_still_shows_the_lifetime(self):
        # `list` and `show` ask for no period, so they report the whole session.
        self.spend(self.midnight - timedelta(hours=6), 1000, 40)
        self.spend(self.midnight + timedelta(hours=9), 100, 4)
        whole, = self.lifetime()
        self.assertEqual(whole["tokens_in"], 1100)
        self.assertIn("1,100", self.digest("show", SID))

    def test_a_repeated_message_id_is_still_counted_once(self):
        # One reply written across three records, all carrying the same usage.
        self.spend(self.midnight + timedelta(hours=9), 700, 30, repeat=3)
        got, = self.day(0)
        self.assertEqual(got["tokens_in"], 700)
        self.assertEqual(got["tokens_out"], 30)

    def test_a_session_inside_one_day_is_unaffected(self):
        self.spend(self.midnight + timedelta(hours=9), 700, 30)
        self.spend(self.midnight + timedelta(hours=11), 300, 10)
        got, = self.day(0)
        self.assertEqual(got["tokens_in"], 1000)
        self.assertEqual(got["tokens_out"], 40)

    def test_a_session_that_reports_no_tokens_still_reports_none(self):
        blank = parser._empty_session("x", "claude")
        cli._clip_tokens(blank, self.midnight, self.midnight + timedelta(days=1))
        self.assertIsNone(blank["tokens_in"])
        self.assertIsNone(blank["tokens_out"])

    def test_a_total_with_nothing_behind_it_is_left_alone(self):
        # No per-turn evidence at all — a log shape we cannot see inside.  The
        # lifetime total is a worse answer than a clipped one and a better
        # answer than a made-up one.
        opaque = parser._empty_session("x", "claude")
        opaque["tokens_in"] = 4242
        opaque["tokens_out"] = 42
        opaque["token_events"] = []
        cli._clip_tokens(opaque, self.midnight, self.midnight + timedelta(days=1))
        self.assertEqual(opaque["tokens_in"], 4242)
        self.assertEqual(opaque["tokens_out"], 42)

    def test_evidence_that_all_falls_outside_is_an_answer_not_a_gap(self):
        # The other side of the same coin: this session we *can* see inside, and
        # what we can see is that it spent nothing here.  Same starting total,
        # opposite result, and the only difference is whether there is evidence.
        seen = parser._empty_session("x", "claude")
        seen["tokens_in"] = 4242
        seen["tokens_out"] = 42
        seen["token_events"] = [
            (self.midnight - timedelta(hours=3), 4242, 42),
        ]
        cli._clip_tokens(seen, self.midnight, self.midnight + timedelta(days=1))
        self.assertEqual(seen["tokens_in"], 0)
        self.assertEqual(seen["tokens_out"], 0)


class TestSpendingWithNothingToShowForIt(Case):
    """A reply that costs tokens and calls no tool is still spending.

    The window gets tightened onto the session's first and last *event* — a
    tool call, a turn, an error — so that a session left open overnight is not
    billed for the night.  Token events are a separate list and are not in that
    reckoning, so anything spent after the day's last tool call fell outside the
    tightened edge and was silently dropped.  It showed up as a week whose
    tokens came to more than its seven days added up to, by 3.4M.
    """

    def think(self, when, tokens_in, tokens_out):
        """An assistant reply with usage and no tool call — no event, real cost."""
        i = len(self.records)
        self.records.append({
            "type": "assistant", "uuid": "th%d" % i, "sessionId": SID,
            "cwd": "/home/you/api", "timestamp": when.isoformat(),
            "message": {"role": "assistant", "id": "think_%d" % i,
                        "model": "claude-opus-5",
                        "usage": {"input_tokens": tokens_in,
                                  "cache_creation_input_tokens": 0,
                                  "cache_read_input_tokens": 0,
                                  "output_tokens": tokens_out},
                        "content": [{"type": "text", "text": "here you go"}]}})

    def setUp(self):
        super().setUp()
        # Yesterday, so the day window really is a clip.  Then one tool call at
        # 09:00 and a plain reply at 23:00 that costs 500.
        self.spend(self.midnight - timedelta(hours=6), 1000, 40)
        self.spend(self.midnight + timedelta(hours=9), 10, 1)
        self.think(self.midnight + timedelta(hours=23), 500, 20)

    def test_the_late_reply_is_counted(self):
        got, = self.day(0)
        self.assertEqual(got["tokens_in"], 510)
        self.assertEqual(got["tokens_out"], 21)

    def test_the_days_still_add_up_to_the_lifetime(self):
        whole, = self.lifetime()
        days = sum(s["tokens_in"] for n in (0, 1) for s in self.day(n))
        self.assertEqual(days, whole["tokens_in"])

    def test_an_early_reply_is_counted_too(self):
        # The other edge: spending before the day's first tool call.
        self.think(self.midnight + timedelta(hours=1), 300, 12)
        got, = self.day(0)
        self.assertEqual(got["tokens_in"], 810)

    def test_yesterday_did_not_gain_it(self):
        got, = self.day(1)
        self.assertEqual(got["tokens_in"], 1000)

    def test_the_tightened_edges_themselves_did_not_move(self):
        # The duration is still measured from real events, which is the whole
        # point of tightening.  Only the tokens stopped being clipped by it.
        got, = self.day(0)
        self.assertEqual(got["win_start"], self.midnight + timedelta(hours=9))
        self.assertEqual(got["win_end"], self.midnight + timedelta(hours=9))


class TestCodexToo(Case):
    """Codex reports a running total; its successive differences are the turns."""

    def codex(self, *stamps):
        """One token_count record per (when, in, out), totals accumulated."""
        path = os.path.join(self.codex_dir, "rollout-%s.jsonl" % CID)
        ti = to = 0
        with open(path, "w") as fh:
            fh.write(json.dumps({
                "timestamp": stamps[0][0].isoformat(), "type": "session_meta",
                "payload": {"id": CID, "cwd": "/home/you/api"}}) + "\n")
            for when, tin, tout in stamps:
                ti += tin
                to += tout
                fh.write(json.dumps({
                    "timestamp": when.isoformat(), "type": "event_msg",
                    "payload": {"type": "token_count", "info": {
                        "last_token_usage": {"input_tokens": tin,
                                             "output_tokens": tout},
                        "total_token_usage": {"input_tokens": ti,
                                              "output_tokens": to}}}}) + "\n")

    def codex_day(self, offset=0):
        start = self.midnight - timedelta(days=offset)
        found, _sources, _unusable = parser.find_sessions(self.home)
        got = [s for s in cli._filter_sessions(
            found, start, start + timedelta(days=1)) if s["source"] == "codex"]
        return got

    def test_the_running_total_is_clipped_by_its_differences(self):
        self.codex((self.midnight - timedelta(hours=6), 1000, 40),
                   (self.midnight + timedelta(hours=9), 100, 4))
        got, = self.codex_day(0)
        self.assertEqual(got["tokens_in"], 100)
        self.assertEqual(got["tokens_out"], 4)

    def test_yesterday_gets_its_own(self):
        self.codex((self.midnight - timedelta(hours=6), 1000, 40),
                   (self.midnight + timedelta(hours=9), 100, 4))
        got, = self.codex_day(1)
        self.assertEqual(got["tokens_in"], 1000)
        self.assertEqual(got["tokens_out"], 40)

    def test_the_lifetime_is_still_the_final_total(self):
        self.codex((self.midnight - timedelta(hours=6), 1000, 40),
                   (self.midnight + timedelta(hours=9), 100, 4))
        found, _sources, _unusable = parser.find_sessions(self.home)
        codex, = [s for s in found if s["source"] == "codex"]
        self.assertEqual(codex["tokens_in"], 1100)
        self.assertEqual(codex["tokens_out"], 44)


if __name__ == "__main__":
    unittest.main()
