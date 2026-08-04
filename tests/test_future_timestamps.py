"""A log written by a clock that runs ahead is still a log.

agentlog reads timestamps that somebody else's machine wrote.  Two clocks are
involved and they do not agree: an NTP step backwards, a VM or container
resumed from a snapshot, a home directory synced from a laptop a few minutes
fast — any of those puts events in the file that are dated after the reader's
`now`.

The window used to end at `now` whether or not anybody asked for an end, so
those events fell outside it.  The session was still listed, so nothing looked
broken; it just reported `0s active` and one turn, because the window had
collapsed to the single instant the session started.  A day of work read as an
empty one, and the digest gave no hint that anything had been clipped.

`min(end, now)` is a no-op whenever the data is in the past, so it never did
anything except on skew.  What replaces it: `today` ends at midnight tonight —
which is what the word means — and `since` has no end at all.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentlog.cli import main  # noqa: E402
from agentlog.window import (  # noqa: E402
    _local_midnight,
    _filter_sessions,
    _today_local,
    _until_for_period,
)
from tests.fixtures import claude_assistant, claude_user, tool_bash  # noqa: E402


def _session_ahead_of_the_clock(skew_minutes: int = 2):
    """A five-minute session with three turns, dated ahead of `now`."""
    start = datetime.now(timezone.utc) + timedelta(minutes=skew_minutes)
    end = start + timedelta(minutes=5)
    events = []
    for i in range(3):
        at = start + timedelta(minutes=i)
        events.append((at, "turn", ""))
        events.append((at, "cmd", "echo {}".format(i)))
        events.append((at, "read", "file{}.py".format(i)))
    return {
        "id": "skewed",
        "project_name": "proj",
        "project": "/tmp/proj",
        "start": start,
        "end": end,
        "user_turns": 3,
        "commands": ["echo 0", "echo 1", "echo 2"],
        "files_read": ["file0.py", "file1.py", "file2.py"],
        "files_written": [],
        "errors": 0,
        "events": events,
    }


class TestAFutureDatedSession(unittest.TestCase):
    """The filter, at the level where the clipping happens."""

    def test_it_is_not_clipped_to_a_single_instant(self):
        s = _filter_sessions([_session_ahead_of_the_clock()])[0]
        self.assertEqual(s["win_end"], s["end"],
                         "the window ended at `now` even though nobody asked "
                         "it to end")

    def test_the_turns_survive(self):
        s = _filter_sessions([_session_ahead_of_the_clock()])[0]
        self.assertEqual(s["user_turns"], 3)

    def test_the_commands_survive(self):
        s = _filter_sessions([_session_ahead_of_the_clock()])[0]
        self.assertEqual(s["commands"], ["echo 0", "echo 1", "echo 2"])

    def test_it_is_not_reported_as_zero_seconds(self):
        s = _filter_sessions([_session_ahead_of_the_clock()])[0]
        self.assertEqual(s.get("window_s", 300.0), 300.0)

    def test_still_true_when_a_since_edge_was_asked_for(self):
        # `since` gives the window a beginning, not an end.
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        s = _filter_sessions([_session_ahead_of_the_clock()], since=since)[0]
        self.assertEqual(s["user_turns"], 3)
        self.assertEqual(s["win_end"], s["end"])


class TestTheWindowsThatDoHaveAnEnd(unittest.TestCase):
    """The fix must not cost the clipping that was the point of the feature."""

    def test_today_ends_at_midnight_tonight(self):
        until = _until_for_period("today")
        self.assertIsNotNone(until, "`today` has an end: tonight")
        tomorrow = _today_local() + timedelta(days=1)
        self.assertEqual(until, _local_midnight(tomorrow))

    def test_yesterday_still_ends_this_morning(self):
        today = _today_local()
        self.assertEqual(_until_for_period("yesterday"),
                         _local_midnight(today))

    def test_since_has_no_end(self):
        self.assertIsNone(_until_for_period("since"))

    def test_a_session_running_past_the_end_is_still_clipped(self):
        # The real feature: a two-week session must not put all its edits into
        # every day's digest.
        start = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
        s = {
            "id": "long", "start": start,
            "end": datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
            "events": [
                (datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc), "cmd", "in"),
                (datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc), "cmd", "out"),
            ],
        }
        got = _filter_sessions(
            [s],
            since=datetime(2026, 7, 21, tzinfo=timezone.utc),
            until=datetime(2026, 7, 22, tzinfo=timezone.utc))[0]
        self.assertEqual(got["commands"], ["in"])
        # One command inside this day, at one instant, so no time passed
        # between the first thing that happened and the last.  This asserted
        # the window's own width until the overnight fix; see the note in
        # `test_cli.test_window_seconds_is_the_overlap_not_the_lifetime`.
        self.assertEqual(got["window_s"], 0.0)
        self.assertLess(got["window_s"], 4 * 24 * 3600, "the lifetime came back")

    def test_a_session_wholly_after_the_end_is_still_dropped(self):
        s = {"id": "later",
             "start": datetime(2026, 7, 25, tzinfo=timezone.utc),
             "end": datetime(2026, 7, 25, 1, tzinfo=timezone.utc)}
        self.assertEqual(
            _filter_sessions(
                [s], until=datetime(2026, 7, 22, tzinfo=timezone.utc)),
            [])


class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agentlog_skew_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, records):
        proj = os.path.join(self.tmp, ".claude", "projects", "-tmp-proj")
        os.makedirs(proj, exist_ok=True)
        with open(os.path.join(proj, "s.jsonl"), "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

    def _run(self, argv):
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
        try:
            code = main(argv)
            return code, sys.stdout.getvalue(), sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    def _skewed_log(self, turns=6, skew_minutes=2):
        sid = "skew-0000-0000-0000-000000000001"
        base = datetime.now(timezone.utc) + timedelta(minutes=skew_minutes)
        recs = []
        for i in range(turns):
            at = (base + timedelta(seconds=30 * i)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            recs.append(claude_user(sid, at, cwd="/tmp/proj",
                                    text="turn {}".format(i)))
            recs.append(claude_assistant(
                sid, at, msg_id="msg_{}".format(i),
                tools=[tool_bash("echo {}".format(i), tool_id="t{}".format(i))]))
        return recs

    def test_a_skewed_day_does_not_read_as_an_empty_one(self):
        self._write(self._skewed_log())
        code, out, err = self._run(["--home", self.tmp, "since", "1h"])
        self.assertEqual(code, 0, out + err)
        # 6 turns 30s apart: the digest leads with the real span, not `0s`.
        self.assertFalse(out.startswith("0s active"), out)
        self.assertIn("2m 30s active", out, out)
        self.assertIn("6 commands", out, out)

    def test_the_sessions_view_agrees_with_the_file(self):
        self._write(self._skewed_log())
        code, out, err = self._run(
            ["--home", self.tmp, "since", "1h", "--sessions"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("6 turns", out, out)
        self.assertNotIn("0s in window", out, out)

    def test_today_counts_it_too(self):
        # Skipped in the last minutes of the day, where a two-minute skew
        # genuinely lands on tomorrow and clipping it is correct.
        _now = datetime.now().astimezone()
        if _now.hour == 23 and _now.minute > 50:
            self.skipTest("within ten minutes of midnight")
        self._write(self._skewed_log())
        code, out, err = self._run(["--home", self.tmp, "today"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("6 commands", out, out)

    def test_next_week_is_not_today(self):
        # The other side of it: giving `today` no end at all would make a log
        # dated next Tuesday part of today's digest.  Small skew belongs in
        # today; a session three days out does not.
        self._write(self._skewed_log(turns=2, skew_minutes=3 * 24 * 60))
        code, out, err = self._run(["--home", self.tmp, "today"])
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("commands", out, out)

    def test_a_normal_past_dated_day_is_unchanged(self):
        sid = "past-0000-0000-0000-000000000001"
        base = datetime.now(timezone.utc) - timedelta(minutes=30)
        recs = []
        for i in range(4):
            at = (base + timedelta(seconds=30 * i)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            recs.append(claude_user(sid, at, cwd="/tmp/proj"))
            recs.append(claude_assistant(
                sid, at, msg_id="m{}".format(i),
                tools=[tool_bash("ls {}".format(i), tool_id="t{}".format(i))]))
        self._write(recs)
        code, out, err = self._run(["--home", self.tmp, "since", "1h"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("4 commands", out, out)


if __name__ == "__main__":
    unittest.main()
