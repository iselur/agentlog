"""A day boundary must be midnight on *that* day, not midnight today.

Every window this tool offers is a day boundary: `today`, `yesterday`, `week`,
`since 2026-01-15`.  Each one is built by taking a date and putting midnight on
it in local time.

The local offset was captured once, at import, from `datetime.now()` — a single
fixed number, today's offset.  Applying today's offset to a date in a different
part of the year gets it wrong by exactly the DST shift.  Asked in July for a
day in January, in a zone that observes DST, the window opened an hour early
and closed an hour early: sessions from 23:00 the night before were reported as
having happened on the day you asked about, and the last hour of that day was
not there at all.

That is the quiet kind of wrong.  `agentlog since 2026-01-15` printing a
session that happened on the 14th, or leaving out the one at 23:30, does not
look like an error — it looks like the log.

The fix is to let the platform resolve each date against its own rules:
`datetime(y, m, d).astimezone()` asks what the offset was *on that date*.

These tests run under a fixed TZ so they mean the same thing on any machine.
"""

import importlib
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _InZone(unittest.TestCase):
    """Run the module with TZ pinned, and with `now` inside a chosen season."""

    zone = "Europe/Berlin"

    def setUp(self):
        self._old_tz = os.environ.get("TZ")
        os.environ["TZ"] = self.zone
        time.tzset()
        self.addCleanup(self._restore)
        # Re-import so the module picks up the zone we just set.
        from agentlog import cli
        self.cli = importlib.reload(cli)

    def _restore(self):
        if self._old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._old_tz
        time.tzset()
        from agentlog import cli
        importlib.reload(cli)

    def local_midnight(self, y, m, d):
        """What midnight on that date actually was, per the platform."""
        return datetime(y, m, d).astimezone()


class TestAnIsoDateIsMidnightOnThatDate(_InZone):

    def test_a_winter_date(self):
        got = self.cli._parse_since("2026-01-15")
        self.assertEqual(got, self.local_midnight(2026, 1, 15),
                         "window opened at the wrong moment")

    def test_a_summer_date(self):
        got = self.cli._parse_since("2026-07-15")
        self.assertEqual(got, self.local_midnight(2026, 7, 15))

    def test_the_day_daylight_saving_starts(self):
        # 2026-03-29 in Berlin: 02:00 does not exist.  Midnight does.
        got = self.cli._parse_since("2026-03-29")
        self.assertEqual(got, self.local_midnight(2026, 3, 29))

    def test_the_day_daylight_saving_ends(self):
        # 2026-10-25 in Berlin: 02:00 happens twice.
        got = self.cli._parse_since("2026-10-25")
        self.assertEqual(got, self.local_midnight(2026, 10, 25))

    def test_both_halves_of_the_year_agree_with_utc(self):
        # The real check: no date may land on the wrong side of its own
        # midnight, whichever season the tool happens to be run in.
        for iso in ("2026-01-01", "2026-02-14", "2026-03-28", "2026-03-29",
                    "2026-06-30", "2026-10-24", "2026-10-25", "2026-12-31"):
            y, m, d = (int(p) for p in iso.split("-"))
            with self.subTest(date=iso):
                self.assertEqual(self.cli._parse_since(iso),
                                 self.local_midnight(y, m, d))


class TestNamedPeriods(_InZone):

    def test_today_starts_at_midnight_today(self):
        today = self.cli._today_local()
        self.assertEqual(
            self.cli._since_for_period("today"),
            self.local_midnight(today.year, today.month, today.day))

    def test_yesterday_is_a_whole_day_long(self):
        start = self.cli._since_for_period("yesterday")
        end = self.cli._until_for_period("yesterday")
        self.assertEqual(end - start, timedelta(days=1),
                         "yesterday was not 24 hours long")

    def test_a_week_covers_seven_whole_days(self):
        start = self.cli._since_for_period("week")
        end = self.cli._until_for_period("week")
        self.assertEqual(end - start, timedelta(days=7),
                         "the week window was the wrong length")

    def test_yesterday_ends_where_today_starts(self):
        self.assertEqual(self.cli._until_for_period("yesterday"),
                         self.cli._since_for_period("today"),
                         "an hour fell between the two windows, or overlapped")


class TestAZoneWithADifferentShift(_InZone):
    """Not every zone shifts by an hour in the same month as Berlin."""

    zone = "America/Santiago"

    def test_a_date_in_the_other_season(self):
        for iso in ("2026-01-15", "2026-07-15", "2026-09-06", "2026-04-05"):
            y, m, d = (int(p) for p in iso.split("-"))
            with self.subTest(date=iso):
                self.assertEqual(self.cli._parse_since(iso),
                                 self.local_midnight(y, m, d))


class TestUTCIsUnaffected(_InZone):
    """The regression guard: a zone with no DST must not move at all."""

    zone = "UTC"

    def test_dates_are_plain_utc_midnight(self):
        got = self.cli._parse_since("2026-01-15")
        self.assertEqual(got, datetime(2026, 1, 15, tzinfo=timezone.utc))

    def test_offsets_still_work(self):
        got = self.cli._parse_since("3d")
        self.assertIsNotNone(got)
        self.assertLess(got, datetime.now(timezone.utc))

    def test_nonsense_is_still_rejected(self):
        for bad in ("", "tomorrow", "0d", "-3d", "2026-13-01", "3x"):
            with self.subTest(value=bad):
                self.assertIsNone(self.cli._parse_since(bad))


if __name__ == "__main__":
    unittest.main()
