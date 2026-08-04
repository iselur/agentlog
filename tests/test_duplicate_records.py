"""The same record, present in two files, counted once.

Claude Code puts a record in more than one file in two ordinary situations, and
until this file existed agentlog counted the work in both of them.

The first is a resume.  `claude --resume` opens a new session with a new id and
copies the earlier transcript into it verbatim — same uuids, same timestamps —
so the commands from the first sitting are on disk twice.  On the machine this
was written for, 5 pairs of sessions overlapped this way, sharing 928 records.

The second is a project directory that has been copied or moved.  The session
file then exists byte-for-byte under both names, both are found by the glob,
and neither is a symlink, so the resolved-path check in `find_sessions` does
not see them.  There were 31 of those here, 934 records.

`_merge_sessions` groups by session id and *adds* the tallies up, which is
right for Codex's parallel workers — each file is a different worker's real
work — and exactly wrong for a copy, where both files are the same work.  Its
own docstring says why this is the worse direction to be wrong in: an
under-count can be caught by adding up the source files, an over-count cannot
be caught at all.

The rule these tests pin is that a record uuid names an event, and an event is
counted once.  The file that carries it first — oldest first, by modification
time — is the one that reports it, so a resume shows the work done in the
resume and the earlier session keeps its own.

Measured before the fix, across every Claude Code log on this machine:
commands 11539 with 287 replayed, writes 4170 with 57, errors 510 with 19,
turns 2231 with 92.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.parser import find_sessions, _oldest_first  # noqa: E402

DAY = "2026-08-04"


def _user(uuid, text, ts):
    return {"type": "user", "uuid": uuid, "sessionId": None,
            "timestamp": ts, "cwd": "/home/you/api", "version": "2.1.0",
            "message": {"role": "user", "content": text}}


def _bash(uuid, tool_id, command, ts):
    return {"type": "assistant", "uuid": uuid, "timestamp": ts,
            "message": {"role": "assistant", "id": "msg_" + uuid,
                        "usage": {"input_tokens": 100, "output_tokens": 10},
                        "content": [{"type": "tool_use", "id": tool_id,
                                     "name": "Bash",
                                     "input": {"command": command}}]}}


def _write(uuid, tool_id, path, ts):
    return {"type": "assistant", "uuid": uuid, "timestamp": ts,
            "message": {"role": "assistant", "id": "msg_" + uuid,
                        "usage": {"input_tokens": 100, "output_tokens": 10},
                        "content": [{"type": "tool_use", "id": tool_id,
                                     "name": "Write",
                                     "input": {"file_path": path,
                                               "content": "x"}}]}}


def _error(uuid, tool_id, ts):
    return {"type": "user", "uuid": uuid, "timestamp": ts,
            "message": {"role": "user",
                        "content": [{"type": "tool_result",
                                     "tool_use_id": tool_id,
                                     "is_error": True,
                                     "content": "boom"}]}}


def _sitting(prefix, hour):
    """Three records of real work: a turn, a command, a write."""
    t = "%sT%02d:00:00.000Z" % (DAY, hour)
    return [
        _user(prefix + "-u1", "do the thing", t),
        _bash(prefix + "-a1", prefix + "-t1", "pytest -x", t),
        _write(prefix + "-a2", prefix + "-t2", "/home/you/api/src/app.py", t),
    ]


class Case(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-dupe-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.projects = os.path.join(self.home, ".claude", "projects")
        os.makedirs(self.projects)

    def write(self, project, session_id, records, mtime=None):
        d = os.path.join(self.projects, project)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, session_id + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def totals(self):
        sessions, _sources, unusable = find_sessions(self.home)
        return {
            "sessions": len(sessions),
            "commands": sum(len(s["commands"]) for s in sessions),
            "written": sum(len(s["files_written"]) for s in sessions),
            "errors": sum(s["errors"] for s in sessions),
            "turns": sum(s["user_turns"] for s in sessions),
            "tokens_in": sum(s.get("tokens_in") or 0 for s in sessions),
            "unusable": unusable,
            "list": sessions,
        }


class TestOneSessionCopiedIntoTwoProjects(Case):
    """A project directory that was copied, so the log exists twice."""

    def setUp(self):
        super().setUp()
        records = _sitting("s", 9)
        # Byte-identical, same session id, two project directories, neither a
        # symlink — which is how a moved or copied checkout leaves them.
        self.write("-home-you-api", "aaaaaaaa-0000-0000-0000-000000000001",
                   records, mtime=1000)
        self.write("-home-you-api-copy", "aaaaaaaa-0000-0000-0000-000000000001",
                   records, mtime=2000)

    def test_it_is_one_session_not_two(self):
        self.assertEqual(self.totals()["sessions"], 1)

    def test_the_command_is_counted_once(self):
        self.assertEqual(self.totals()["commands"], 1)

    def test_the_written_file_is_counted_once(self):
        self.assertEqual(self.totals()["written"], 1)

    def test_the_turn_is_counted_once(self):
        # This is the count `_merge_sessions` adds up, so it is the one that
        # doubled.
        self.assertEqual(self.totals()["turns"], 1)

    def test_the_tokens_are_counted_once(self):
        self.assertEqual(self.totals()["tokens_in"], 200)

    def test_the_copy_is_not_reported_as_an_unusable_file(self):
        # `unusable` means "there is a file on disk you should know about".
        # A duplicate is accounted for, not skipped, so saying so would be
        # noise — and would read as data missing from the report.
        self.assertEqual(self.totals()["unusable"], [])


class TestAResumedSession(Case):
    """`claude --resume`: a new session id carrying the old transcript."""

    def setUp(self):
        super().setUp()
        self.first = _sitting("first", 9)
        # The resume replays every record of the first sitting verbatim — same
        # uuids, same timestamps — and then does two new things.
        later = "%sT15:00:00.000Z" % DAY
        self.second = list(self.first) + [
            _bash("second-a1", "second-t1", "ruff check", later),
            _error("second-u1", "second-t1", later),
        ]
        self.write("-home-you-api", "bbbbbbbb-0000-0000-0000-000000000001",
                   self.first, mtime=1000)
        self.write("-home-you-api", "cccccccc-0000-0000-0000-000000000002",
                   self.second, mtime=2000)

    def test_the_replayed_command_is_not_counted_twice(self):
        self.assertEqual(self.totals()["commands"], 2)   # pytest, ruff

    def test_the_replayed_turn_is_not_counted_twice(self):
        self.assertEqual(self.totals()["turns"], 1)

    def test_the_replayed_write_is_not_counted_twice(self):
        self.assertEqual(self.totals()["written"], 1)

    def test_the_replayed_tokens_are_not_counted_twice(self):
        # Three assistant records in total: two in the first sitting, one new.
        self.assertEqual(self.totals()["tokens_in"], 300)

    def test_both_sittings_are_still_shown_as_sessions(self):
        # Deduping records must not make a session disappear: the resume is a
        # real second sitting and belongs on its own row.
        self.assertEqual(self.totals()["sessions"], 2)

    def test_the_earlier_sitting_keeps_its_own_work(self):
        # The file that carried the record first is the one that reports it,
        # so the work stays where it happened rather than moving to the resume.
        by_id = {s["id"]: s for s in self.totals()["list"]}
        first = by_id["bbbbbbbb-0000-0000-0000-000000000001"]
        self.assertEqual(first["commands"], ["pytest -x"])
        self.assertEqual(first["user_turns"], 1)

    def test_the_resume_reports_only_what_it_did(self):
        by_id = {s["id"]: s for s in self.totals()["list"]}
        second = by_id["cccccccc-0000-0000-0000-000000000002"]
        self.assertEqual(second["commands"], ["ruff check"])
        self.assertEqual(second["user_turns"], 0)
        self.assertEqual(second["errors"], 1)

    def test_the_replay_does_not_stretch_the_resumes_span(self):
        # Before the fix the resume began at 09:00, because it carried the
        # first sitting's timestamps, and so looked like a six-hour session
        # that had been running since morning.
        by_id = {s["id"]: s for s in self.totals()["list"]}
        second = by_id["cccccccc-0000-0000-0000-000000000002"]
        self.assertEqual(second["start"].hour, 15)


class TestAFileThatIsNothingButReplay(Case):
    """A resume that was opened and then abandoned without doing anything."""

    def setUp(self):
        super().setUp()
        records = _sitting("first", 9)
        self.write("-home-you-api", "11111111-0000-0000-0000-000000000001",
                   records, mtime=1000)
        self.write("-home-you-api", "22222222-0000-0000-0000-000000000002",
                   records, mtime=2000)

    def test_it_does_not_appear_as_an_empty_session(self):
        # An empty row would read as a sitting where nothing happened, which
        # is a different and less true statement than "nothing happened yet".
        self.assertEqual(self.totals()["sessions"], 1)

    def test_it_is_not_reported_as_a_file_with_no_readable_records(self):
        # The `unusable` list means "work may be missing from this report".
        # Every record in this file is in the report already, under the
        # session that did it.
        self.assertEqual(self.totals()["unusable"], [])

    def test_nothing_it_replayed_is_counted_twice(self):
        t = self.totals()
        self.assertEqual((t["commands"], t["written"], t["turns"]), (1, 1, 1))


class TestTheRuleIsPerRecord(Case):

    def test_two_records_that_merely_look_alike_are_both_counted(self):
        # Same command, same timestamp, different uuid: two real runs of the
        # same thing, and dropping one would be the under-count this whole
        # exercise exists to avoid.  The command list is deduped for display,
        # so the tokens are what show both records were read.
        t = "%sT09:00:00.000Z" % DAY
        self.write("-home-you-api", "dddddddd-0000-0000-0000-000000000001", [
            _bash("d-a1", "d-t1", "pytest -x", t),
            _bash("d-a2", "d-t2", "pytest -x", t),
        ], mtime=1000)
        self.assertEqual(self.totals()["tokens_in"], 200)

    def test_records_with_no_uuid_do_not_collapse_into_one(self):
        # Nothing guarantees the field is there.  Two records missing it are
        # two records, not one seen twice.
        t = "%sT09:00:00.000Z" % DAY
        a = _bash("x", "e-t1", "make build", t)
        b = _bash("y", "e-t2", "make test", t)
        del a["uuid"]
        del b["uuid"]
        self.write("-home-you-api", "eeeeeeee-0000-0000-0000-000000000001",
                   [a, b], mtime=1000)
        sessions, _s, _u = find_sessions(self.home)
        self.assertEqual(sorted(sessions[0]["commands"]),
                         ["make build", "make test"])

    def test_the_totals_do_not_depend_on_which_file_is_read_first(self):
        # Ownership goes to the older file, so the answer is the same however
        # the filesystem happens to hand the paths over.
        first = _sitting("first", 9)
        second = list(first) + [
            _bash("second-a1", "second-t1", "ruff check",
                  "%sT15:00:00.000Z" % DAY)]
        # zzz sorts after aaa, but is the older file, so it owns the records.
        self.write("-home-you-api", "zzzzzzzz-0000-0000-0000-000000000001",
                   first, mtime=1000)
        self.write("-home-you-api", "aaaaaaaa-0000-0000-0000-000000000002",
                   second, mtime=2000)
        by_id = {s["id"]: s for s in find_sessions(self.home)[0]}
        self.assertEqual(
            by_id["zzzzzzzz-0000-0000-0000-000000000001"]["commands"],
            ["pytest -x"])
        self.assertEqual(
            by_id["aaaaaaaa-0000-0000-0000-000000000002"]["commands"],
            ["ruff check"])


class TestTheOrderFilesAreRead(Case):

    def test_a_file_that_vanished_sorts_last(self):
        # A file listed a moment ago and gone by the time it is stat-ed has no
        # mtime to order it by.  It sorts last rather than first, so a file
        # whose age is actually known is never displaced by one whose is not --
        # and this ordering is what decides which file owns a shared record.
        real = self.write("api", "aaaa1111", _sitting("a", 9))
        gone = os.path.join(os.path.dirname(real), "vanished.jsonl")
        self.assertEqual(_oldest_first([gone, real]), [real, gone])


class TestCodexIsLeftAlone(Case):
    """Codex records carry no uuid, and its duplicate files are real work."""

    def setUp(self):
        super().setUp()
        self.codex = os.path.join(self.home, ".codex", "sessions",
                                  "2026", "08", "04")
        os.makedirs(self.codex)

    def _worker(self, name, sid, command):
        path = os.path.join(self.codex, name)
        rows = [
            {"type": "session_meta", "timestamp": "%sT09:00:00.000Z" % DAY,
             "payload": {"id": sid, "cwd": "/home/you/api"}},
            {"type": "response_item", "timestamp": "%sT09:01:00.000Z" % DAY,
             "payload": {"type": "custom_tool_call", "call_id": name,
                         "input": json.dumps({"command": command})}},
        ]
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def test_two_worker_files_of_one_session_still_add_up(self):
        sid = "019f80fa-4d34-7513-8add-a5368508ba77"
        self._worker("rollout-2026-08-04T09-00-00-" + sid + ".jsonl",
                     sid, "pytest -x")
        self._worker("rollout-2026-08-04T09-00-01-" + sid + ".jsonl",
                     sid, "ruff check")
        sessions, _s, _u = find_sessions(self.home)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sorted(sessions[0]["commands"]),
                         ["pytest -x", "ruff check"])


if __name__ == "__main__":
    unittest.main()
