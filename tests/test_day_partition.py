"""Consecutive days must partition the work: nothing counted twice, nothing lost.

`agentlog yesterday` and `agentlog today` are the two commands somebody runs
back to back, and between them they should account for each thing that happened
exactly once.  The two windows meet at local midnight, and `_until_for_period`
says in as many words that the end it returns is *exclusive* — yesterday runs up
to midnight, today starts at it.

The counting did not agree with that sentence.  `_clip_counts` and
`_first_and_last_inside` both asked `start <= ts <= end`, inclusive at both
edges, so a record stamped exactly at local midnight fell inside both windows
and was counted in both days: three turns across the two commands were reported
as four.

Nothing in this machine's 81261 real timestamps lands on an exact local
midnight, so this was never going to show up in a digest anybody has read.  It
is worth fixing anyway, and worth a file of its own, because the property is one
a reader relies on without being told — days are supposed to add up — and
because the boundary is exactly where an off-by-one is invisible: both numbers
look plausible and neither is checkable against the other.

The rule is the one the docstring already stated.  A window's asked-for end is
exclusive: an event at that instant is the first thing in the next window, not
the last thing in this one.  A window's *start* is inclusive, which is what
makes the pair meet without a gap.
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

SID = "4ef1361b-07e4-4bc9-bb29-1783b761d677"


def _when(text):
    """A timestamp out of the json, however it was spelled on the way out."""
    return datetime.fromisoformat(text.replace(" ", "T", 1))


class Case(unittest.TestCase):
    """A session whose middle event sits on the stroke of midnight."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-partition-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.dir = os.path.join(self.home, ".claude", "projects", "-home-you-api")
        os.makedirs(self.dir)
        self.midnight = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0)
        self.records = []

    def turn(self, when):
        self.records.append({
            "type": "user", "uuid": "u%d" % len(self.records), "sessionId": SID,
            "timestamp": when.isoformat(), "cwd": "/home/you/api",
            "message": {"role": "user", "content": [
                {"type": "text", "text": "go"}]}})

    def tool(self, when, name, value):
        i = len(self.records)
        field = {"Bash": "command", "Write": "file_path"}[name]
        self.records.append({
            "type": "assistant", "uuid": "u%d" % i, "sessionId": SID,
            "timestamp": when.isoformat(), "cwd": "/home/you/api",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t%d" % i, "name": name,
                 "input": {field: value}}]}})

    def written(self):
        with open(os.path.join(self.dir, SID + ".jsonl"), "w") as fh:
            for r in self.records:
                fh.write(json.dumps(r) + "\n")

    def day(self, period):
        """The sessions agentlog reports for one named day."""
        self.written()
        p = subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home, period,
             "--json", "--sessions"],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100"))
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout or "[]")

    def counts(self, period, field="user_turns"):
        return sum(s[field] for s in self.day(period))


class TestTheStrokeOfMidnight(Case):

    def setUp(self):
        super().setUp()
        self.turn(self.midnight - timedelta(minutes=1))
        self.turn(self.midnight)
        self.turn(self.midnight + timedelta(minutes=1))

    def test_three_turns_are_not_reported_as_four(self):
        self.assertEqual(self.counts("yesterday") + self.counts("today"), 3)

    def test_the_stroke_belongs_to_the_day_it_begins(self):
        # Which day gets it is a choice, and this is the one the code already
        # says it makes: the end of a named period is exclusive, its start is
        # inclusive.  Written down here so the next person changing a window
        # edge finds out which way round it goes.
        self.assertEqual(self.counts("yesterday"), 1)
        self.assertEqual(self.counts("today"), 2)

    def test_the_earlier_day_does_not_claim_time_it_did_not_use(self):
        # The window a day reports is the time between the first and last thing
        # done inside it.  If yesterday still counts the midnight turn, it also
        # reports a minute of work that belonged to the next day.
        #
        # Parsed, not compared as text: `win_end` is `str(datetime)`, which
        # separates with a space where `isoformat()` uses a "T", and a space
        # sorts below a "T" — so the string form of this assertion passes
        # whatever the times are.  It did, on the unfixed code, which is the
        # only reason the bad comparison was caught.
        sessions = self.day("yesterday")
        self.assertEqual(len(sessions), 1, sessions)
        self.assertLess(_when(sessions[0]["win_end"]), self.midnight,
                        sessions[0])


class TestItIsNotOnlyTurns(Case):

    def setUp(self):
        super().setUp()
        self.turn(self.midnight - timedelta(minutes=1))
        self.tool(self.midnight, "Bash", "pytest -x")
        self.tool(self.midnight, "Write", "/home/you/api/app.py")
        self.turn(self.midnight + timedelta(minutes=1))

    def test_a_command_on_the_stroke_is_reported_once(self):
        seen = []
        for period in ("yesterday", "today"):
            for s in self.day(period):
                seen.extend(s["commands"])
        self.assertEqual(seen, ["pytest -x"])

    def test_a_write_on_the_stroke_is_reported_once(self):
        total = 0
        for period in ("yesterday", "today"):
            for s in self.day(period):
                total += sum(s["write_counts"].values())
        self.assertEqual(total, 1)


class TestWhatDidNotChange(Case):
    """The ordinary case, so the fix cannot be "count one less, always"."""

    def setUp(self):
        super().setUp()
        self.turn(self.midnight - timedelta(minutes=1))
        self.turn(self.midnight + timedelta(seconds=1))
        self.turn(self.midnight + timedelta(minutes=1))

    def test_nothing_is_lost_when_no_event_sits_on_the_edge(self):
        self.assertEqual(self.counts("yesterday"), 1)
        self.assertEqual(self.counts("today"), 2)

    def test_a_session_wholly_inside_one_day_keeps_its_totals(self):
        self.records = []
        for i in range(3):
            self.turn(self.midnight + timedelta(hours=1, minutes=i))
        self.assertEqual(self.counts("today"), 3)
        self.assertEqual(self.counts("yesterday"), 0)

    def test_a_last_event_exactly_at_midnight_is_still_reported(self):
        # The other half of the same edge, and the one a careless fix drops:
        # the session ends at the stroke and has nothing after it.  It belongs
        # to the later day, and it must belong to *a* day.
        self.records = []
        self.turn(self.midnight - timedelta(minutes=5))
        self.turn(self.midnight)
        self.assertEqual(self.counts("yesterday") + self.counts("today"), 2)
        self.assertEqual(self.counts("today"), 1)


if __name__ == "__main__":
    unittest.main()
