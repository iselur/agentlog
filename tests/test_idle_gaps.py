"""Time nobody was working is not active time.

The digest's headline number answers, in the README's own words, "how much of
the day had an agent working".  It was measured from the first thing a session
did to the last, so a session left sitting idle counted every idle hour as work.
On this machine, the day this test was written, `agentlog today` reported
**14h 21m active** where Claude Code's own `turn_duration` records — it writes
down how long each turn really took — added up to **3h 19m**.  Over the 76
sessions that carry those records, the old figure came to 14x the truth.

The rule now is that a silence longer than `IDLE_GAP_S` is not work.  A session
contributes the stretches it was busy, and the sum of those stretches is what is
reported and what the day's union is built from.  Five minutes is the threshold
because it is the one that matches: against those 76 sessions, splitting at five
minutes lands at 0.93 of the recorded turn time in aggregate and a median of
1.10 per session, and ten minutes overshoots on both.  Being a little under is
also the better way to be wrong for a number somebody might quote.

Two things deliberately did *not* change.  `duration_s` is still the whole span
from the first record to the last, because "how long was this session open" is a
real and different question.  And the union across sessions is still a union —
agents run in parallel, and two of them busy at once is one hour of the day, not
two.
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

from agentlog import window, parser, render  # noqa: E402

GAP = parser.IDLE_GAP_S


class Case(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-idle-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.dir = os.path.join(self.home, ".claude", "projects", "-home-you-api")
        os.makedirs(self.dir)
        self.base = datetime.now().astimezone().replace(
            hour=9, minute=0, second=0, microsecond=0)
        self.records = {}

    def busy(self, sid, *offsets):
        """A session doing one thing at each offset, in seconds from 09:00."""
        recs = self.records.setdefault(sid, [])
        for off in offsets:
            i = len(recs)
            recs.append({
                "type": "assistant", "uuid": "%s-%d" % (sid[:4], i),
                "sessionId": sid, "cwd": "/home/you/api",
                "timestamp": (self.base + timedelta(seconds=off)).isoformat(),
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t%d" % i, "name": "Bash",
                     "input": {"command": "step %d" % i}}]}})

    def write(self):
        for sid, recs in self.records.items():
            with open(os.path.join(self.dir, sid + ".jsonl"), "w") as fh:
                for r in recs:
                    fh.write(json.dumps(r) + "\n")

    def sessions(self):
        """Today's sessions, as the CLI assembles them."""
        self.write()
        found, _sources, _unusable = parser.find_sessions(self.home)
        day = self.base.replace(hour=0, minute=0, second=0, microsecond=0)
        return window._filter_sessions(found, day, day + timedelta(days=1))

    def active(self):
        return render.active_seconds(self.sessions())

    def run_log(self, *args):
        self.write()
        p = subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home, *args],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100"))
        self.assertEqual(p.returncode, 0, p.stderr)
        return p


SID_A = "1a1a1a1a-0000-4000-8000-000000000001"
SID_B = "2b2b2b2b-0000-4000-8000-000000000002"


class TestASilenceIsNotWork(Case):

    def test_an_idle_stretch_is_not_counted(self):
        # Two minutes of work, six hours of nothing, one more minute of work.
        self.busy(SID_A, 0, 60, 120, 6 * 3600, 6 * 3600 + 60)
        self.assertAlmostEqual(self.active(), 180, delta=1)

    def test_the_session_was_still_open_for_the_whole_span(self):
        # The change is to what counts as active, not to how long the session
        # existed.  Both questions are real and they have different answers.
        self.busy(SID_A, 0, 60, 120, 6 * 3600, 6 * 3600 + 60)
        s = self.sessions()[0]
        self.assertAlmostEqual(s["duration_s"], 6 * 3600 + 60, delta=1)

    def test_the_headline_says_minutes_not_hours(self):
        self.busy(SID_A, 0, 60, 120, 6 * 3600, 6 * 3600 + 60)
        out = self.run_log("today").stdout
        self.assertIn("3m", out)
        self.assertNotIn("6h", out)

    def test_many_short_bursts_across_a_long_session(self):
        # The shape an overnight agent actually makes: a burst an hour.
        offsets = []
        for hour in range(8):
            offsets += [hour * 3600, hour * 3600 + 30]
        self.busy(SID_A, *offsets)
        self.assertAlmostEqual(self.active(), 8 * 30, delta=1)


class TestEveryPlaceThatPrintsADuration(Case):
    """The headline is not the only number somebody reads."""

    def setUp(self):
        super().setUp()
        self.busy(SID_A, 0, 60, 120, 6 * 3600, 6 * 3600 + 60)

    def test_the_session_block_gives_both_numbers(self):
        # Three minutes of work inside six hours of being open.  Both are true
        # and the block says which is which, because the time range printed
        # beside them spans the whole six.
        out = self.run_log("--sessions").stdout
        self.assertIn("3m 00s active, 6h 01m open", out)

    def test_the_list_row_reports_active_time(self):
        # `list` asks for no window, so nothing has clipped these sessions —
        # the DUR column still has to mean what it means everywhere else.
        row = [ln for ln in self.run_log("list").stdout.splitlines()
               if ln.startswith("1a1a1a1a")]
        self.assertEqual(len(row), 1, self.run_log("list").stdout)
        self.assertIn("3m 00s", row[0])
        self.assertNotIn("6h", row[0])

    def test_the_project_line_reports_active_time(self):
        out = self.run_log("today").stdout
        line = [ln for ln in out.splitlines() if " api " in ln]
        self.assertTrue(line, out)
        self.assertIn("3m", line[0])

    def test_the_json_says_both_and_names_them(self):
        # A script reading `duration_s` alone would make the same mistake the
        # text output used to, so the working time is there under its own name.
        got, = json.loads(self.run_log("today", "--json").stdout)
        self.assertAlmostEqual(got["active_s"], 180, delta=1)
        self.assertAlmostEqual(got["duration_s"], 6 * 3600 + 60, delta=1)


class TestClippedAndIdleAtOnce(Case):
    """A session can straddle the window's edge *and* sit idle inside it."""

    def test_the_window_share_is_the_working_part_of_it(self):
        # It started yesterday evening, worked for two minutes after midnight,
        # slept, and worked for one more.  Today's share is three minutes.
        self.busy(SID_A, -12 * 3600)                      # yesterday, 21:00
        self.busy(SID_A, -9 * 3600 + 0, -9 * 3600 + 60,
                  -9 * 3600 + 120)                        # today, 00:00–00:02
        self.busy(SID_A, 0, 60)                           # today, 09:00–09:01
        s = self.sessions()[0]
        self.assertIsNotNone(s["window_s"], "the clip did not happen")
        self.assertAlmostEqual(s["window_s"], 180, delta=1)
        self.assertAlmostEqual(self.active(), 180, delta=1)


class TestWhereTheLineIs(Case):

    def test_a_gap_of_exactly_the_threshold_is_not_a_break(self):
        # "Longer than", not "at least" — so the boundary value keeps the work
        # together, and a test says which way round it goes.
        self.busy(SID_A, 0, GAP, 2 * GAP)
        self.assertAlmostEqual(self.active(), 2 * GAP, delta=1)

    def test_a_second_over_the_threshold_is_a_break(self):
        self.busy(SID_A, 0, 60, 60 + GAP + 1, 60 + GAP + 61)
        self.assertAlmostEqual(self.active(), 120, delta=1)

    def test_a_dense_session_is_unchanged(self):
        self.busy(SID_A, *range(0, 601, 60))
        self.assertAlmostEqual(self.active(), 600, delta=1)


class TestTheDayIsStillAUnion(Case):

    def test_two_agents_busy_at_once_are_one_hour_of_the_day(self):
        # Sessions run in parallel; summing them reported more hours than the
        # day contains, which is why this was a union in the first place.
        self.busy(SID_A, 0, 60, 120)
        self.busy(SID_B, 0, 60, 120)
        self.assertAlmostEqual(self.active(), 120, delta=1)

    def test_two_sessions_idle_over_the_same_hours_do_not_fill_them(self):
        for sid in (SID_A, SID_B):
            self.busy(sid, 0, 60, 6 * 3600, 6 * 3600 + 60)
        self.assertAlmostEqual(self.active(), 120, delta=1)

    def test_work_that_does_not_overlap_still_adds_up(self):
        self.busy(SID_A, 0, 60)
        self.busy(SID_B, 6 * 3600, 6 * 3600 + 120)
        self.assertAlmostEqual(self.active(), 180, delta=1)


class TestTheFallbacksHold(Case):
    """A session we cannot see inside keeps the answer it had before."""

    def test_a_session_without_usable_timestamps_keeps_its_span(self):
        s = parser._empty_session(SID_A, "claude")
        s["start"] = self.base
        s["end"] = self.base + timedelta(hours=3)
        s["duration_s"] = 3 * 3600
        s["events"] = []
        self.assertAlmostEqual(render.active_seconds([s]), 3 * 3600, delta=1)

    def test_a_single_event_is_an_instant_not_a_span(self):
        self.busy(SID_A, 0)
        self.assertAlmostEqual(self.active(), 0, delta=1)

    def test_no_sessions_is_no_time(self):
        self.assertEqual(render.active_seconds([]), 0.0)


if __name__ == "__main__":
    unittest.main()
