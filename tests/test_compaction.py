"""What it cost to keep going.

When a session runs out of room, Claude Code summarises what happened so far
and throws the rest away.  It writes one record when it does:
`type: "system"`, `subtype: "compact_boundary"`, with a `compactMetadata`
block saying how big the context was before, how much survived, and how long
the summarising took.

agentlog is a tool for the question "where did that session go", and on a long
one this is a large part of the answer.  On the developer's own logs: 313
compactions across 49 sessions, twelve hours of wall-clock spent doing them,
a median of 2m17s each, and a median of 13% of the context surviving.  One
session compacted 86 times.  None of that appears anywhere in the log a person
can read, so a session that spent a third of its life re-reading its own
summary looks exactly like one that was simply slow.

The number that has to be handled carefully is `cumulativeDroppedTokens`.  It
is a *running total* — on all 313 real records it equals the running sum of
`preTokens - postTokens`, not that one compaction's loss.  Adding those fields
up across a session counts the first compaction once for every compaction that
followed it, so a session with three of them reports roughly three times the
truth, in the direction that makes the tool look more informative.  The
per-compaction loss is `pre - post`; the session total is the last cumulative.
"""

import os
import shutil
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agentlog import render  # noqa: E402
from agentlog.parser import find_sessions  # noqa: E402
from tests.fixtures import claude_assistant, claude_user, make_claude_project  # noqa: E402

DAY = "2026-08-04"
SID = "sess-compact"


def _at(hour, minute=0):
    return f"{DAY}T{hour:02d}:{minute:02d}:00.000Z"


def boundary(timestamp, pre, post, cumulative, duration_ms=137000,
             trigger="auto", session_id=SID):
    """A compact_boundary record, shaped like the ones Claude Code writes."""
    return {
        "type": "system",
        "subtype": "compact_boundary",
        "sessionId": session_id,
        "timestamp": timestamp,
        "cwd": "/home/test/myproject",
        "version": "2.1.0",
        "uuid": f"compact-{timestamp}",
        "content": "Conversation compacted",
        "compactMetadata": {
            "trigger": trigger,
            "preTokens": pre,
            "postTokens": post,
            "cumulativeDroppedTokens": cumulative,
            "durationMs": duration_ms,
            "preservedSegment": {"headUuid": "h", "anchorUuid": "a",
                                 "tailUuid": "t"},
        },
    }


class CompactionCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agentlog_compact_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def sessions_from(self, records):
        make_claude_project(self.tmp, "proj", [records])
        sessions, _sources, _unusable = find_sessions(self.tmp)
        return sessions

    def one(self, records):
        sessions = self.sessions_from(records)
        self.assertEqual(len(sessions), 1, sessions)
        return sessions[0]


class TestTheCompactionIsRecorded(CompactionCase):

    def test_a_session_that_never_compacted_says_so_with_an_empty_list(self):
        # Not None, and not a missing key: every other view reads this the way
        # it reads files_read, and a key that is sometimes absent is a
        # KeyError waiting for the first quiet day.
        s = self.one([claude_user(SID, _at(9)), claude_assistant(SID, _at(9, 1))])
        self.assertEqual(s["compactions"], [])

    def test_one_compaction_is_kept_with_what_it_cost(self):
        s = self.one([
            claude_user(SID, _at(9)),
            boundary(_at(10), pre=363312, post=9661, cumulative=353651),
            claude_assistant(SID, _at(10, 5)),
        ])
        self.assertEqual(len(s["compactions"]), 1)
        c = s["compactions"][0]
        self.assertEqual(c["trigger"], "auto")
        self.assertEqual(c["pre"], 363312)
        self.assertEqual(c["post"], 9661)
        self.assertEqual(c["dropped"], 363312 - 9661)
        self.assertAlmostEqual(c["duration_s"], 137.0)

    def test_a_manual_compaction_is_marked_as_one(self):
        # `/compact` and running out of room are different events: one is a
        # person deciding, the other is the session hitting a wall.  A reader
        # counting walls should not be shown their own keystrokes.
        s = self.one([
            claude_user(SID, _at(9)),
            boundary(_at(10), 300000, 9000, 291000, trigger="manual"),
        ])
        self.assertEqual(s["compactions"][0]["trigger"], "manual")

    def test_they_come_back_in_the_order_they_happened(self):
        s = self.one([
            claude_user(SID, _at(9)),
            boundary(_at(10), 300000, 9000, 291000),
            boundary(_at(12), 310000, 8000, 593000),
            boundary(_at(14), 320000, 7000, 906000),
        ])
        self.assertEqual([c["pre"] for c in s["compactions"]],
                         [300000, 310000, 320000])


class TestTheRunningTotalIsNotSummed(CompactionCase):
    """`cumulativeDroppedTokens` is a running total, not this event's loss.

    Summing it across a session counts the first compaction once for every
    compaction after it.  Three compactions of 291k each would report 1.7M
    dropped instead of 873k — and it reads as a plausible number, because the
    only thing wrong with it is that it is too large.
    """

    def records(self):
        return [
            claude_user(SID, _at(9)),
            boundary(_at(10), 300000, 9000, 291000),
            boundary(_at(12), 300000, 9000, 582000),
            boundary(_at(14), 300000, 9000, 873000),
        ]

    def test_each_compaction_reports_only_its_own_loss(self):
        s = self.one(self.records())
        self.assertEqual([c["dropped"] for c in s["compactions"]],
                         [291000, 291000, 291000])

    def test_the_session_total_is_the_last_running_total(self):
        s = self.one(self.records())
        self.assertEqual(sum(c["dropped"] for c in s["compactions"]), 873000)

    def test_time_spent_compacting_adds_up_across_them(self):
        s = self.one(self.records())
        self.assertAlmostEqual(sum(c["duration_s"] for c in s["compactions"]),
                               411.0)


class TestABoundaryIsNotSomethingYouDid(CompactionCase):
    """The record is machine bookkeeping, not conversation."""

    def test_it_is_not_counted_as_a_turn(self):
        plain = self.one([claude_user(SID, _at(9)),
                          claude_assistant(SID, _at(9, 1))])
        with_compact = self.one([
            claude_user(SID, _at(9)),
            boundary(_at(10), 300000, 9000, 291000),
            claude_assistant(SID, _at(10, 1)),
        ])
        self.assertEqual(with_compact["user_turns"], plain["user_turns"])

    def test_it_is_not_counted_as_an_error(self):
        s = self.one([claude_user(SID, _at(9)),
                      boundary(_at(10), 300000, 9000, 291000)])
        self.assertEqual(s["errors"], 0)

    def test_it_is_not_counted_as_a_line_the_parser_could_not_read(self):
        s = self.one([claude_user(SID, _at(9)),
                      boundary(_at(10), 300000, 9000, 291000)])
        self.assertEqual(s["skipped_lines"], 0)


class TestAMalformedBoundaryIsIgnored(CompactionCase):
    """These records are read from a file the tool exists to audit."""

    def test_a_boundary_with_no_metadata_is_dropped_not_crashed_on(self):
        rec = boundary(_at(10), 300000, 9000, 291000)
        del rec["compactMetadata"]
        s = self.one([claude_user(SID, _at(9)), rec])
        self.assertEqual(s["compactions"], [])

    def test_token_counts_that_are_not_numbers_are_dropped(self):
        rec = boundary(_at(10), 300000, 9000, 291000)
        rec["compactMetadata"]["preTokens"] = "lots"
        s = self.one([claude_user(SID, _at(9)), rec])
        self.assertEqual(s["compactions"], [])

    def test_a_missing_duration_is_zero_not_a_crash(self):
        rec = boundary(_at(10), 300000, 9000, 291000)
        del rec["compactMetadata"]["durationMs"]
        s = self.one([claude_user(SID, _at(9)), rec])
        self.assertEqual(s["compactions"][0]["duration_s"], 0.0)

    def test_a_negative_duration_is_clamped_to_zero(self):
        # A clock that stepped backwards mid-compaction would otherwise
        # subtract from the session's total time spent compacting.
        rec = boundary(_at(10), 300000, 9000, 291000, duration_ms=-5000)
        s = self.one([claude_user(SID, _at(9)), rec])
        self.assertEqual(s["compactions"][0]["duration_s"], 0.0)

    def test_a_trigger_the_tool_has_never_seen_is_kept_as_written(self):
        # Guessing "auto" for an unknown trigger would report a wall the
        # session never hit.  Print what the log said.
        rec = boundary(_at(10), 300000, 9000, 291000, trigger="something-new")
        s = self.one([claude_user(SID, _at(9)), rec])
        self.assertEqual(s["compactions"][0]["trigger"], "something-new")


class TestItShowsUpWhereSomebodyWillSeeIt(CompactionCase):

    def test_show_reports_the_count_the_time_and_the_loss(self):
        s = self.one([
            claude_user(SID, _at(9)),
            boundary(_at(10), 300000, 9000, 291000),
            boundary(_at(12), 300000, 9000, 582000),
        ])
        out = render.render_show(s)
        line = [ln for ln in out.splitlines() if ln.startswith("context")]
        self.assertEqual(len(line), 1, out)
        self.assertIn("2", line[0])          # how many times
        self.assertIn("4m 34s", line[0])     # what it cost in wall-clock
        self.assertIn("582,000", line[0])    # what was thrown away

    def test_a_session_that_never_compacted_gets_no_context_line(self):
        # A row saying "0" is a row the reader has to read before deciding it
        # says nothing.
        s = self.one([claude_user(SID, _at(9)),
                      claude_assistant(SID, _at(9, 1))])
        out = render.render_show(s)
        self.assertNotIn("context", out)

    def test_manual_compactions_are_named_so_the_count_can_be_trusted(self):
        s = self.one([
            claude_user(SID, _at(9)),
            boundary(_at(10), 300000, 9000, 291000, trigger="manual"),
        ])
        line = [ln for ln in render.render_show(s).splitlines()
                if ln.startswith("context")][0]
        self.assertIn("manual", line)

    def test_json_carries_the_compactions_for_anything_downstream(self):
        s = self.one([
            claude_user(SID, _at(9)),
            boundary(_at(10), 300000, 9000, 291000),
        ])
        import json as _json
        data = _json.loads(render.render_json([s]))
        self.assertEqual(len(data[0]["compactions"]), 1)
        self.assertEqual(data[0]["compactions"][0]["dropped"], 291000)

    def test_the_json_timestamp_is_a_string_not_a_datetime(self):
        # render_json has to serialise it, and a datetime in there is a
        # TypeError at the moment somebody pipes the output into jq.
        s = self.one([
            claude_user(SID, _at(9)),
            boundary(_at(10), 300000, 9000, 291000),
        ])
        import json as _json
        data = _json.loads(render.render_json([s]))
        self.assertIsInstance(data[0]["compactions"][0]["at"], str)


if __name__ == "__main__":
    unittest.main()
