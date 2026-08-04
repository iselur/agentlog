"""The hour it names has to be an hour inside the period it is reporting.

`agentlog today` ends on a line like `1 session · busiest 03:00–04:00`.  Every
other number on that screen is clipped to the day — the commands, the files, the
turns, the active time — but the busiest hour was counted from the session's
*whole* event list.  So a session that worked hard at 03:00 yesterday and ran two
commands at 14:00 today had `today` report `busiest 03:00–04:00`: an hour in
which, today, nothing happened at all.

It is the one line that says *when*, which is exactly what makes it hard to
notice being wrong.  The rest of the digest agrees with itself and this one line
quietly disagrees with all of it.
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

SID = "1a1a1a1a-0000-4000-8000-000000000001"


class Case(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-busiest-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.dir = os.path.join(self.home, ".claude", "projects", "-home-you-api")
        os.makedirs(self.dir)
        self.midnight = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0)
        self.records = []

    def work(self, when, count, minutes_apart=4):
        """``count`` commands, starting at ``when``, a few minutes apart."""
        for n in range(count):
            i = len(self.records)
            self.records.append({
                "type": "assistant", "uuid": "u%d" % i, "sessionId": SID,
                "cwd": "/home/you/api",
                "timestamp": (when + timedelta(minutes=n * minutes_apart)).isoformat(),
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t%d" % i, "name": "Bash",
                     "input": {"command": "step %d" % i}}]}})

    def turns(self, when, count):
        """User turns, which have never counted towards the busiest hour."""
        for n in range(count):
            i = len(self.records)
            self.records.append({
                "type": "user", "uuid": "v%d" % i, "sessionId": SID,
                "cwd": "/home/you/api",
                "timestamp": (when + timedelta(minutes=n)).isoformat(),
                "message": {"role": "user", "content": "do the thing"}})

    def write(self):
        with open(os.path.join(self.dir, SID + ".jsonl"), "w") as fh:
            for r in self.records:
                fh.write(json.dumps(r) + "\n")

    def digest(self, period="today"):
        self.write()
        p = subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home, period],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100"))
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def busiest(self, period="today"):
        """The hour the digest names, or None if it names none."""
        for line in self.digest(period).splitlines():
            if "busiest" in line:
                return line.split("busiest", 1)[1].strip()
        return None

    def sessions(self, since, until):
        self.write()
        found, _sources, _unusable = parser.find_sessions(self.home)
        return window._filter_sessions(found, since, until)


class TestTheHourIsInsideThePeriod(Case):
    """One session, two days, and each day's digest names its own hour."""

    def setUp(self):
        super().setUp()
        # Ten commands at 03:00 yesterday; two at 14:00 today.
        self.work(self.midnight - timedelta(hours=21), 10)
        self.work(self.midnight + timedelta(hours=14), 2, minutes_apart=2)

    def test_today_names_an_hour_that_happened_today(self):
        self.assertEqual(self.busiest("today"), "14:00–15:00")

    def test_yesterday_names_an_hour_that_happened_yesterday(self):
        self.assertEqual(self.busiest("yesterday"), "03:00–04:00")

    def test_the_rest_of_the_line_already_agreed(self):
        # The commands were clipped correctly all along, which is what made the
        # hour beside them look sound.
        out = self.digest("today")
        self.assertIn("2 commands", out)


class TestTheOtherEdgeToo(Case):
    """The same mistake at the far end: the busy hour is *after* the window."""

    def test_yesterday_is_not_told_about_today(self):
        # Two commands yesterday at 03:00, ten today at 14:00.  `yesterday` has
        # only one hour it could honestly name.
        self.work(self.midnight - timedelta(hours=21), 2)
        self.work(self.midnight + timedelta(hours=14), 10, minutes_apart=2)
        self.assertEqual(self.busiest("yesterday"), "03:00–04:00")

    def test_and_today_still_names_its_own(self):
        self.work(self.midnight - timedelta(hours=21), 2)
        self.work(self.midnight + timedelta(hours=14), 10, minutes_apart=2)
        self.assertEqual(self.busiest("today"), "14:00–15:00")


class TestWhatDidNotChange(Case):

    def test_a_session_inside_one_day_is_unaffected(self):
        self.work(self.midnight + timedelta(hours=9), 3)
        self.work(self.midnight + timedelta(hours=16), 8)
        self.assertEqual(self.busiest("today"), "16:00–17:00")

    def test_user_turns_still_do_not_count(self):
        # A conversation is not activity: twenty turns in one hour must not
        # outvote three tool calls in another.
        self.turns(self.midnight + timedelta(hours=11), 20)
        self.work(self.midnight + timedelta(hours=16), 3)
        self.assertEqual(self.busiest("today"), "16:00–17:00")

    def test_a_tie_names_the_earlier_hour(self):
        self.work(self.midnight + timedelta(hours=9), 3)
        self.work(self.midnight + timedelta(hours=16), 3)
        self.assertEqual(self.busiest("today"), "09:00–10:00")

    def test_no_events_names_no_hour(self):
        self.assertIsNone(render._busiest_hour([]))


class TestTheUnitItself(Case):
    """Straight at `_busiest_hour`, since the digest hides half of it."""

    def test_it_counts_only_events_inside_the_window(self):
        self.work(self.midnight - timedelta(hours=21), 10)
        self.work(self.midnight + timedelta(hours=14), 2, minutes_apart=2)
        today = self.sessions(self.midnight, self.midnight + timedelta(days=1))
        self.assertEqual(render._busiest_hour(today), "14:00–15:00")

    def test_a_session_with_no_window_keeps_every_event(self):
        # `list` and `show` ask for no period, so nothing has clipped these and
        # the answer is over the session's whole life.
        self.work(self.midnight - timedelta(hours=21), 10)
        self.work(self.midnight + timedelta(hours=14), 2, minutes_apart=2)
        self.write()
        found, _sources, _unusable = parser.find_sessions(self.home)
        self.assertEqual(render._busiest_hour(found), "03:00–04:00")


if __name__ == "__main__":
    unittest.main()
