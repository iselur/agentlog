"""A subagent's transcript is part of a sitting, not a sitting of its own.

Claude Code writes a subagent's conversation to its own file, one that sits
below the session that spawned it:

    ~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<runid>.jsonl

Nothing inside that file says which *project* it was in, and for a long time
this package answered that question by taking the name of the directory beside
the file — which is the literal word `subagents`.  All 402 subagent transcripts
on the machine this was written for were filed under a project by that name.
The same decoder also dropped the leading dash of an encoded slug without
putting the root slash back, so an ordinary session's project came out as
`home/you/api` rather than `/home/you/api`.

Neither is a wrong answer anyone would notice.  They are plausible-looking
labels, which is why they lasted, and why the test that covered the second one
asserted only that the words `home` and `you` appeared somewhere in the result
— true of the bug and of the fix alike.

The session id is the other half of the same question and it goes the other
way: every real subagent transcript repeats its parent's `sessionId` inside the
file, so the id was already right, and reading it off the path only matters
when the records do not carry one.  Both halves are tested here because they
are one rule — what a transcript's location says about it — and that rule now
lives in the format module `agentwatch` shares, so a correction lands in both
tools or in neither.
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

from agentlog.parser import find_sessions  # noqa: E402
from agentlog.transcript import decode_claude_project, session_id_for  # noqa: E402
from tests.fixtures import (  # noqa: E402
    claude_assistant, claude_user, codex_session_meta, codex_user_message,
)

STAMP = "2026-08-04T10:00:00.000Z"
PARENT = "0b42c9cc-846b-4d0c-94fb-1226fba9e63f"
SLUG = "-home-you-api"
PROJECT = "/home/you/api"


class TestWhatThePathSays(unittest.TestCase):
    """The two facts read straight off a path, with no file on disk."""

    def a_subagent_path(self, run="agent-a30bc72d535f"):
        return os.path.join("/home/you/.claude/projects", SLUG, PARENT,
                            "subagents", run + ".jsonl")

    def a_workflow_subagent_path(self, run="agent-a30bc72d535f"):
        # A subagent run by a workflow sits two directories deeper, under the
        # workflow's run id.  200 of the 602 subagent transcripts on this
        # machine are this shape, and the run id is what the old decoder
        # reported as their project.
        return os.path.join("/home/you/.claude/projects", SLUG, PARENT,
                            "subagents", "workflows", "wf_5e1bb28a-07b",
                            run + ".jsonl")

    def test_a_workflow_subagent_belongs_to_the_same_session(self):
        self.assertEqual(
            session_id_for(self.a_workflow_subagent_path(), "claude"), PARENT)

    def test_a_workflow_subagents_project_is_not_the_run_id(self):
        self.assertEqual(
            decode_claude_project(self.a_workflow_subagent_path()), PROJECT)

    def test_the_session_is_the_one_that_spawned_it(self):
        self.assertEqual(session_id_for(self.a_subagent_path(), "claude"),
                         PARENT)

    def test_an_ordinary_transcript_is_still_its_own_session(self):
        # The guard on the above: a rule that returned the parent directory's
        # name for every path would pass that test and break every other file.
        ordinary = os.path.join("/home/you/.claude/projects", SLUG,
                                PARENT + ".jsonl")
        self.assertEqual(session_id_for(ordinary, "claude"), PARENT)

    def test_the_project_is_the_projects_directory_not_the_word_subagents(self):
        self.assertEqual(decode_claude_project(self.a_subagent_path()), PROJECT)

    def test_the_project_keeps_its_leading_slash(self):
        # `home/you/api` is a plausible-looking label and an absolute path is
        # what it means.  The old decoder dropped the leading dash without
        # putting the root slash back, and every assertion over it said only
        # that the words were in there somewhere.
        ordinary = os.path.join("/home/you/.claude/projects", SLUG,
                                PARENT + ".jsonl")
        self.assertEqual(decode_claude_project(ordinary), PROJECT)

    def test_a_project_directory_that_is_not_encoded_is_left_alone(self):
        plain = "/home/you/.claude/projects/notes/s.jsonl"
        self.assertEqual(decode_claude_project(plain), "notes")


class TestItLandsOnTheRightRow(unittest.TestCase):
    """The same two facts, seen through a digest of a tree on disk."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-subagent-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.projects = os.path.join(self.home, ".claude", "projects")

    def write(self, directory, name, text, session_id=None):
        """One transcript.  `session_id=None` writes records that carry none.

        Real subagent transcripts repeat their parent's sessionId, so that is
        the default; the None case is the one where the path has to answer.
        """
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, name + ".jsonl")
        records = [
            claude_user(session_id or PARENT, STAMP, cwd=PROJECT, text=text),
            claude_assistant(session_id or PARENT, STAMP),
        ]
        if session_id is None:
            for record in records:
                record.pop("sessionId", None)
        with open(path, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return path

    def a_session_with_a_subagent(self, **kwargs):
        holder = os.path.join(self.projects, SLUG)
        self.write(holder, PARENT, "do the thing", session_id=PARENT)
        self.write(os.path.join(holder, PARENT, "subagents"),
                   "agent-a30bc72d535f", "go and look", **kwargs)

    def sessions(self):
        found, _sources, _unusable = find_sessions(self.home)
        return found

    def test_no_row_is_labelled_subagents(self):
        # The fix.  Before it, the second row's project was the word
        # `subagents` -- a project nobody has, sitting in the list next to the
        # real one.
        self.a_session_with_a_subagent()
        self.assertEqual([s["project"] for s in self.sessions()], [PROJECT])

    def test_the_two_files_are_one_session(self):
        self.a_session_with_a_subagent()
        self.assertEqual([s["id"] for s in self.sessions()], [PARENT])

    def test_the_subagents_work_is_in_it(self):
        # Merged, not chosen between: the point of putting it on the parent's
        # row is that what the subagent did is counted, not dropped.
        self.a_session_with_a_subagent()
        self.assertEqual(self.sessions()[0]["user_turns"], 2)

    def test_a_subagent_that_names_no_session_is_placed_by_its_path(self):
        # The half the records cannot answer.  Every subagent transcript on
        # this machine repeats its parent's sessionId, so the path is only
        # asked when one does not -- a truncated file, a format change, or the
        # live tail `agentwatch` does, which has no records to read yet.
        self.a_session_with_a_subagent(session_id=None)
        self.assertEqual([s["id"] for s in self.sessions()], [PARENT])

    def test_a_subagent_left_behind_on_its_own_is_still_that_sitting(self):
        # Transcripts get tidied up one at a time.  A subagent whose parent
        # file is gone is still that sitting's work, and still in that project.
        holder = os.path.join(self.projects, SLUG)
        self.write(os.path.join(holder, PARENT, "subagents"),
                   "agent-a30bc72d535f", "go and look", session_id=None)
        found = self.sessions()
        self.assertEqual([s["id"] for s in found], [PARENT])
        self.assertEqual([s["project"] for s in found], [PROJECT])


UUID = "019fd922-1111-2222-3333-444455556666"
ROLLOUT = "rollout-2026-08-06T22-12-29-" + UUID


class TestACodexRolloutIsNamedByItsUuid(unittest.TestCase):
    """The other half of the same rule, for the other log format.

    Codex names a file `rollout-<date>-<uuid>.jsonl`, and the date in the middle
    is already the row's start time -- repeating it in the id gives a
    fifty-character label for something meant to be glanced at.  So the id is
    the last five dash-parts, the uuid.

    Every one of the 1,219 rollouts on this machine repeats its session id in a
    `session_meta` record at the head of the file, and that record wins, so the
    name is normally never asked.  It is asked when the head is missing -- a
    file copied while it was being written, a truncated one, a log rotated
    mid-session.  Such a file is still read (nothing about it is unusable; it is
    just short), so the difference is not an error, it is a row whose name is
    the whole filename.  That is the case with no test until this one, and it is
    also the case `agentwatch` lives in permanently: tailing a file, it needs a
    name for the session before it has read anything at all.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-rollout-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.dir = os.path.join(self.home, ".codex", "sessions", "2026", "08")
        os.makedirs(self.dir)

    def write(self, records):
        path = os.path.join(self.dir, ROLLOUT + ".jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def ids(self):
        found, _sources, _unusable = find_sessions(self.home)
        return [s["id"] for s in found]

    def test_the_id_is_read_off_the_path(self):
        self.assertEqual(session_id_for("/x/" + ROLLOUT + ".jsonl", "codex"),
                         UUID)

    def test_a_rollout_that_lost_its_head_is_named_by_its_uuid(self):
        # No session_meta, so nothing in the file answers.  Without the
        # shortening this row is labelled with the whole filename, date and all.
        self.write([codex_user_message(STAMP, "do stuff")])
        self.assertEqual(self.ids(), [UUID])

    def test_the_record_still_wins_when_there_is_one(self):
        # The guard on the above: the path is the fallback, not the rule.
        self.write([codex_session_meta("stated-in-the-file", PROJECT, STAMP),
                    codex_user_message(STAMP, "do stuff")])
        self.assertEqual(self.ids(), ["stated-in-the-file"])


if __name__ == "__main__":
    unittest.main()
