"""A session left open overnight billed the whole morning as work.

Leave an agent session open, come back, run one command at 09:16, ask
agentlog how the day has gone:

    9h 16m active across 1 project · today, Tue 4 Aug

      proj        9h 16m   1 command

One command.  Nine hours and sixteen minutes.  The two halves of that line
disagree, and 09:16 is exactly midnight-to-now — because the window clipped the
session to the *edge of the day* rather than to the first thing that happened
inside it:

    clipped_start = max(start, since)

`since` is local midnight.  A session that began yesterday therefore started its
day at 00:00, and every hour spent asleep counted as active.

The counts were already right — `_clip_counts` recounts events inside the
window, which is why it said one command — so only the duration lied, and it
lied in the headline, which is the first thing anyone reads.

The honest bound is the first and last event actually inside the window.  The
window edge is where we started looking, not when anything happened.

Sessions parsed without per-event timestamps keep the old behaviour: with
nothing to tighten to there is nothing better to say, and that is the same
fallback `_clip_counts` already takes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.window import _filter_sessions
from tests.fixtures import a_now_that_keeps


def _local(dt):
    return dt.astimezone()


def _midnight_today():
    return _local(datetime.now()).replace(
        hour=0, minute=0, second=0, microsecond=0)


def _session(events):
    """A session dict shaped the way the parser produces one."""
    stamps = [ts for ts, _k, _v in events]
    return {
        "id": "s1", "project": "proj", "source": "claude",
        "start": min(stamps), "end": max(stamps),
        "events": list(events),
        "files_read": [], "files_written": [], "commands": [],
        "write_counts": {}, "failed_cmds": [], "user_turns": 0, "errors": 0,
    }


def _cmd(when, what="echo hi"):
    return (when, "cmd", what)


class TestTheDurationMatchesWhatHappened(unittest.TestCase):

    def window(self, session):
        got = _filter_sessions([session], since=_midnight_today())
        self.assertEqual(len(got), 1, "the session dropped out of the window")
        s = got[0]
        return (s["win_end"] - s["win_start"]).total_seconds()

    def test_one_command_today_is_not_nine_hours(self):
        midnight = _midnight_today()
        s = _session([_cmd(midnight - timedelta(hours=1)),      # yesterday
                      _cmd(midnight + timedelta(hours=9, minutes=16))])
        self.assertEqual(self.window(s), 0.0,
                         "one command reported as most of a working day")

    def test_two_commands_measure_the_gap_between_them(self):
        midnight = _midnight_today()
        s = _session([_cmd(midnight - timedelta(hours=1)),
                      _cmd(midnight + timedelta(hours=9)),
                      _cmd(midnight + timedelta(hours=9, minutes=30))])
        self.assertEqual(self.window(s), 30 * 60)

    def test_the_window_starts_at_the_first_event_not_the_edge(self):
        midnight = _midnight_today()
        first_today = midnight + timedelta(hours=9)
        s = _session([_cmd(midnight - timedelta(hours=2)), _cmd(first_today)])
        got = _filter_sessions([s], since=midnight)[0]
        self.assertEqual(got["win_start"], first_today)

    def test_window_seconds_agrees(self):
        # The same half hour is reported separately as `window_s` — for a
        # session that worked through it.  Steadily, because a silence longer
        # than the idle gap is no longer counted; see tests/test_idle_gaps.py.
        midnight = _midnight_today()
        events = [_cmd(midnight - timedelta(hours=1))]
        events += [_cmd(midnight + timedelta(hours=9, minutes=m))
                   for m in range(0, 31, 2)]
        got = _filter_sessions([_session(events)], since=midnight)[0]
        self.assertEqual(got["window_s"], 30 * 60)

    def test_window_seconds_is_the_working_part_of_that_span(self):
        # The edges still sit half an hour apart — the test above says so — but
        # two commands with nothing between them are not half an hour of work,
        # and `window_s` is what gets reported as time spent.
        midnight = _midnight_today()
        s = _session([_cmd(midnight - timedelta(hours=1)),
                      _cmd(midnight + timedelta(hours=9)),
                      _cmd(midnight + timedelta(hours=9, minutes=30))])
        got = _filter_sessions([s], since=midnight)[0]
        self.assertEqual((got["win_end"] - got["win_start"]).total_seconds(),
                         30 * 60)
        self.assertEqual(got["window_s"], 0.0)

    def test_the_trailing_edge_too(self):
        # The same mistake at the other end: an explicit --until must not
        # stretch the session forward to the edge it was cut at.
        midnight = _midnight_today()
        last = midnight + timedelta(hours=2)
        s = _session([_cmd(midnight + timedelta(hours=1)), _cmd(last),
                      _cmd(midnight + timedelta(hours=20))])
        got = _filter_sessions([s], since=midnight,
                               until=midnight + timedelta(hours=10))[0]
        self.assertEqual(got["win_end"], last)


class TestNothingElseMoves(unittest.TestCase):
    """The regression guard: only clipped sessions change, and only their edges."""

    def test_a_session_wholly_inside_the_window_is_untouched(self):
        midnight = _midnight_today()
        a = midnight + timedelta(hours=9)
        b = midnight + timedelta(hours=10)
        got = _filter_sessions([_session([_cmd(a), _cmd(b)])], since=midnight)[0]
        self.assertEqual(got["win_start"], a)
        self.assertEqual(got["win_end"], b)
        self.assertNotIn("window_s", got, "an unclipped session was clipped")

    def test_no_window_at_all_is_untouched(self):
        a = _midnight_today() - timedelta(days=3)
        b = a + timedelta(hours=1)
        got = _filter_sessions([_session([_cmd(a), _cmd(b)])])[0]
        self.assertEqual(got["win_start"], a)
        self.assertEqual(got["win_end"], b)

    def test_a_session_with_no_recorded_events_keeps_the_old_bounds(self):
        # Nothing to tighten to, so nothing better to say than the edge.
        midnight = _midnight_today()
        s = _session([_cmd(midnight - timedelta(hours=1)),
                      _cmd(midnight + timedelta(hours=9))])
        s["events"] = []
        got = _filter_sessions([s], since=midnight)[0]
        self.assertEqual(got["win_start"], midnight)

    def test_events_with_no_timestamp_are_ignored_not_crashed_on(self):
        midnight = _midnight_today()
        s = _session([_cmd(midnight - timedelta(hours=1)),
                      _cmd(midnight + timedelta(hours=9))])
        s["events"].append((None, "cmd", "unstamped"))
        got = _filter_sessions([s], since=midnight)[0]
        self.assertEqual(got["win_start"], midnight + timedelta(hours=9))

    def test_a_session_that_ended_before_the_window_still_drops_out(self):
        midnight = _midnight_today()
        s = _session([_cmd(midnight - timedelta(hours=5)),
                      _cmd(midnight - timedelta(hours=4))])
        self.assertEqual(_filter_sessions([s], since=midnight), [])


class TestTheReportItself(unittest.TestCase):
    """End to end, because the headline is what people actually read."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="agentlog_overnight_")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def _write(self, offsets_minutes, must_reach_back=0):
        """Write one session's worth of commands, that many minutes back each.

        `must_reach_back` says how far back the *test* needs to still be today;
        offsets beyond it are meant to land in yesterday and are left there.
        See fixtures.a_now_that_keeps.
        """
        import json
        folder = os.path.join(self.home, ".claude", "projects", "-tmp-proj")
        os.makedirs(folder, exist_ok=True)
        now = a_now_that_keeps(must_reach_back)
        path = os.path.join(folder, "4ef1361b-07e4-4bc9-bb29-1783b761d677.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for i, mins in enumerate(offsets_minutes):
                fh.write(json.dumps({
                    "type": "assistant",
                    "timestamp": (now - timedelta(minutes=mins)).isoformat(),
                    "message": {"role": "assistant", "content": [
                        {"type": "tool_use", "id": "t{}".format(i),
                         "name": "Bash",
                         "input": {"command": "echo {}".format(i)}}]},
                }) + "\n")

    def _report(self):
        p = subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home],
            cwd=_ROOT, capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))
        return p.stdout + p.stderr

    def test_one_command_today_does_not_headline_as_hours(self):
        # The first event is far enough back to be yesterday whatever time the
        # suite runs at; the second is this minute.
        self._write([60 * 30, 1], must_reach_back=1)
        out = self._report()
        self.assertIn("1 command", out)
        self.assertNotIn("h ", out.split("\n")[0],
                         "the headline still reports hours for one command:\n"
                         + out)

    def test_an_ordinary_day_still_reports_its_span(self):
        # Half an hour of steady work, so that the idle-gap rule has nothing to
        # take off it and the headline is the plain span.  The rule itself has
        # its own file, tests/test_idle_gaps.py.
        self._write(list(range(40, 9, -2)), must_reach_back=40)
        out = self._report()
        self.assertIn("30m", out, out)


if __name__ == "__main__":
    unittest.main()
