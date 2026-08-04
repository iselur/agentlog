"""A message the machine injected is not a turn you took.

A `user` record is written for a fourth thing that nobody typed.  Claude Code
writes one, marked `isMeta: true`, whenever it needs to put text into the
conversation on its own account: the caveat that precedes a slash command's
output, the body of a skill being loaded, a message relayed from another
session, a nudge to continue, the placeholder that stands in for an image.

They carry no tool_result and no `isSidechain`, so the two rules that already
keep the agent's own loop out of the turn count let every one of them through,
and each is counted as a turn the person took.

On the developer's own logs that was 210 records against 2109 real turns — a
tenth of the count, in the direction a reader cannot check.  The same asymmetry
as the sidechain fix before it: an under-count can be caught by scrolling the
log, an over-count just reads as a busier day than it was.

Every one of the 210 was machine text.  Not one was a person.

What the record still is, is part of the sitting: it has a timestamp, a cwd and
a version, and those are kept.  Only the claim that you spoke goes.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agentlog.parser import find_sessions  # noqa: E402

DAY = "2026-08-04"


def _at(hour, minute=0):
    return "%sT%02d:%02d:00.000Z" % (DAY, hour, minute)


def _typed(uuid, text, when):
    """What a person typing looks like."""
    return {"type": "user", "uuid": uuid, "timestamp": when,
            "cwd": "/home/you/api", "version": "2.1.220",
            "message": {"role": "user", "content": text}}


def _meta(uuid, text, when):
    """What Claude Code injecting text looks like."""
    rec = _typed(uuid, text, when)
    rec["isMeta"] = True
    return rec


def _assistant(uuid, call_id, command, when):
    return {"type": "assistant", "uuid": uuid, "timestamp": when,
            "message": {"role": "assistant", "id": "msg-" + call_id,
                        "model": "claude-opus-5",
                        "content": [{"type": "tool_use", "id": call_id,
                                     "name": "Bash",
                                     "input": {"command": command}}],
                        "usage": {"input_tokens": 10, "output_tokens": 5}}}


def _result(uuid, call_id, when, is_error=False):
    return {"type": "user", "uuid": uuid, "timestamp": when,
            "message": {"role": "user",
                        "content": [{"type": "tool_result",
                                     "tool_use_id": call_id,
                                     "is_error": is_error,
                                     "content": "output"}]}}


class Case(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="agentlog-meta-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.projects = os.path.join(self.home, ".claude", "projects")

    def write(self, records, project="-home-you-api", name="aaaa1111"):
        d = os.path.join(self.projects, project)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        return path

    def only(self):
        sessions, _, _ = find_sessions(self.home)
        self.assertEqual(len(sessions), 1, sessions)
        return sessions[0]


class TestTheShapesClaudeCodeInjects(Case):
    """Each of these was taken from a real log, by opening line."""

    def one(self, text):
        self.write([
            _typed("u-1", "run the tests", _at(9)),
            _meta("m-1", text, _at(9, 1)),
        ])
        return self.only()["user_turns"]

    def test_a_slash_command_caveat_is_not_a_turn(self):
        # 102 of the 210: the banner that precedes a local command's output.
        self.assertEqual(self.one(
            "<local-command-caveat>Caveat: The messages below were generated "
            "by the user while running a local command.</local-command-caveat>"
        ), 1)

    def test_a_skill_body_is_not_a_turn(self):
        # Invoking a skill drops its whole markdown body into the
        # conversation as a user record.  Nobody typed a page of markdown.
        self.assertEqual(self.one(
            "Base directory for this skill: /tmp/bundled-skills/dataviz\n\n"
            "# Data Visualization\n\nA chart is read by people."
        ), 1)

    def test_a_message_relayed_from_another_session_is_not_a_turn(self):
        self.assertEqual(self.one(
            "Another Claude session sent a message while you were working:\n"
            "the build is green"
        ), 1)

    def test_a_system_notification_is_not_a_turn(self):
        self.assertEqual(self.one(
            "[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated "
            "message."
        ), 1)

    def test_a_nudge_to_continue_is_not_a_turn(self):
        self.assertEqual(self.one("Continue from where you left off."), 1)

    def test_an_image_placeholder_is_not_a_turn(self):
        # The person did paste an image, but the record that says so is the
        # harness describing the paste, and the paste itself is already the
        # non-meta record beside it.  Counting both counts the person twice.
        self.assertEqual(self.one(
            "[Image: original 5712x4284, displayed at 2000x1500.]"), 1)

    def test_text_delivered_as_blocks_rather_than_a_string(self):
        # Some injected records carry a content list, not a bare string; the
        # marker is the same field either way.
        rec = _meta("m-1", "", _at(9, 1))
        rec["message"]["content"] = [{"type": "text", "text": "# A Skill"}]
        self.write([_typed("u-1", "go", _at(9)), rec])
        self.assertEqual(self.only()["user_turns"], 1)


class TestWhatIsStillATurn(Case):

    def test_a_person_typing_is_a_turn(self):
        self.write([_typed("u-1", "run the tests", _at(9)),
                    _typed("u-2", "now ship it", _at(9, 5))])
        self.assertEqual(self.only()["user_turns"], 2)

    def test_a_record_with_the_field_set_false_is_a_turn(self):
        rec = _typed("u-2", "now ship it", _at(9, 5))
        rec["isMeta"] = False
        self.write([_typed("u-1", "go", _at(9)), rec])
        self.assertEqual(self.only()["user_turns"], 2)

    def test_a_record_without_the_field_at_all_is_a_turn(self):
        # Older logs have no isMeta.  Only an explicit true is machine text;
        # treating absence as true would drop every turn ever recorded before
        # the field existed, which is the opposite mistake and a worse one.
        rec = _typed("u-2", "now ship it", _at(9, 5))
        self.assertNotIn("isMeta", rec)
        self.write([_typed("u-1", "go", _at(9)), rec])
        self.assertEqual(self.only()["user_turns"], 2)

    def test_a_string_true_is_not_an_explicit_true(self):
        rec = _typed("u-2", "now ship it", _at(9, 5))
        rec["isMeta"] = "true"
        self.write([_typed("u-1", "go", _at(9)), rec])
        self.assertEqual(self.only()["user_turns"], 2)


class TestTheRecordIsStillPartOfTheSitting(Case):

    def test_it_still_says_which_project_this_is(self):
        # A session whose only record naming the directory is an injected one
        # still knows where it happened.  Dropping the turn must not drop that.
        meta = _meta("m-1", "Continue from where you left off.", _at(9))
        result = _result("r-1", "t1", _at(9, 1))
        self.write([meta, _assistant("a-1", "t1", "pytest -x", _at(9, 1)),
                    result])
        s = self.only()
        self.assertEqual(s["project"], "/home/you/api")
        self.assertEqual(s["version"], "2.1.220")

    def test_it_still_counts_toward_the_span(self):
        # The clock was running: the machine wrote that text during the
        # sitting, and a session that starts at the injected record started
        # then.
        self.write([_meta("m-1", "Continue.", _at(9)),
                    _assistant("a-1", "t1", "pytest -x", _at(10)),
                    _result("r-1", "t1", _at(10, 1))])
        s = self.only()
        self.assertEqual(s["start"].hour, 9)

    def test_a_session_that_is_only_injected_text_is_still_a_session(self):
        # Zero turns is the honest answer, not "no session here".  The file
        # exists, the machine wrote in it, and saying nothing about it would
        # be the under-count.
        self.write([_meta("m-1", "Continue from where you left off.", _at(9)),
                    _assistant("a-1", "t1", "pytest -x", _at(9, 1)),
                    _result("r-1", "t1", _at(9, 2))])
        s = self.only()
        self.assertEqual(s["user_turns"], 0)
        self.assertEqual(s["commands"], ["pytest -x"])

    def test_an_error_inside_an_injected_record_still_counts(self):
        # Belt and braces: no real meta record carries a tool result, but if
        # one ever did, a failure that happened is a failure that happened.
        # The turn is the only thing the marker speaks to.
        rec = _result("r-1", "t1", _at(9, 2), is_error=True)
        rec["isMeta"] = True
        self.write([_typed("u-1", "go", _at(9)),
                    _assistant("a-1", "t1", "pytest -x", _at(9, 1)), rec])
        s = self.only()
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["user_turns"], 1)


class TestItComposesWithTheRulesAlreadyThere(Case):

    def test_tool_results_sidechains_and_injected_text_all_drop(self):
        # The three non-person shapes together, against one real turn.
        side = _typed("s-1", "a prompt for the subagent", _at(9, 3))
        side["isSidechain"] = True
        self.write([
            _typed("u-1", "run the tests", _at(9)),
            _assistant("a-1", "t1", "pytest -x", _at(9, 1)),
            _result("r-1", "t1", _at(9, 2)),
            side,
            _meta("m-1", "Continue from where you left off.", _at(9, 4)),
        ])
        self.assertEqual(self.only()["user_turns"], 1)

    def test_the_ratio_on_a_realistic_sitting(self):
        # Roughly the shape of a real log: a few typed turns, a great many
        # tool results, a handful of injected records.  The old rules got the
        # tool results; this one gets the rest.
        records = []
        for n in range(3):
            records.append(_typed("u-%d" % n, "step %d" % n, _at(9, n)))
            for c in range(4):
                call = "t%d%d" % (n, c)
                records.append(_assistant("a" + call, call, "make", _at(9, n)))
                records.append(_result("r" + call, call, _at(9, n)))
            records.append(_meta("m-%d" % n, "Continue.", _at(9, n)))
        self.write(records)
        self.assertEqual(self.only()["user_turns"], 3)


if __name__ == "__main__":
    unittest.main()
