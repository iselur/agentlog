"""What `Window` promises, asked of `Window` and nothing else.

Until this file, every question about a window had to be asked through
something else.  `agentlog week` meant "call `_since_for_period`, then
`_until_for_period`, then `_filter_sessions` with both" — three private names
out of a dozen, and knowing which three went with which command.  So the tests
either reached for the private names one at a time, which checks the pieces and
not the answer, or ran the whole command line and read its printed output,
which checks the answer through a page of formatting.  Neither asks the
question a caller actually asks.

The question a caller asks is: *this command and this argument name which two
moments, and what did each session do between them.*  That is `Window.parse`
and `window.clip`, and this file is those two.

Two things it can check that nothing could before:

  * **the moment is an argument.**  `now` is passed in, so "what does `week`
    mean" has one answer instead of a different one every time the suite runs,
    and the day-boundary cases can be asked *about* a boundary rather than by
    waiting for one.
  * **what a person is told when they get it wrong.**  Four different wordings,
    each printed to somebody who has already typed something that did not work.
    They were previously reachable only by running the command line and reading
    stderr, so they were checked loosely or not at all.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentlog.window import Unparseable, Window, _local_midnight  # noqa: E402

# A Wednesday afternoon.  Fixed, because every assertion below about what a
# period *means* is only stable if the moment it is asked at is.
NOW = datetime(2026, 7, 15, 14, 30, tzinfo=timezone.utc)


def day(y, m, d):
    return _local_midnight(datetime(y, m, d).date())


class TestAPeriodNamesTwoMoments(unittest.TestCase):
    """today / yesterday / week: no argument, and both edges implied."""

    def test_today_runs_from_this_midnight_to_the_next(self):
        w = Window.parse("today", now=NOW)
        local_today = NOW.astimezone().date()
        self.assertEqual(w.since, _local_midnight(local_today))
        self.assertEqual(w.until,
                         _local_midnight(local_today + timedelta(days=1)))

    def test_yesterday_ends_where_today_begins(self):
        # The two commands partition the two days, which is the whole reason
        # the end is exclusive.  Said here as one sentence about two windows,
        # rather than inferred from two separate calls to a private helper.
        yesterday = Window.parse("yesterday", now=NOW)
        today = Window.parse("today", now=NOW)
        self.assertEqual(yesterday.until, today.since)

    def test_a_week_is_seven_days_ending_tonight(self):
        w = Window.parse("week", now=NOW)
        self.assertEqual((w.until - w.since).days, 7)
        self.assertEqual(w.until, Window.parse("today", now=NOW).until)

    def test_the_label_is_the_command(self):
        for period in ("today", "yesterday", "week"):
            self.assertEqual(Window.parse(period, now=NOW).label, period)

    def test_an_argument_is_not_needed(self):
        # Whether an argument is *allowed* is the command line's business; what
        # matters here is that leaving it out is not an error.
        self.assertEqual(Window.parse("today", now=NOW),
                         Window.parse("today", None, NOW))


class TestTheMomentIsAnArgument(unittest.TestCase):
    """The property that makes every assertion above possible."""

    def test_a_different_moment_gives_a_different_window(self):
        first = Window.parse("today", now=NOW)
        later = Window.parse("today", now=NOW + timedelta(days=3))
        self.assertNotEqual(first.since, later.since)
        self.assertEqual((later.since - first.since).days, 3)

    def test_the_same_moment_gives_the_same_window(self):
        self.assertEqual(Window.parse("week", now=NOW),
                         Window.parse("week", now=NOW))

    def test_a_minute_before_midnight_and_a_minute_after_are_different_days(self):
        # The case that cannot be written at all without an injected moment:
        # you would have to run the suite at 23:59.
        midnight = _local_midnight(NOW.astimezone().date() + timedelta(days=1))
        before = Window.parse("today", now=midnight - timedelta(minutes=1))
        after = Window.parse("today", now=midnight + timedelta(minutes=1))
        self.assertEqual(before.until, after.since)

    def test_omitting_the_moment_means_now(self):
        w = Window.parse("today")
        self.assertLessEqual(w.since, datetime.now(timezone.utc))
        self.assertGreater(w.until, datetime.now(timezone.utc))


class TestSinceHasNoEnd(unittest.TestCase):

    def test_an_offset_counts_back_from_the_moment_given(self):
        w = Window.parse("since", "3d", NOW)
        self.assertEqual(w.since, NOW - timedelta(days=3))

    def test_an_iso_date_is_midnight_on_that_date(self):
        w = Window.parse("since", "2026-01-15", NOW)
        self.assertEqual(w.since, day(2026, 1, 15))

    def test_there_is_no_until(self):
        # `since 3d` genuinely means "and everything after", so the window has
        # an open end rather than one quietly set to now.
        self.assertIsNone(Window.parse("since", "3d", NOW).until)

    def test_the_label_repeats_what_was_typed(self):
        self.assertEqual(Window.parse("since", "3d", NOW).label, "since 3d")


class TestOnIsOneWholeDay(unittest.TestCase):

    def test_it_runs_from_that_midnight_to_the_next(self):
        w = Window.parse("on", "2026-07-31", NOW)
        self.assertEqual(w.since, day(2026, 7, 31))
        self.assertEqual(w.until, day(2026, 8, 1))

    def test_a_day_offset_is_counted_from_the_moment_given(self):
        w = Window.parse("on", "3d", NOW)
        self.assertEqual(w.since,
                         _local_midnight(NOW.astimezone().date()
                                         - timedelta(days=3)))

    def test_zero_days_ago_is_today(self):
        # Where `on` and `since` part company on purpose: `since 0d` is an
        # empty window and refused, `on 0d` is today and is not.
        self.assertEqual(Window.parse("on", "0d", NOW).since,
                         Window.parse("today", now=NOW).since)

    def test_the_label_names_the_day_rather_than_the_argument(self):
        # `on 3d` should print the date it resolved to; a heading that says
        # "3d" is unreadable a week later.
        self.assertEqual(Window.parse("on", "2026-07-31", NOW).label,
                         "on 2026-07-31")
        self.assertRegex(Window.parse("on", "3d", NOW).label,
                         r"^on \d{4}-\d{2}-\d{2}$")

    def test_a_day_the_clocks_change_is_still_a_whole_day(self):
        # 25 hours in Berlin, 24 in UTC — whichever this machine is in, the
        # window is the day, not a fixed number of hours.
        w = Window.parse("on", "2026-10-25", NOW)
        self.assertEqual(w.until, day(2026, 10, 26))


class TestWhatAPersonIsToldWhenItIsWrong(unittest.TestCase):
    """Four wordings, each printed to somebody who already got it wrong."""

    def message(self, *argv):
        with self.assertRaises(Unparseable) as caught:
            Window.parse(*argv)
        return str(caught.exception)

    def test_since_with_nothing_after_it_says_what_to_put_there(self):
        text = self.message("since", None, NOW)
        self.assertIn("requires a date or offset", text)
        self.assertIn("3d", text)

    def test_an_argument_it_cannot_read_is_quoted_back(self):
        text = self.message("since", "tuesday", NOW)
        self.assertIn("tuesday", text, "the person cannot see which word failed")
        self.assertIn("2026-07-01", text, "no example of a form that works")

    def test_on_with_nothing_after_it_says_what_to_put_there(self):
        text = self.message("on", None, NOW)
        self.assertIn("requires a date or a day offset", text)

    def test_a_length_given_to_on_is_told_which_command_takes_it(self):
        # `on 12h` is not a typo — it is a valid argument handed to the wrong
        # command, and the useful answer names the right one.
        text = self.message("on", "12h", NOW)
        self.assertIn("not a day", text)
        self.assertIn("agentlog since 12h", text,
                      "the answer says it is wrong without saying what is right")

    def test_a_real_typo_is_not_told_to_try_since(self):
        # The hint is only for somebody who typed a length.  Offering `agentlog
        # since tuesday` sends them to a second error.
        self.assertNotIn("since", self.message("on", "tuesday", NOW))

    def test_an_unknown_command_lists_the_ones_that_exist(self):
        text = self.message("yesteday", None, NOW)
        self.assertIn("yesteday", text)
        for command in ("today", "yesterday", "week", "since", "on",
                        "show", "list"):
            self.assertIn(command, text, command)

    def test_show_and_list_are_not_windows(self):
        # They are commands, and they reach this module by mistake if at all.
        # Answering with a window would be worse than refusing.
        for command in ("show", "list"):
            with self.assertRaises(Unparseable):
                Window.parse(command, "abc", NOW)


def _session(start, end, events=()):
    return {"id": "s", "start": start, "end": end,
            "events": [(ts, "cmd", "echo") for ts in events],
            "commands": ["echo"] * len(events)}


class TestClipping(unittest.TestCase):
    """`clip` is the second half of the interface, and the only other half."""

    def setUp(self):
        self.window = Window.parse("on", "2026-07-15", NOW)
        self.midnight = self.window.since
        self.noon = self.midnight + timedelta(hours=12)

    def test_a_session_outside_the_window_is_dropped(self):
        earlier = self.midnight - timedelta(days=2)
        self.assertEqual(
            self.window.clip([_session(earlier, earlier + timedelta(hours=1))]),
            [])

    def test_a_session_inside_the_window_is_kept(self):
        kept = self.window.clip(
            [_session(self.noon, self.noon + timedelta(hours=1), [self.noon])])
        self.assertEqual(len(kept), 1)

    def test_a_session_that_began_before_the_window_still_counts(self):
        # The reason overlap is the test and not the start timestamp: a session
        # left running overnight belongs to today as well as yesterday.
        overnight = _session(self.midnight - timedelta(hours=3),
                             self.noon, [self.noon])
        self.assertEqual(len(self.window.clip([overnight])), 1)

    def test_the_session_handed_in_is_not_modified(self):
        # `list` and `show` read the same parse, so a clip that wrote through
        # would change what an unrelated command prints.
        original = _session(self.midnight - timedelta(hours=3), self.noon,
                            [self.noon])
        before = dict(original)
        self.window.clip([original])
        self.assertEqual(original, before)

    def test_an_open_ended_window_keeps_everything_after_it(self):
        w = Window.parse("since", "2026-01-01", NOW)
        far_future = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(
            len(w.clip([_session(far_future,
                                 far_future + timedelta(hours=1))])), 1)

    def test_clipping_nothing_is_not_an_error(self):
        self.assertEqual(self.window.clip([]), [])


if __name__ == "__main__":
    unittest.main()
