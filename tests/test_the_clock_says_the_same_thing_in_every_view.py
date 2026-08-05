"""One session, five views, one answer about its time.

Every view that prints how long a session ran worked the answer out for itself,
in three or four lines that looked the same at a glance.  They were not, and
they drifted in the two places a reader could see:

A session from 23:40 to 00:15 came out of the text digest as ``23:40 –
2026-07-17 00:15`` and out of the HTML digest as ``23:40 – 00:15``, which reads
as thirty-five minutes of running backwards.  The text view had the rule and a
comment explaining it; the HTML view was written later and had neither, because
the rule was not in a place it could be got from.

And ``show`` — the view you open to find out the truth about one session —
reported the time the session was *open* under the bare label ``duration``,
while every other view reported the time it spent *working*.  On a session left
open over lunch that is the difference between forty minutes and six hours, and
the detailed view was the one giving the larger, wronger number.

Nothing in either case was a bug in a formatter.  Both were rules held by a
caller, and a rule held by a caller is a rule the next caller does not have.
So `clock` holds them, and these are the promises that made moving them worth
doing — written against the rendered output, because a reader of these tools
reads the output and not the module.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentlog import clock                                    # noqa: E402
from agentlog.html import render_html                         # noqa: E402
from agentlog.render import (                                 # noqa: E402
    render_list, render_markdown, render_show, render_text,
)


# How far the zone these fixtures are *stored* in sits from the zone they are
# *read* in.  Any non-zero amount does; seven hours is one that keeps the
# resulting offset legal from Baker Island to Kiritimati.
LOGGED_OFFSET = timedelta(hours=-7)


def logged(year, month, day, hour, minute):
    """A reader's wall-clock time, stored the way the parser stores it.

    The arguments name an instant in the reader's own timezone, because the
    rule under test is about *local* days: a session crosses midnight where the
    person reading about it lives, not in UTC.  Every assertion below is
    therefore written in the reader's wall clock, and holds on any box.

    What gets stored is that same instant expressed somewhere else.  It has to
    be.  `transcript.parse_time` reads every record as UTC — the stamps end in
    ``Z``, and one without an offset is read as UTC too — so a session arrives
    at these views in a zone that is not the reader's, and converting it is
    most of what this module does.  A fixture built in the reader's own zone
    is a fixture in which none of that conversion can be seen: every
    ``.astimezone()`` is a no-op on it, and deleting one changes nothing.
    Three mutants proved exactly that by surviving.

    Pinning the stored zone outright would not fix it either — pinned to UTC,
    the fixture is a no-op again on a box that runs in UTC.  Offsetting it from
    whatever local is keeps the two sides a known distance apart everywhere.
    """
    here = datetime(year, month, day, hour, minute).astimezone()
    return here.astimezone(timezone(here.utcoffset() + LOGGED_OFFSET))


def a_session(**overrides):
    """A session dict shaped the way the parser produces one."""
    start = overrides.pop("start", logged(2026, 7, 16, 10, 0))
    base = {
        "id": "abc12345-0000-0000-0000-000000000000",
        "source": "claude",
        "project": "/home/test/myproject",
        "project_name": "myproject",
        "start": start,
        "end": start + timedelta(minutes=90) if start else None,
        "duration_s": 5400.0,
        "models": ["claude-test"],
        "user_turns": 5,
        "files_read": [],
        "files_written": [],
        "commands": [],
        "errors": 0,
        "tokens_in": None,
        "tokens_out": None,
        "ai_title": None,
        "version": "2.1.0",
        "skipped_lines": 0,
    }
    base.update(overrides)
    return base


def html_of(s):
    return render_html([s], ["claude"], "today")


class TestWhenItRanReadsForwards(unittest.TestCase):
    """A range whose far end is earlier than its near end needs its date."""

    OVERNIGHT = dict(start=logged(2026, 7, 16, 23, 40),
                     end=logged(2026, 7, 17, 0, 15))

    def test_a_session_that_crosses_midnight_dates_the_far_end(self):
        self.assertEqual(clock.when(a_session(**self.OVERNIGHT)),
                         "2026-07-16 23:40 – 2026-07-17 00:15")

    def test_a_session_inside_one_day_leaves_the_far_end_bare(self):
        # The date beside it already said which day this is; repeating it is
        # eleven characters saying nothing.
        self.assertEqual(clock.when(a_session()), "2026-07-16 10:00 – 11:30")

    def test_the_html_digest_dates_it_too(self):
        # The defect.  This view was written after the text view and did not
        # inherit its rule, because the rule was inside the text view.
        self.assertIn("2026-07-16 23:40 – 2026-07-17 00:15",
                      html_of(a_session(**self.OVERNIGHT)))

    def test_the_text_digest_dates_it(self):
        self.assertIn("2026-07-16 23:40 – 2026-07-17 00:15",
                      render_text([a_session(**self.OVERNIGHT)]))

    def test_the_markdown_document_dates_it(self):
        self.assertIn("2026-07-16 23:40 – 2026-07-17 00:15",
                      render_markdown([a_session(**self.OVERNIGHT)]))

    def test_a_session_with_no_end_is_just_its_start(self):
        self.assertEqual(clock.when(a_session(end=None)), "2026-07-16 10:00")

    def test_a_session_whose_ends_are_the_same_moment_is_said_once(self):
        start = logged(2026, 7, 16, 10, 0)
        self.assertEqual(clock.when(a_session(start=start, end=start)),
                         "2026-07-16 10:00")

    def test_a_session_with_no_start_says_so(self):
        # Rather than an empty gap where a time goes, which reads as a layout
        # fault instead of as a missing value.
        self.assertEqual(clock.when(a_session(start=None, end=None)), "?")


class TestHowLongMeansWorkingTime(unittest.TestCase):
    """Open and busy are different questions, and views used to mix them."""

    # Open for six hours, busy for forty minutes of them.
    IDLE = dict(start=logged(2026, 7, 16, 9, 0),
                end=logged(2026, 7, 16, 15, 0),
                duration_s=21600.0,
                active_spans=[(logged(2026, 7, 16, 9, 0),
                               logged(2026, 7, 16, 9, 40))])

    def test_the_number_is_the_time_it_worked(self):
        self.assertTrue(clock.how_long(a_session(**self.IDLE)).startswith("40m 00s"))

    def test_and_it_says_how_long_it_was_open(self):
        # Without this the range printed next to it looks like a contradiction:
        # nine to three, forty minutes.
        self.assertEqual(clock.how_long(a_session(**self.IDLE)),
                         "40m 00s active, 6h 00m open")

    def test_show_reports_the_working_time_like_everything_else(self):
        # The defect.  `show` printed 6h 00m under "duration" while `list`
        # printed 40m 00s under DUR for the same session.
        row = [line for line in render_show(a_session(**self.IDLE)).splitlines()
               if line.startswith("duration")]
        self.assertEqual(row, ["duration 40m 00s active, 6h 00m open"])

    def test_a_window_says_it_is_only_part_of_the_session(self):
        # A different thing to be told: we looked at part of it on purpose,
        # rather than looked at all of it and found it quiet.
        s = a_session(duration_s=21600.0, window_s=2400.0, active_spans=[])
        self.assertEqual(clock.how_long(s), "40m 00s in window, 6h 00m total")

    def test_a_session_that_was_busy_throughout_says_one_number(self):
        s = a_session(active_spans=[(logged(2026, 7, 16, 10, 0),
                                     logged(2026, 7, 16, 11, 30))])
        self.assertEqual(clock.how_long(s), "1h 30m")

    def test_a_minute_of_slack_is_not_worth_a_second_number(self):
        # A session that merely rounds oddly should not sprout a number saying
        # the same thing twice.
        start = logged(2026, 7, 16, 10, 0)
        near = a_session(duration_s=3659.0, start=start,
                         active_spans=[(start, start + timedelta(seconds=3600))])
        self.assertEqual(clock.how_long(near), "1h 00m")
        far = a_session(duration_s=3661.0, start=start,
                        active_spans=[(start, start + timedelta(seconds=3600))])
        self.assertIn("open", clock.how_long(far))


class TestTheTableTakesTheBareNumber(unittest.TestCase):
    """`list` is the one view that opts out, and it has a reason to."""

    def test_the_dur_column_holds_a_number_and_not_a_phrase(self):
        # Eight characters wide.  A phrase in it would push every column right
        # of it out of line, which is the whole point of a table.
        row = render_list([a_session(**TestHowLongMeansWorkingTime.IDLE)]).splitlines()[-1]
        self.assertIn("40m 00s", row)
        self.assertNotIn("open", row)

    def test_it_is_still_the_working_time(self):
        # Bare is not the same as wrong: the column means what DUR means
        # everywhere else, it just does not have room to explain itself.
        self.assertEqual(
            clock.how_long(a_session(**TestHowLongMeansWorkingTime.IDLE),
                           qualified=False), "40m 00s")


class TestEveryViewAgrees(unittest.TestCase):
    """The property the module exists for, stated as one test.

    Each of these used to derive the answer itself, so each was free to drift
    from the others — and two of them had.  Rendering one session five ways and
    reading the number back out of each is the cheapest thing that notices.
    """

    def test_one_session_gets_one_duration_everywhere(self):
        s = a_session(**TestHowLongMeansWorkingTime.IDLE)
        for name, text in (("text", render_text([s])),
                           ("html", html_of(s)),
                           ("markdown", render_markdown([s])),
                           ("list", render_list([s])),
                           ("show", render_show(s))):
            self.assertIn("40m 00s", text,
                          "the {} view disagrees about how long it ran".format(name))

    def test_the_views_with_room_all_explain_the_number(self):
        s = a_session(**TestHowLongMeansWorkingTime.IDLE)
        for name, text in (("text", render_text([s])),
                           ("html", html_of(s)),
                           ("markdown", render_markdown([s])),
                           ("show", render_show(s))):
            self.assertIn("6h 00m open", text,
                          "the {} view gives the number without the reason".format(name))


class TestTheRenderersNoLongerDeriveIt(unittest.TestCase):
    """The move, stated as what the renderers can no longer get wrong."""

    def test_neither_renderer_works_the_day_out_for_itself(self):
        # The rule that drifted was `end.date() == start.date()`, written out
        # by hand in one renderer and not the other.  There is one copy now.
        for module in ("render", "html"):
            path = os.path.join(os.path.dirname(__file__), "..", "agentlog",
                                module + ".py")
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
            self.assertNotIn("astimezone().date() ==", body,
                             "{}.py compares the days itself again".format(module))

    def test_the_html_view_does_not_reach_for_the_time_helpers(self):
        from agentlog import html
        for name in ("_fmt_datetime", "_fmt_time", "_fmt_duration",
                     "_window_duration", "_idled"):
            self.assertFalse(
                hasattr(html, name),
                "html reaches past the clock for {!r}".format(name))

    def test_the_qualifier_is_written_once(self):
        # Two spellings of "it idled" in two files is how they came apart the
        # first time.
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        found = []
        for module in ("clock", "render", "html"):
            with open(os.path.join(here, "agentlog", module + ".py"),
                      encoding="utf-8") as fh:
                if re.search(r'\bactive, \{', fh.read()):
                    found.append(module)
        self.assertEqual(found, ["clock"], found)


if __name__ == "__main__":
    unittest.main()
