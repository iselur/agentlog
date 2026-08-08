"""`--file PATH` reads one transcript and nothing else.

A hook is handed a transcript path and given about a minute; scanning a whole
home takes minutes.  So there has to be a way in that starts from the path.

Two things are worth pinning here, and neither is the speed.  The first is that
the file is read as whoever actually wrote it, decided by reading it both ways
rather than by the path it arrived on or by a marker record near the top — the
two failures a hook's file is most likely to have are a path nowhere near the
usual directory and a truncation that took the marker with it.  The second is
that the window does not apply: a session handed over by name is reported
whole, including the parts of it that happened yesterday.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.parser import read_one_session  # noqa: E402
from tests.fixtures import (  # noqa: E402
    a_now_that_keeps,
    claude_assistant,
    claude_user,
    codex_function_call,
    codex_session_meta,
    codex_user_message,
    tool_bash,
)


def _stamp(when):
    return when.isoformat()


class Case(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Anchored once, so the offsets below keep the span they describe.
        self.now = a_now_that_keeps(90)

    def write(self, name, records):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        return path

    def a_claude_file(self, name="anywhere.jsonl", ago=30):
        when = _stamp(self.now - timedelta(minutes=ago))
        return self.write(name, [
            claude_user("sess-claude", when, cwd="/home/you/work",
                        text="ship the release"),
            claude_assistant("sess-claude", when,
                             tools=[tool_bash("git commit -m 'ship it'")]),
        ])

    def a_codex_file(self, name="rollout.jsonl", ago=30):
        when = _stamp(self.now - timedelta(minutes=ago))
        return self.write(name, [
            codex_session_meta("sess-codex", "/home/you/work", when),
            codex_user_message(when, "review the plan"),
            codex_function_call("shell", {"command": ["pytest", "-q"]}, when),
        ])

    def run_log(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.tmp, *argv],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100"))


class TestItIsReadAsWhoeverWroteIt(Case):

    def test_a_claude_transcript_anywhere_on_disk_is_read_as_claude(self):
        # The path is the thing a hook cannot promise: the file is wherever the
        # agent put it, which is not under ~/.claude/projects for a worktree,
        # a copied tree, or a test.
        sessions, sources, unusable = read_one_session(self.a_claude_file())
        self.assertEqual([s["source"] for s in sessions], ["claude"])
        self.assertEqual(sources, ["Claude Code"])
        self.assertEqual(unusable, [])

    def test_a_codex_rollout_anywhere_on_disk_is_read_as_codex(self):
        sessions, sources, unusable = read_one_session(self.a_codex_file())
        self.assertEqual([s["source"] for s in sessions], ["codex"])
        self.assertEqual(sources, ["Codex"])
        self.assertEqual(unusable, [])

    def test_the_name_of_the_file_decides_nothing(self):
        # Every rollout on this machine is named rollout-*.jsonl and sits under
        # ~/.codex, so a corpus of them cannot show whether the name is being
        # read.  Give a Claude transcript a Codex file's name and see.
        sessions, _, _ = read_one_session(
            self.a_claude_file(name="rollout-2026-08-08T11-11-07-abc.jsonl"))
        self.assertEqual([s["source"] for s in sessions], ["claude"])

    def test_a_file_that_lost_its_opening_records_is_still_read(self):
        # The reason the format is not sniffed from a marker near the top.  A
        # rollout copied mid-write, truncated, or rotated has no session_meta
        # left; every file in a healthy corpus has one, so the corpus is
        # exactly the wrong place to look for this.  It is still a Codex file
        # and still holds the work.
        when = _stamp(self.now - timedelta(minutes=20))
        path = self.write("truncated.jsonl", [
            codex_function_call("shell", {"command": ["pytest", "-q"]}, when),
            codex_user_message(when, "keep going"),
        ])
        sessions, sources, unusable = read_one_session(path)
        self.assertEqual(unusable, [])
        self.assertEqual([s["source"] for s in sessions], ["codex"])
        self.assertEqual(sources, ["Codex"])

    def test_a_file_that_is_not_a_transcript_is_reported_not_guessed(self):
        path = os.path.join(self.tmp, "notes.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# just some notes\n")
        sessions, sources, unusable = read_one_session(path)
        self.assertEqual(sessions, [])
        self.assertEqual(sources, [])
        self.assertEqual([p for p, _ in unusable], [path])

    def test_a_file_that_is_not_there_is_reported_not_raised(self):
        missing = os.path.join(self.tmp, "gone.jsonl")
        sessions, _, unusable = read_one_session(missing)
        self.assertEqual(sessions, [])
        self.assertEqual([p for p, _ in unusable], [missing])

    def test_a_directory_handed_over_by_mistake_is_reported_not_raised(self):
        sessions, _, unusable = read_one_session(self.tmp)
        self.assertEqual(sessions, [])
        self.assertEqual([p for p, _ in unusable], [self.tmp])


class TestTheWindowDoesNotApply(Case):

    def test_a_session_from_last_week_is_still_reported_in_full(self):
        # The property that made --file ignore the time command.  A hook hands
        # over the session it is compacting; that session may have started days
        # ago, and answering an explicit request with an empty page because it
        # did not start today would be the worst possible reading of it.
        old = _stamp(self.now - timedelta(days=6))
        path = self.write("old.jsonl", [
            claude_user("sess-old", old, cwd="/home/you/work",
                        text="the long-running one"),
            claude_assistant("sess-old", old,
                             tools=[tool_bash("git push")]),
        ])
        r = self.run_log("--file", path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("work", r.stdout)
        # And the day command it was nominally given is not what was answered.
        self.assertNotIn("today", r.stdout.splitlines()[0])

    def test_the_same_file_is_empty_through_the_ordinary_day_command(self):
        # The complement, and the thing that makes the test above mean
        # something: without --file that session is correctly out of scope, so
        # the page above is not just a page that would have printed anyway.
        old = _stamp(self.now - timedelta(days=6))
        proj = os.path.join(self.tmp, ".claude", "projects", "work")
        os.makedirs(proj)
        with open(os.path.join(proj, "old.jsonl"), "w", encoding="utf-8") as fh:
            for rec in (claude_user("sess-old", old, cwd="/home/you/work"),
                        claude_assistant("sess-old", old)):
                fh.write(json.dumps(rec) + "\n")
        r = self.run_log("today")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("/home/you/work", r.stdout)


class TestTheFlagRefusesWhatItCannotMean(Case):

    def test_it_is_refused_with_list(self):
        r = self.run_log("list", "--file", self.a_claude_file())
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("--file", r.stderr)

    def test_it_is_refused_with_show(self):
        r = self.run_log("show", "abc", "--file", self.a_claude_file())
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("--file", r.stderr)

    def test_a_file_it_cannot_read_exits_two_and_says_which(self):
        missing = os.path.join(self.tmp, "gone.jsonl")
        r = self.run_log("--file", missing)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn(missing, r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_the_help_says_the_time_command_does_not_apply(self):
        r = self.run_log("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--file", r.stdout)
        one_line = " ".join(r.stdout.split())
        self.assertIn("time command does not apply", one_line)


if __name__ == "__main__":
    unittest.main()
