"""Asking what happened on one particular day.

`today` and `yesterday` are the only two days you could ask about.  For anything
older there was `since DATE`, which is open-ended: `since 2026-07-31` answers
"the four days from Friday to now", never "Friday".  So the two questions a
digest exists to answer — *what did I do on Tuesday* and *how did Tuesday
compare with Wednesday* — could not be typed.

`on DATE` closes one whole local day.  It takes the same argument `since` does,
with one difference that falls out of the words: `since 0d` is an empty window
(since now, until now) and is refused, while `on 0d` is today and is not.  An
offset in hours does not name a day and is refused with that reason.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog import window, parser  # noqa: E402

SID = "3c3c3c3c-0000-4000-8000-000000000003"


class Case(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-onday-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.dir = os.path.join(self.home, ".claude", "projects", "-home-you-api")
        os.makedirs(self.dir)
        self.midnight = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0)
        self.records = []

    def busy(self, when, count=1, label="step"):
        for n in range(count):
            i = len(self.records)
            self.records.append({
                "type": "assistant", "uuid": "u%d" % i, "sessionId": SID,
                "cwd": "/home/you/api",
                "timestamp": (when + timedelta(minutes=n)).isoformat(),
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t%d" % i, "name": "Bash",
                     "input": {"command": "%s %d" % (label, i)}}]}})

    def write(self):
        with open(os.path.join(self.dir, SID + ".jsonl"), "w") as fh:
            for r in self.records:
                fh.write(json.dumps(r) + "\n")

    def run_cli(self, *args, expect=0):
        self.write()
        p = subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home, *args],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100"))
        self.assertEqual(p.returncode, expect, p.stdout + p.stderr)
        return p.stdout + p.stderr

    def json_of(self, *args):
        return json.loads(self.run_cli(*args, "--json"))


class TestOneDayInTheMiddle(Case):
    """A session running all week, asked about one day of it."""

    def setUp(self):
        super().setUp()
        # Three commands on the day before yesterday, seven yesterday, one today.
        self.busy(self.midnight - timedelta(days=2, hours=-10), count=3,
                  label="older")
        self.busy(self.midnight - timedelta(days=1, hours=-10), count=7,
                  label="mid")
        self.busy(self.midnight + timedelta(hours=10), count=1, label="new")

    def commands_on(self, when):
        doc = self.json_of("on", when)
        return sum(len(s.get("commands") or []) for s in doc)

    def test_a_past_day_answers_for_that_day_alone(self):
        two_ago = (self.midnight - timedelta(days=2)).date().isoformat()
        self.assertEqual(self.commands_on(two_ago), 3)

    def test_the_day_after_it_answers_for_itself(self):
        one_ago = (self.midnight - timedelta(days=1)).date().isoformat()
        self.assertEqual(self.commands_on(one_ago), 7)

    def test_a_named_day_and_yesterday_agree(self):
        one_ago = (self.midnight - timedelta(days=1)).date().isoformat()
        named = self.json_of("on", one_ago)
        yday = self.json_of("yesterday")
        self.assertEqual(
            [len(s.get("commands") or []) for s in named],
            [len(s.get("commands") or []) for s in yday])

    def test_todays_date_and_today_agree(self):
        got = self.json_of("on", self.midnight.date().isoformat())
        today = self.json_of("today")
        self.assertEqual(
            [len(s.get("commands") or []) for s in got],
            [len(s.get("commands") or []) for s in today])

    def test_the_named_days_add_up_to_the_week(self):
        days = sum(self.commands_on(
            (self.midnight - timedelta(days=n)).date().isoformat())
            for n in range(7))
        week = sum(len(s.get("commands") or [])
                   for s in self.json_of("week"))
        self.assertEqual(days, week)

    def test_a_day_it_did_nothing_reports_nothing(self):
        three_ago = (self.midnight - timedelta(days=3)).date().isoformat()
        self.assertEqual(self.commands_on(three_ago), 0)

    def test_the_period_is_named_in_the_output(self):
        two_ago = (self.midnight - timedelta(days=2)).date().isoformat()
        self.assertIn(two_ago, self.run_cli("on", two_ago))


class TestTheOffsetForm(Case):
    """`on 2d` is the day before yesterday, the same way `since 2d` counts."""

    def setUp(self):
        super().setUp()
        self.busy(self.midnight - timedelta(days=2, hours=-10), count=3)

    def test_an_offset_names_the_same_day_as_the_date(self):
        two_ago = (self.midnight - timedelta(days=2)).date().isoformat()
        by_offset = self.json_of("on", "2d")
        by_date = self.json_of("on", two_ago)
        self.assertEqual([s["id"] for s in by_offset], [s["id"] for s in by_date])
        self.assertEqual(
            sum(len(s.get("commands") or []) for s in by_offset), 3)

    def test_zero_days_ago_is_today_even_though_since_refuses_it(self):
        # `since 0d` is a window from now until now.  `on 0d` is a day.
        self.assertIsNone(window._parse_since("0d"))
        got = self.json_of("on", "0d")
        today = self.json_of("today")
        self.assertEqual([s["id"] for s in got], [s["id"] for s in today])

    def test_hours_do_not_name_a_day(self):
        out = self.run_cli("on", "12h", expect=2)
        self.assertIn("day", out.lower())

    def test_weeks_do_not_name_a_day(self):
        self.run_cli("on", "2w", expect=2)

    def test_a_negative_offset_is_refused(self):
        self.run_cli("on", "-3d", expect=2)


class TestSayingItWrong(Case):

    def setUp(self):
        super().setUp()
        self.busy(self.midnight + timedelta(hours=10), count=1)

    def test_on_without_a_day_says_so(self):
        out = self.run_cli("on", expect=2)
        self.assertIn("'on' requires", out)
        self.assertIn("on 2026-", out)

    def test_nonsense_is_refused_by_showing_what_would_work(self):
        out = self.run_cli("on", "tuesday", expect=2)
        self.assertIn("does not name a day", out)
        self.assertIn("2026-07-31", out)
        self.assertIn("3d", out)

    def test_a_length_is_refused_by_pointing_at_the_command_that_takes_one(self):
        # `12h` is not wrong, it is the wrong command — say which one is right.
        out = self.run_cli("on", "12h", expect=2)
        self.assertIn("agentlog since 12h", out)
        self.assertIn("agentlog since 2w", self.run_cli("on", "2w", expect=2))

    def test_a_word_is_not_told_it_is_a_length(self):
        # The pointer at `since` is for the person who typed a duration.  Saying
        # it to someone who typed 'tuesday' answers a question they didn't ask.
        out = self.run_cli("on", "tuesday", expect=2)
        self.assertNotIn("agentlog since", out)

    def test_a_stray_second_word_is_still_a_typo(self):
        out = self.run_cli("on", "2026-07-31", "extra", expect=2)
        self.assertIn("unrecognized", out.lower() + out)

    def test_a_day_in_the_future_is_simply_empty(self):
        out = self.run_cli("on", (self.midnight + timedelta(days=400))
                           .date().isoformat())
        self.assertNotIn("Traceback", out)

    def test_it_is_offered_in_the_help(self):
        out = self.run_cli("--help")
        self.assertIn("on DAY", out)

    def test_an_unknown_command_offers_it(self):
        out = self.run_cli("bogus", expect=2)
        self.assertIn("on DAY", out)

    def test_every_view_accepts_it(self):
        day = self.midnight.date().isoformat()
        for flags in (["--sessions"], ["--md"], ["--json"]):
            self.run_cli("on", day, *flags)


class TestParsingOnItsOwn(unittest.TestCase):
    """The day parser, away from the CLI."""

    def test_an_iso_date_gives_that_whole_day(self):
        start, end = window._parse_day("2026-07-31")
        self.assertEqual(start.date(), date(2026, 7, 31))
        self.assertEqual(end.date(), date(2026, 8, 1))
        self.assertEqual((end - start), timedelta(days=1))

    def test_the_end_is_the_next_day_however_long_that_day_is(self):
        # Measured in days, not in hours: the day the clocks change is still a
        # day, and it is not twenty-four hours long.
        for value in ("2026-01-01", "2026-12-31", "0d", "1d", "9d",
                      "2026-03-29", "2026-10-25"):
            start, end = window._parse_day(value)
            self.assertEqual(end.date() - start.date(), timedelta(days=1), value)
            self.assertEqual((end.hour, end.minute), (0, 0), value)

    def test_it_starts_at_local_midnight(self):
        start, _end = window._parse_day("2026-07-31")
        self.assertEqual((start.hour, start.minute, start.second), (0, 0, 0))

    def test_what_it_refuses(self):
        for value in ("12h", "2w", "-1d", "", "tuesday", "2026-13-01", "3"):
            self.assertIsNone(window._parse_day(value), value)


if __name__ == "__main__":
    unittest.main()
