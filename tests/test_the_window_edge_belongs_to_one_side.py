"""The instant on a window's edge belongs to exactly one of the two windows.

`cli._inside` carries the rule and its history: "Both were inclusive, so an
event at exactly local midnight was the last thing yesterday and the first
thing today, and three turns across the two commands were reported as four."
`tests/test_day_partition.py` holds it to that.

`parser.active_spans` has its own copy of that rule, written out again inline,
and nothing held it to anything.  A mutation sweep flipped the comparison, then
flipped the default that selects it, and the suite stayed green on both — so
the two copies were free to drift apart, which is the failure mode a duplicated
rule actually has.  When they disagree, `agentlog on` clips the counts by one
rule and the working time by the other, and the digest contradicts itself about
a day nobody can go back and re-measure.

The zero-width case is here for a different reason.  A session with no
timestamped events keeps its whole span as one stretch — the documented
fallback, because we cannot see inside it.  Clip that session to an instant and
the honest answer is an instant of work, not the fallback: `render` treats an
empty span list as "nothing worked it out" and reports the session's whole
lifetime instead, which is exactly the fourteen-times over-count `active_spans`
was written to stop.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.cli import _inside  # noqa: E402
from agentlog.parser import _empty_session, active_spans  # noqa: E402

MIDNIGHT = datetime(2026, 8, 4, 0, 0, tzinfo=timezone.utc)
NOON = MIDNIGHT + timedelta(hours=12)
NEXT = MIDNIGHT + timedelta(days=1)


def session_with(*stamps):
    s = _empty_session("edge", "Codex")
    s["events"] = [(ts, "cmd", "work") for ts in stamps]
    s["start"] = stamps[0]
    s["end"] = stamps[-1]
    return s


def blank_session(start, end):
    """A session the parser could place but could not see inside."""
    s = _empty_session("blank", "Codex")
    s["start"] = start
    s["end"] = end
    return s


class TestTheTwoCopiesOfTheRuleAgree(unittest.TestCase):
    """`active_spans` and `_inside` decide the same edge the same way."""

    def test_a_closed_end_takes_the_event_on_it(self):
        s = session_with(NOON, NEXT)
        spans = active_spans(s, MIDNIGHT, NEXT)
        self.assertEqual(spans[-1][1], NEXT,
                         "an event exactly on a closed end was dropped")
        self.assertTrue(_inside(NEXT, MIDNIGHT, NEXT, False))

    def test_an_open_end_leaves_the_event_on_it_for_the_next_window(self):
        s = session_with(NOON, NEXT)
        spans = active_spans(s, MIDNIGHT, NEXT, True)
        self.assertEqual(spans[-1][1], NOON,
                         "an event exactly on an open end was counted twice — "
                         "once here and once at the start of tomorrow")
        self.assertFalse(_inside(NEXT, MIDNIGHT, NEXT, True))

    def test_the_default_is_the_closed_end(self):
        # The two copies also have to agree about which rule applies when
        # nobody said.  `_inside` takes it as a required argument; here it is
        # a default, and a default is the easiest thing in the file to flip
        # without anybody noticing.
        s = session_with(NOON, NEXT)
        self.assertEqual(active_spans(s, MIDNIGHT, NEXT),
                         active_spans(s, MIDNIGHT, NEXT, False))
        self.assertNotEqual(active_spans(s, MIDNIGHT, NEXT),
                            active_spans(s, MIDNIGHT, NEXT, True))

    def test_the_start_is_inclusive_either_way(self):
        # Stated in `_inside`'s docstring as unconditional, and it is the
        # half of the rule that keeps a day from losing its first turn.
        s = session_with(MIDNIGHT, NOON)
        self.assertEqual(active_spans(s, MIDNIGHT, NEXT)[0][0], MIDNIGHT)
        self.assertEqual(active_spans(s, MIDNIGHT, NEXT, True)[0][0], MIDNIGHT)
        self.assertTrue(_inside(MIDNIGHT, MIDNIGHT, NEXT, True))

    def test_one_event_is_not_in_both_of_two_adjoining_days(self):
        # The bug in one sentence.  `_until_for_period` hands back an open
        # end for the day being asked about, so the instant of midnight is
        # yesterday's last event and not today's first.
        # Both windows are asked-for edges, so both ends are open — and the
        # start is inclusive either way, which is what puts the instant in
        # exactly one of them.
        s = session_with(NEXT)
        yesterday = active_spans(s, MIDNIGHT, NEXT, True)
        today = active_spans(s, NEXT, NEXT + timedelta(days=1), True)
        self.assertEqual(len(yesterday) + len(today), 1,
                         "the midnight event landed in both days, or neither")


class TestASessionClippedToAnInstant(unittest.TestCase):
    """The fallback for a session we cannot see inside, clipped to nothing."""

    def test_an_instant_of_an_unreadable_session_is_an_instant_of_work(self):
        blank = blank_session(MIDNIGHT, NEXT)
        spans = active_spans(blank, NOON, NOON)
        self.assertEqual(
            spans, [(NOON, NOON)],
            "a zero-width clip came back empty, which render reads as "
            "'nobody worked the spans out' and answers with the session's "
            "whole lifetime instead")

    def test_a_window_that_ended_before_the_session_began_is_still_nothing(self):
        # The guard this shares a line with, and the reason it cannot simply
        # be dropped: a backwards span is not a span.
        blank = blank_session(MIDNIGHT, NEXT)
        self.assertEqual(active_spans(blank, NEXT, MIDNIGHT), [])

    def test_a_session_that_can_be_seen_into_is_not_given_the_fallback(self):
        # Vacuity guard.  The fallback is only for a session with no
        # timestamped events at all; one with events that simply miss the
        # window slept through it, and the answer is nothing.
        s = session_with(NOON)
        self.assertEqual(active_spans(s, NEXT, NEXT + timedelta(days=1)), [])


if __name__ == "__main__":
    unittest.main()
