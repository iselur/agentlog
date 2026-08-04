"""Folding parallel workers into one session, when the workers disagree.

`_merge_sessions` exists because Codex fans a turn out to worker agents, every
worker writes its own file, and all of them carry the same session_id.  The
existing tests for it — `test_parallel_workers` — are about arithmetic: that
the counts add and the lists union, so that a merge does not trade an
under-count for the over-count that cannot be spotted afterwards.

What they never varied is the workers *differing in shape*.  Every fixture
there is built the same way, so every dict has every key and every timestamp
parsed.  A mutation sweep took nine separate `or` defaults out of this function
— the ones that stand in for a missing key or an unparsed timestamp — and the
suite noticed none of them.

That is a realistic gap, not a theoretical one.  The workers are separate files
written concurrently by a process that may be killed between them, and the
merge is the first place two of them are held next to each other.  One worker
that recorded no tokens, one whose compaction timestamp did not parse, one that
never learned the project name: each is one file, and the merge decides what
the whole session says.

Ordering is the other half.  The lists are sorted oldest-first so the merged
session reads in the order the work happened rather than the order the
filesystem handed the files over — a report whose order depends on directory
listing is a report that changes when you copy it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.parser import (  # noqa: E402
    _empty_session, _merge_sessions, find_sessions)
from tests.fixtures import claude_assistant, claude_user  # noqa: E402

SID = "019fc384-1111-2222-3333-444455556666"
T0 = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)


def worker(minutes_in=None, minutes_out=None, **fields):
    """One worker's file, as the parser would hand it over."""
    s = _empty_session(SID, "Codex")
    if minutes_in is not None:
        s["start"] = T0 + timedelta(minutes=minutes_in)
        s["end"] = T0 + timedelta(minutes=minutes_out
                                  if minutes_out is not None else minutes_in)
    s.update(fields)
    return s


class TestTheMergeReadsInTheOrderTheWorkHappened(unittest.TestCase):

    def test_the_commands_come_out_oldest_first(self):
        # Handed over newest-first, which is what a directory listing does
        # about as often as not.
        merged = _merge_sessions([
            worker(30, 40, commands=["third"]),
            worker(0, 10, commands=["first"]),
            worker(15, 20, commands=["second"]),
        ])
        self.assertEqual(merged["commands"], ["first", "second", "third"])

    def test_a_worker_with_no_timestamps_sorts_to_the_front(self):
        # It cannot be placed, and the front is where an unplaceable thing
        # goes — but the merge has to place it *somewhere* rather than
        # comparing None against a datetime and raising halfway through.
        merged = _merge_sessions([
            worker(10, 20, commands=["stamped"]),
            worker(commands=["unstamped"]),
        ])
        self.assertEqual(merged["commands"], ["unstamped", "stamped"])

    def test_two_workers_starting_together_are_ordered_by_when_they_ended(self):
        # The tie-break, which is the second half of the sort key and would go
        # unnoticed without a pair that starts at the same instant.
        merged = _merge_sessions([
            worker(0, 40, commands=["long"]),
            worker(0, 5, commands=["short"]),
        ])
        self.assertEqual(merged["commands"], ["short", "long"])


class TestAWorkerMissingAFieldAltogether(unittest.TestCase):
    """Keys the merge reads with `.get`, because they may not be there."""

    def test_token_events_survive_a_worker_that_has_none(self):
        a = worker(0, 10)
        a["token_events"] = [(T0, 100, 50)]
        b = worker(20, 30)
        del b["token_events"]           # a file written before the field existed
        merged = _merge_sessions([a, b])
        self.assertEqual(merged["token_events"], [(T0, 100, 50)],
                         "the surviving worker's token events were dropped")

    def test_compactions_survive_a_worker_that_has_none(self):
        a = worker(0, 10)
        a["compactions"] = [{"at": T0, "dropped": 4000}]
        b = worker(20, 30)
        del b["compactions"]
        merged = _merge_sessions([a, b])
        self.assertEqual(len(merged["compactions"]), 1,
                         "the surviving worker's compaction was dropped")

    def test_two_workers_that_both_compacted_are_two_compactions(self):
        # Concatenated, not unioned — the function says so, and each one
        # really cost its own time.  Also the vacuity guard for the test
        # above: a merge that kept no compactions at all would pass a check
        # that only counted one.
        a = worker(0, 10, compactions=[{"at": T0, "dropped": 4000}])
        b = worker(20, 30,
                   compactions=[{"at": T0 + timedelta(minutes=25),
                                 "dropped": 9000}])
        merged = _merge_sessions([b, a])
        self.assertEqual([c["dropped"] for c in merged["compactions"]],
                         [4000, 9000])


class TestATimestampThatDidNotParse(unittest.TestCase):
    """A record still counts when its `at` came out None."""

    def test_a_compaction_with_no_timestamp_sorts_to_the_front(self):
        a = worker(0, 10, compactions=[{"at": T0, "dropped": 1}])
        b = worker(20, 30, compactions=[{"at": None, "dropped": 2}])
        merged = _merge_sessions([a, b])
        self.assertEqual([c["dropped"] for c in merged["compactions"]], [2, 1],
                         "an unparsed compaction timestamp was not handled")

    def test_a_token_event_with_no_timestamp_sorts_to_the_front(self):
        a = worker(0, 10)
        a["token_events"] = [(T0, 100, 50)]
        b = worker(20, 30)
        b["token_events"] = [(None, 7, 7)]
        merged = _merge_sessions([a, b])
        self.assertEqual([e[1] for e in merged["token_events"]], [7, 100])


class TestTheFirstWorkerToKnowSomethingIsTheOneBelieved(unittest.TestCase):
    """project, project_name, version, ai_title — filled in, never overwritten."""

    def test_an_empty_field_is_filled_in_by_a_later_worker(self):
        a = worker(0, 10)                      # never learned the project
        b = worker(20, 30, project_name="api", version="0.1.0")
        merged = _merge_sessions([a, b])
        self.assertEqual(merged["project_name"], "api")
        self.assertEqual(merged["version"], "0.1.0")

    def test_a_field_already_known_is_not_overwritten(self):
        # The workers are one session, so they should agree — and when they
        # do not, the earliest one is the one that was there when the session
        # started.  Letting the last file read win makes the answer depend on
        # sort order, which is how this drifts silently.
        a = worker(0, 10, project_name="api", version="0.1.0")
        b = worker(20, 30, project_name="not-api", version="9.9.9")
        merged = _merge_sessions([b, a])
        self.assertEqual(merged["project_name"], "api")
        self.assertEqual(merged["version"], "0.1.0")


class TestTheMergedSpan(unittest.TestCase):

    def test_a_session_the_merge_cannot_place_has_no_duration(self):
        # `end - start` on a None is a TypeError, and this is a plain digest
        # reading files somebody else wrote — it does not get to crash on one.
        merged = _merge_sessions([worker(commands=["a"]),
                                  worker(commands=["b"])])
        self.assertIsNone(merged["start"])
        self.assertIsNone(merged["end"])
        self.assertIsNone(merged["duration_s"])

    def test_the_span_covers_every_worker(self):
        # Vacuity guard for the test above: a duration that was always None
        # would pass it.
        merged = _merge_sessions([worker(30, 40), worker(0, 10)])
        self.assertEqual(merged["start"], T0)
        self.assertEqual(merged["end"], T0 + timedelta(minutes=40))
        self.assertEqual(merged["duration_s"], 40 * 60)

    def test_a_worker_with_a_start_and_no_end_still_has_no_duration(self):
        # The test above hands the merge two workers with *neither*
        # timestamp, and that is the one shape where the guard's two halves
        # cannot be told apart: with both operands missing, `start and end`
        # and `start or end` agree, so a sweep that swapped them left the
        # suite green.  One timestamp present and the other missing is the
        # shape that separates them — `or` takes the subtraction branch and
        # `end - start` raises TypeError on the None.
        half = worker()
        half["start"] = T0
        merged = _merge_sessions([half, worker(commands=["a"])])
        self.assertEqual(merged["start"], T0)
        self.assertIsNone(merged["end"])
        self.assertIsNone(merged["duration_s"])

    def test_a_worker_with_an_end_and_no_start_still_has_no_duration(self):
        # And the same the other way round.  The two ends are gathered by
        # separate comprehensions, each filtering on its own field, so the
        # merge can arrive at one without the other from either side.
        half = worker()
        half["end"] = T0 + timedelta(minutes=5)
        merged = _merge_sessions([half, worker(commands=["a"])])
        self.assertIsNone(merged["start"])
        self.assertEqual(merged["end"], T0 + timedelta(minutes=5))
        self.assertIsNone(merged["duration_s"])


class TestWhyThatGuardIsDefensiveRatherThanRoutine(unittest.TestCase):
    """Half a span is not something a parser hands over today.

    Both readers set `start` and `end` inside one `if ts:` block, off the same
    timestamp, so the first record a session has gives it both and no record
    can give it one.  That is worth writing down, because it is the reason the
    two tests above have to build their input by hand instead of parsing a
    file — and the reason a reader who found the guard would be right to
    wonder whether it can ever fire.

    It fires the moment that stops being true: a third reader, a filter that
    clips a span to a window, a session read back out of a cache that lost a
    field.  Testing the invariant here means such a change shows up as this
    test failing, next to the tests for what the guard then has to do, rather
    than as a TypeError in somebody's digest.
    """

    def test_a_parsed_session_has_both_timestamps_or_neither(self):
        home = tempfile.mkdtemp(prefix="al-span-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        directory = os.path.join(home, ".claude", "projects", "-home-you-api")
        os.makedirs(directory)

        stamp = "2026-08-04T09:00:00.000Z"
        files = {
            # A whole session, a session of one record, and a session whose
            # only record carries no timestamp at all.
            "whole": [claude_user("whole", stamp, cwd="/home/you/api",
                                  text="do it"),
                      claude_assistant("whole", stamp)],
            "single": [claude_user("single", stamp, cwd="/home/you/api",
                                   text="do it")],
            "undated": [claude_user("undated", "", cwd="/home/you/api",
                                    text="do it")],
        }
        for name, records in files.items():
            path = os.path.join(directory, "{}.jsonl".format(name))
            with open(path, "w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record) + "\n")

        sessions, _sources, _unusable = find_sessions(home)
        self.assertEqual(len(sessions), 3)  # vacuity guard
        for session in sessions:
            self.assertEqual(
                session["start"] is None, session["end"] is None,
                "{} came out of the parser with half a span, which the "
                "merge's duration guard is the only thing standing "
                "between and a TypeError".format(session["id"]))


if __name__ == "__main__":
    unittest.main()
