"""A day a session slept through is not a day it worked.

`active_spans` has a fallback: a session with no timestamped events keeps its
whole span, because we cannot see inside it and a lifetime total beats a made-up
one.  That is right for a session we know nothing about.  It was also firing for
a session we know everything about — one with four thousand events, none of them
on the day being asked for.  The window emptied the list, the fallback could not
tell that apart from an empty session, and handed back the window: a full
twenty-four hours of "work" on a day nothing happened.

It showed up as an arithmetic impossibility on the real logs.  A week is the
union of its days, so it cannot be shorter than they add up to — and the week
came to 31h against 111h for the seven days inside it, four of which reported
exactly 24h 00m.  Exactly twenty-four is the tell: that is the window, not the
work.
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


class Case(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-quiet-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.dir = os.path.join(self.home, ".claude", "projects", "-home-you-api")
        os.makedirs(self.dir)
        self.midnight = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0)
        self.records = []

    def busy(self, when, count=4, seconds_apart=60):
        """A burst of work starting at ``when``."""
        for n in range(count):
            i = len(self.records)
            self.records.append({
                "type": "assistant", "uuid": "u%d" % i, "sessionId": SID,
                "cwd": "/home/you/api",
                "timestamp": (when + timedelta(seconds=n * seconds_apart)).isoformat(),
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t%d" % i, "name": "Bash",
                     "input": {"command": "step %d" % i}}]}})

    def write(self):
        with open(os.path.join(self.dir, SID + ".jsonl"), "w") as fh:
            for r in self.records:
                fh.write(json.dumps(r) + "\n")

    def day(self, offset):
        """The sessions of the day ``offset`` days before today."""
        self.write()
        start = self.midnight - timedelta(days=offset)
        found, _sources, _unusable = parser.find_sessions(self.home)
        return cli._filter_sessions(found, start, start + timedelta(days=1))

    def span(self, days_back):
        """The sessions of the whole stretch from ``days_back`` ago to tonight."""
        self.write()
        start = self.midnight - timedelta(days=days_back)
        found, _sources, _unusable = parser.find_sessions(self.home)
        return cli._filter_sessions(found, start, self.midnight + timedelta(days=1))

    def digest(self, *args):
        self.write()
        p = subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home, *args],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100"))
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout


class TestTheQuietDayInTheMiddle(Case):
    """One session, busy at each end, asleep for the two days between."""

    def setUp(self):
        super().setUp()
        # Four minutes of work three days ago, four more today.  Nothing at all
        # on the two days in between.
        self.busy(self.midnight - timedelta(days=3) + timedelta(hours=10))
        self.busy(self.midnight + timedelta(hours=10))

    def test_a_day_it_slept_through_reports_no_work(self):
        self.assertAlmostEqual(render.active_seconds(self.day(2)), 0.0, places=1)

    def test_the_session_itself_says_zero_for_that_day(self):
        quiet = self.day(2)
        self.assertEqual(len(quiet), 1, "the session still overlaps that day")
        self.assertAlmostEqual(quiet[0]["window_s"], 0.0, places=1)
        self.assertEqual(quiet[0]["active_spans"], [])

    def test_the_digest_does_not_claim_the_whole_day(self):
        # Yesterday is one of the two it slept through.
        out = self.digest("yesterday")
        self.assertNotIn("24h", out)

    def test_a_day_it_worked_still_counts_that_work(self):
        self.assertAlmostEqual(render.active_seconds(self.day(0)), 180.0, places=1)

    def test_and_so_does_the_other_one(self):
        self.assertAlmostEqual(render.active_seconds(self.day(3)), 180.0, places=1)


class TestTheWeekIsNeverShorterThanItsDays(Case):
    """The invariant that caught it: a union cannot be smaller than its parts."""

    def setUp(self):
        super().setUp()
        self.busy(self.midnight - timedelta(days=3) + timedelta(hours=10))
        self.busy(self.midnight + timedelta(hours=10))

    def test_the_days_add_up_to_the_stretch(self):
        days = sum(render.active_seconds(self.day(n)) for n in range(4))
        self.assertAlmostEqual(render.active_seconds(self.span(3)), days, places=1)

    def test_no_single_day_beats_the_stretch(self):
        whole = render.active_seconds(self.span(3))
        for n in range(4):
            self.assertLessEqual(render.active_seconds(self.day(n)), whole + 1)

    def test_the_stretch_is_the_work_and_not_the_calendar(self):
        # Two bursts of three minutes each, three days apart.
        self.assertAlmostEqual(render.active_seconds(self.span(3)), 360.0, places=1)


class TestWhatTheFallbackIsActuallyFor(Case):
    """A session we cannot see inside still keeps its span.  That part was right."""

    def test_a_session_with_no_events_keeps_its_whole_span(self):
        blank = parser._empty_session("x", "claude")
        blank["start"] = self.midnight
        blank["end"] = self.midnight + timedelta(hours=3)
        blank["duration_s"] = 3 * 3600
        spans = parser.active_spans(blank)
        self.assertEqual(spans, [(blank["start"], blank["end"])])

    def test_it_holds_inside_a_window_too(self):
        blank = parser._empty_session("x", "claude")
        blank["start"] = self.midnight
        blank["end"] = self.midnight + timedelta(hours=3)
        blank["duration_s"] = 3 * 3600
        spans = parser.active_spans(blank, self.midnight,
                                    self.midnight + timedelta(hours=1))
        self.assertEqual(spans, [(self.midnight, self.midnight + timedelta(hours=1))])

    def test_events_without_timestamps_do_not_count_as_seeing_inside(self):
        # Every event is unstamped, so the window cannot be what emptied the
        # list — there was never anything in it to place.  Fall back.
        blank = parser._empty_session("x", "claude")
        blank["start"] = self.midnight
        blank["end"] = self.midnight + timedelta(hours=3)
        blank["events"] = [(None, "command", "ls"), (None, "command", "pwd")]
        self.assertEqual(parser.active_spans(blank),
                         [(blank["start"], blank["end"])])

    def test_one_stamped_event_is_enough_to_stop_guessing(self):
        # It worked at 09:00 and we are asking about 15:00.  We can see inside
        # this one, and what we can see is that nothing happened then.
        blank = parser._empty_session("x", "claude")
        blank["start"] = self.midnight
        blank["end"] = self.midnight + timedelta(hours=23)
        blank["events"] = [(self.midnight + timedelta(hours=9), "command", "ls")]
        self.assertEqual(
            parser.active_spans(blank, self.midnight + timedelta(hours=15),
                                self.midnight + timedelta(hours=16)),
            [])


class TestTheEdgesStillWork(Case):
    """Partly inside the window is not the same as wholly outside it."""

    def test_the_part_inside_is_what_counts(self):
        # Three minutes before midnight, three minutes after.  Today gets the
        # part that happened today.
        self.busy(self.midnight - timedelta(minutes=4))
        self.busy(self.midnight)
        self.assertAlmostEqual(render.active_seconds(self.day(0)), 180.0, places=1)

    def test_a_burst_that_stops_at_the_boundary(self):
        # All of it yesterday; today sees none of it and must not invent any.
        self.busy(self.midnight - timedelta(hours=2))
        self.assertAlmostEqual(render.active_seconds(self.day(0)), 0.0, places=1)


if __name__ == "__main__":
    unittest.main()
