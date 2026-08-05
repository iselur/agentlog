"""A field nobody can parse must not be reported as an error that happened.

`_failed` says so in its own docstring — "Guessing 'failed' from a field nobody
can parse would invent errors that never happened, which is worse than missing
a real one" — and until now nothing held it to that.  A mutation sweep flipped
every one of its unreadable-input branches to `True` and the suite stayed green
on all of them.  The same was true of `_script_failed`, of `_count`'s bool
guard, and of the apply_patch scanner's guard against a missing text.

The direction matters and it is not symmetric.  This tool reports on work that
already happened; nobody can go back and check.  A missed failure means a
digest that is quietly incomplete.  An invented failure means a digest that
says a command you ran fine came back non-zero — and the person reading it goes
looking for a bug that was never there, in a log they have already thrown away.

The reachable case is not exotic, either.  Codex writes a
`function_call_output` for every tool call, and only the shell ones carry an
`exit_code` in their metadata.  A read, a search, an MCP call — none of them
have one, so `_failed(None)` is answered several times per turn in every real
session on disk.  Flip it and the digest reports an error for every tool the
agent used.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog import parser, transcript  # noqa: E402
from tests.fixtures import make_codex_dir  # noqa: E402

SID = "019fc384-aaaa-bbbb-cccc-ddddeeeeffff"
CWD = "/home/you/api"


class TestAnUnreadableExitCodeIsNotAFailure(unittest.TestCase):
    """`_failed`, one branch per way a log can fail to say what happened."""

    def test_the_helper_can_still_see_a_real_failure(self):
        # Every assertion below says "not a failure", so a `_failed` that
        # answered False to everything would pass all of them and report a
        # clean day forever.  This is the one that says it still answers.
        self.assertTrue(parser._failed(1))
        self.assertTrue(parser._failed("2"))
        self.assertTrue(parser._failed(-1))

    def test_a_missing_exit_code_is_not_a_failure(self):
        # The common one: every non-shell tool call reaches here.
        self.assertFalse(parser._failed(None))

    def test_an_exit_code_that_is_not_a_number_is_not_a_failure(self):
        self.assertFalse(parser._failed("killed"))
        self.assertFalse(parser._failed(""))

    def test_an_exit_code_of_an_unexpected_shape_is_not_a_failure(self):
        # A future Codex could write `{"signal": 9}` here, or a list, and the
        # honest answer to "did this exit non-zero" is that we cannot tell.
        self.assertFalse(parser._failed({"signal": 9}))
        self.assertFalse(parser._failed(["1"]))

    def test_a_boolean_exit_code_is_not_a_failure(self):
        # JSON `true` is not exit code 1.  Something wrote the wrong type; it
        # is not evidence about how the command ended.
        self.assertFalse(parser._failed(True))
        self.assertFalse(parser._failed(False))


class TestScriptOutputOfAnUnexpectedShape(unittest.TestCase):
    """`_script_failed`, which reads free text rather than a number."""

    def test_the_helper_can_still_see_a_real_failure(self):
        marker = transcript._SCRIPT_FAILED
        self.assertTrue(transcript.script_failed(marker + " something"))
        self.assertTrue(transcript.script_failed(
            [{"text": marker + " something"}]))

    def test_output_that_is_neither_text_nor_blocks_is_not_a_failure(self):
        self.assertFalse(transcript.script_failed(None))
        self.assertFalse(transcript.script_failed({"text": "whatever"}))
        self.assertFalse(transcript.script_failed(7))

    def test_a_block_list_with_something_else_in_it_is_read_not_refused(self):
        # Content blocks are a list of dicts by contract, and contracts slip.
        # A bare string among them, or a block whose `text` is not a string,
        # is a block this cannot read — the rest of the list is still read.
        marker = transcript._SCRIPT_FAILED
        self.assertTrue(transcript.script_failed(
            [{"text": marker + " nope"}, "a bare string", {"text": None}]))
        self.assertFalse(transcript.script_failed(
            ["a bare string", {"text": None}, {}]))


class TestATokenCountThatIsNotACount(unittest.TestCase):
    """`_count`, whose answer is added into the totals a report prints."""

    def test_the_helper_can_still_count(self):
        self.assertEqual(parser._count(1200), 1200)
        self.assertEqual(parser._count("1200"), 1200)

    def test_a_boolean_is_not_one_token(self):
        # `True` is an int in Python, so a count written as a JSON boolean
        # adds 1 to the day's token total unless something says otherwise.
        # One is not a plausible token count; it is a type confusion showing
        # up as data.
        self.assertEqual(parser._count(True), 0)
        self.assertEqual(parser._count(False), 0)

    def test_a_missing_count_is_zero(self):
        self.assertEqual(parser._count(None), 0)


class TestAPatchEnvelopeWithNoText(unittest.TestCase):
    """`_patched_files`, which is handed whatever the shell command was."""

    def test_the_scanner_still_finds_a_patched_file(self):
        self.assertEqual(
            transcript.patched_files("*** Update File: src/app.py"),
            ["src/app.py"])

    def test_a_command_that_is_not_text_finds_nothing_and_does_not_raise(self):
        # `patch or cmd` at the call site can be None when neither field was
        # written, and `"*** " not in None` is a TypeError that takes the
        # whole session file down with it.
        self.assertEqual(transcript.patched_files(None), [])
        self.assertEqual(transcript.patched_files(""), [])


class TestARealSessionWithNothingWrong(unittest.TestCase):
    """The same claim end to end, because that is where it is read."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="al-nofail-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp,
                        ignore_errors=True)

    def parse(self, records):
        codex_dir = make_codex_dir(self.tmp)
        path = os.path.join(codex_dir, "rollout-2026-08-04-{}.jsonl".format(SID))
        with open(path, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return parser.parse_codex_session(path)

    def test_tool_calls_without_an_exit_code_are_not_errors(self):
        stamp = "2026-08-04T10:00:00.000Z"
        session = self.parse([
            {"timestamp": stamp, "type": "session_meta",
             "payload": {"id": SID, "cwd": CWD, "cli_version": "0.1.0"}},
            {"timestamp": stamp, "type": "event_msg",
             "payload": {"type": "user_message", "message": "read the file"}},
            # A shell call that really did work, so the session has content.
            {"timestamp": stamp, "type": "response_item",
             "payload": {"type": "function_call", "name": "exec_command",
                         "call_id": "c1",
                         "arguments": json.dumps({"cmd": "ls"})}},
            {"timestamp": stamp, "type": "response_item",
             "payload": {"type": "function_call_output", "call_id": "c1",
                         "output": {"output": "app.py\n", "metadata": {"exit_code": 0}}}},
            # And the shapes with nothing to read: no metadata at all, an
            # exit_code that is not a number, and metadata of the wrong type.
            {"timestamp": stamp, "type": "response_item",
             "payload": {"type": "function_call_output", "call_id": "c2",
                         "output": {"output": "contents"}}},
            {"timestamp": stamp, "type": "response_item",
             "payload": {"type": "function_call_output", "call_id": "c3",
                         "output": {"output": "x", "metadata": {"exit_code": "?"}}}},
            {"timestamp": stamp, "type": "response_item",
             "payload": {"type": "function_call_output", "call_id": "c4",
                         "output": {"output": "x", "metadata": "unavailable"}}},
        ])
        self.assertIsNotNone(session, "the session did not parse at all")
        self.assertEqual(
            session["errors"], 0,
            "a tool call that never said how it ended was counted as an "
            "error: {}".format(session["failed_cmds"]))

    def test_a_command_that_really_failed_is_still_counted(self):
        # The vacuity guard for the test above: a parser that had stopped
        # reading exit codes entirely would also report zero errors.
        stamp = "2026-08-04T10:00:00.000Z"
        session = self.parse([
            {"timestamp": stamp, "type": "session_meta",
             "payload": {"id": SID, "cwd": CWD, "cli_version": "0.1.0"}},
            {"timestamp": stamp, "type": "event_msg",
             "payload": {"type": "user_message", "message": "run the tests"}},
            {"timestamp": stamp, "type": "response_item",
             "payload": {"type": "function_call", "name": "exec_command",
                         "call_id": "c1",
                         "arguments": json.dumps({"cmd": "pytest"})}},
            {"timestamp": stamp, "type": "response_item",
             "payload": {"type": "function_call_output", "call_id": "c1",
                         "output": {"output": "1 failed",
                                    "metadata": {"exit_code": 1}}}},
        ])
        self.assertEqual(session["errors"], 1)
        self.assertIn("pytest", " ".join(session["failed_cmds"]))


if __name__ == "__main__":
    unittest.main()
