"""Fixtures that write "forty minutes ago" and mean "earlier today".

Those are the same thing for twenty-three hours and twenty minutes a day.  For
the other forty minutes the records land in yesterday, `agentlog today`
correctly reports an empty day, and the suite that passed all evening fails
until 00:40.  It happened: fourteen tests across three files went red at 00:03
and came back on their own, which is the worst way for a suite to be wrong.

The clock cannot be pinned here — these fixtures are read by subprocess runs of
the real command, which reads the real one — so `fixtures.a_now_that_keeps`
moves the fixture's own clock forward off midnight instead.  That helper is the
whole fix, so it is what gets tested, with a `now` handed in.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from tests.fixtures import a_now_that_keeps, midnight_today

# The files whose fixtures write day-anchored stamps.  Each one asks the real
# command for `today` (or the default report, which is today), so each one has
# to reach back through the helper.
THE_DAY_ANCHORED_ONES = (
    "test_broken_pipe.py",
    "test_c_locale.py",
    "test_cli.py",
    "test_overnight_sessions.py",
)


def _at(hour, minute):
    """A local `now` at that time on an ordinary day."""
    return datetime(2026, 8, 5, hour, minute).astimezone()


class TestMidnightToday(unittest.TestCase):

    def test_it_is_the_start_of_the_day_that_now_is_in(self):
        self.assertEqual(midnight_today(_at(14, 30)), _at(0, 0))

    def test_midnight_is_its_own_midnight(self):
        self.assertEqual(midnight_today(_at(0, 0)), _at(0, 0))

    def test_it_keeps_the_offset_it_was_given(self):
        # Local midnight, not UTC midnight: `today` is a local day.
        self.assertEqual(midnight_today(_at(3, 0)).utcoffset(),
                         _at(3, 0).utcoffset())


class TestANowThatKeeps(unittest.TestCase):

    def test_the_ordinary_hour_gets_the_real_clock_back(self):
        now = _at(14, 30)
        self.assertEqual(a_now_that_keeps(40, now), now)

    def test_the_first_minutes_of_a_day_are_moved_forward(self):
        self.assertEqual(a_now_that_keeps(40, _at(0, 3)), _at(0, 40))

    def test_what_it_hands_back_always_has_the_history_behind_it(self):
        # The property the callers actually depend on, at every minute of the
        # window where it matters and a few outside it.
        for minute in range(0, 90):
            for reach in (1, 5, 30, 40, 60):
                now = _at(0, 0) + timedelta(minutes=minute)
                moved = a_now_that_keeps(reach, now)
                self.assertGreaterEqual(
                    moved - timedelta(minutes=reach), midnight_today(now),
                    "{}m of history at 00:{:02d} still lands in yesterday"
                    .format(reach, minute))

    def test_it_never_moves_the_clock_backwards(self):
        for minute in (0, 1, 39, 40, 41, 600):
            now = _at(0, 0) + timedelta(minutes=minute)
            self.assertGreaterEqual(a_now_that_keeps(40, now), now)

    def test_asking_for_nothing_changes_nothing(self):
        self.assertEqual(a_now_that_keeps(0, _at(0, 0)), _at(0, 0))

    def test_reaching_past_the_start_of_the_day_is_not_clamped_into_tomorrow(self):
        # A fixture that deliberately writes into yesterday -- the overnight
        # tests do -- asks for the reach it needs, not the reach it writes.
        moved = a_now_that_keeps(1, _at(0, 0))
        self.assertLess(moved, midnight_today(_at(0, 0)) + timedelta(days=1))


class TestTheFixturesStillGoThroughIt(unittest.TestCase):
    """A cheap guard: the helper is easy to stop calling and hard to miss.

    Not a lint over the whole suite -- most `datetime.now` in here is a
    comparison bound, and a rule that flagged those would be an allowlist with
    a test attached.  These four files are the ones that write a stamp and then
    ask for a day.
    """

    def test_each_one_imports_the_helper(self):
        for name in THE_DAY_ANCHORED_ONES:
            with self.subTest(name):
                tree = ast.parse(open(os.path.join(_ROOT, "tests", name),
                                      encoding="utf-8").read())
                imported = {alias.name
                            for node in ast.walk(tree)
                            if isinstance(node, ast.ImportFrom)
                            and (node.module or "").endswith("fixtures")
                            for alias in node.names}
                self.assertIn("a_now_that_keeps", imported,
                              "{} writes day-anchored stamps off the raw clock"
                              .format(name))


if __name__ == "__main__":
    unittest.main()
