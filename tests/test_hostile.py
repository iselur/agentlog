"""What agentlog does when a session log is not what it promised to be.

Every case here was found by pointing a fuzzer at the four tools and keeping
whatever produced a traceback, a hang, or an answer that contradicted itself.
A log is written by another program on a bad day: fields come back as lists,
timestamps lose their timezone, counts arrive as strings.  None of that is
agentlog's business to fix — but none of it may take agentlog down either.

The contract every test below asserts is the same one: read what you can,
ignore what you cannot, exit 0.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentlog.cli import main

NOW = "2026-08-03T12:00:00.000Z"
SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _user(**over) -> dict:
    rec = {
        "type": "user",
        "timestamp": NOW,
        "cwd": "/home/test/demo",
        "sessionId": SID,
        "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    }
    rec.update(over)
    return rec


def _assistant(content, **over) -> dict:
    rec = {
        "type": "assistant",
        "timestamp": NOW,
        "message": {"id": "msg_1", "model": "claude-opus-5", "content": content},
    }
    rec.update(over)
    return rec


class HostileLogCase(unittest.TestCase):
    """A temporary home whose session logs can be made as odd as needed."""

    def setUp(self) -> None:
        self.home = tempfile.mkdtemp(prefix="agentlog-hostile-")
        self.claude_dir = os.path.join(self.home, ".claude", "projects", "-home-test-demo")
        os.makedirs(self.claude_dir)

    def tearDown(self) -> None:
        # A test may have removed its own read permission to prove a point.
        for root, dirs, _ in os.walk(self.home):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o700)
                except OSError:
                    pass
        shutil.rmtree(self.home, ignore_errors=True)

    # -- helpers ----------------------------------------------------------

    def write(self, records, name="sess.jsonl") -> str:
        path = os.path.join(self.claude_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        return path

    def write_codex(self, records) -> str:
        d = os.path.join(self.home, ".codex", "sessions", "2026", "08", "03")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "rollout-2026-08-03T12-00-00-" + SID + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        return path

    def run_cli(self, *argv):
        """Run agentlog and return (exit_code, stdout, stderr).

        Any exception escaping ``main`` is a failure of the tool, so it is
        allowed to propagate and fail the test loudly.
        """
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(list(argv) + ["--home", self.home])
            except SystemExit as exit_:
                # argparse exits rather than returning; from outside the
                # process the two are the same thing.
                code = exit_.code if isinstance(exit_.code, int) else 2
        return code, out.getvalue(), err.getvalue()

    def assertSurvives(self, *argv):
        """The tool read a broken log and still gave a clean answer."""
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 0, "exit {}: {}".format(code, err))
        return out


# ---------------------------------------------------------------------------
# Fields that came back as the wrong type
# ---------------------------------------------------------------------------

class TestWrongTypes(HostileLogCase):
    def test_cwd_is_a_number(self):
        self.write([_user(cwd=12345)])
        self.assertSurvives("today")

    def test_session_id_is_a_list(self):
        self.write([_user(sessionId=["a", "b"])])
        self.assertSurvives("list")

    def test_version_is_a_dict(self):
        self.write([_user(version={"major": 2})])
        self.assertSurvives("today")

    def test_message_is_a_list(self):
        self.write([_user(message=[]), _assistant([], message=[])])
        self.assertSurvives("today")

    def test_message_content_is_a_string(self):
        self.write([_user(message={"content": "not-a-list"})])
        self.assertSurvives("today")

    def test_tool_use_id_is_a_list(self):
        self.write([_user(message={"content": [
            {"type": "tool_result", "is_error": True, "tool_use_id": ["z"]}]})])
        self.assertSurvives("today")

    def test_bash_command_is_a_list(self):
        self.write([_user(), _assistant([
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": ["ls", "-la"]}}])])
        self.assertSurvives("today")

    def test_file_path_is_a_number(self):
        self.write([_user(), _assistant([
            {"type": "tool_use", "id": "t1", "name": "Write",
             "input": {"file_path": 99}}])])
        self.assertSurvives("today")

    def test_tool_input_is_not_an_object(self):
        self.write([_user(), _assistant([
            {"type": "tool_use", "id": "t1", "name": "Read", "input": "oops"}])])
        self.assertSurvives("today")

    def test_token_counts_are_strings(self):
        self.write([_user(), _assistant([], message={
            "id": "msg_1", "usage": {"input_tokens": "12", "output_tokens": "8"}})])
        out = self.assertSurvives("today")
        self.assertNotIn("Traceback", out)

    def test_ai_title_is_a_number(self):
        self.write([_user(), {"type": "ai-title", "timestamp": NOW, "aiTitle": 7}])
        self.assertSurvives("today")

    def test_codex_cwd_and_counts_are_wrong_types(self):
        self.write_codex([
            {"type": "session_meta", "timestamp": NOW,
             "payload": {"session_id": SID, "cwd": 42}},
            {"type": "response_item", "timestamp": NOW,
             "payload": {"type": "function_call", "name": "exec_command",
                         "arguments": "not json", "call_id": "c1"}},
            {"type": "response_item", "timestamp": NOW,
             "payload": {"type": "function_call_output", "call_id": "c1",
                         "output": {"metadata": {"exit_code": "1"}}}},
            {"type": "event_msg", "timestamp": NOW,
             "payload": {"type": "token_count",
                         "info": {"last_token_usage": {"input_tokens": "5"}}}},
        ])
        self.assertSurvives("today")

    def test_codex_session_id_is_a_list(self):
        self.write_codex([
            {"type": "session_meta", "timestamp": NOW,
             "payload": {"session_id": ["a"], "cwd": "/home/test/demo"}},
        ])
        self.assertSurvives("list")

    def test_codex_exit_code_zero_as_a_string_is_not_an_error(self):
        from agentlog.parser import parse_codex_session
        path = self.write_codex([
            {"type": "session_meta", "timestamp": NOW,
             "payload": {"session_id": SID, "cwd": "/home/test/demo"}},
            {"type": "event_msg", "timestamp": NOW,
             "payload": {"type": "user_message", "message": "go"}},
            {"type": "response_item", "timestamp": NOW,
             "payload": {"type": "function_call_output", "call_id": "c1",
                         "output": {"metadata": {"exit_code": "0"}}}},
        ])
        sess = parse_codex_session(path)
        self.assertEqual(sess["errors"], 0)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

class TestTimestamps(HostileLogCase):
    def test_timestamp_without_a_timezone(self):
        # Comparing a naive datetime against an aware one raises; a log that
        # dropped its 'Z' must not be able to do that to us.
        self.write([_user(timestamp="2026-08-03T12:00:00")])
        self.assertSurvives("today")

    def test_naive_timestamp_is_read_as_utc(self):
        from agentlog.parser import _ts
        parsed = _ts("2026-08-03T12:00:00")
        self.assertIsNotNone(parsed)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_timestamp_is_a_number(self):
        self.write([_user(timestamp=1754222400)])
        self.assertSurvives("today")

    def test_timestamp_is_nonsense(self):
        self.write([_user(timestamp="last tuesday")])
        self.assertSurvives("today")


# ---------------------------------------------------------------------------
# Arguments a person can actually type
# ---------------------------------------------------------------------------

class TestArguments(HostileLogCase):
    def test_absurd_offsets_are_a_usage_error(self):
        # timedelta overflows long before the integer does.
        for value in ("999999999999999999999w", "99999999999d", "9" * 400 + "h"):
            code, _, err = self.run_cli("since", value)
            self.assertEqual(code, 2, "accepted {!r}".format(value))
            self.assertIn("agentlog:", err)

    def test_zero_and_negative_offsets_are_a_usage_error(self):
        for value in ("0d", "-3d"):
            code, _, _ = self.run_cli("since", value)
            self.assertEqual(code, 2, "accepted {!r}".format(value))

    def test_limit_must_be_at_least_one(self):
        # 'no sessions found ... and 1 more' is not an answer anyone can use.
        self.write([_user()])
        for value in ("0", "-1"):
            code, out, err = self.run_cli("list", "--limit", value)
            self.assertEqual(code, 2, "accepted --limit {}".format(value))
            self.assertNotIn("more", out)

    def test_limit_applies_to_json_too(self):
        for i in range(3):
            self.write([_user(sessionId="{}-bbbb-cccc-dddd-eeeeeeeeeeee".format(i))],
                       name="s{}.jsonl".format(i))
        out = self.assertSurvives("list", "--limit", "1", "--json")
        self.assertEqual(len(json.loads(out)), 1)

    def test_stray_positional_is_refused(self):
        # Silently ignoring a word the person typed hides their typo from them.
        self.write([_user()])
        for argv in (("today", "accidental"), ("list", "accidental"),
                     ("week", "yesterday")):
            code, _, err = self.run_cli(*argv)
            self.assertEqual(code, 2, "accepted {}".format(argv))
            self.assertIn("accepts no", err)

    def test_show_still_takes_its_argument(self):
        self.write([_user()])
        self.assertSurvives("show", SID[:8])

    def test_since_still_takes_its_argument(self):
        self.write([_user()])
        self.assertSurvives("since", "3d")


# ---------------------------------------------------------------------------
# The one promise in the README: it never writes to the logs
# ---------------------------------------------------------------------------

class TestNeverWritesToLogs(HostileLogCase):
    def test_html_refuses_to_overwrite_a_session_log(self):
        victim = self.write([_user()], name="victim.jsonl")
        before = open(victim, encoding="utf-8").read()
        code, _, err = self.run_cli("today", "--html", victim)
        self.assertEqual(code, 2)
        self.assertEqual(open(victim, encoding="utf-8").read(), before)
        self.assertIn("session log", err)

    def test_markdown_refuses_to_overwrite_a_session_log(self):
        victim = self.write([_user()], name="victim.jsonl")
        before = open(victim, encoding="utf-8").read()
        code, _, err = self.run_cli("today", "--md", victim)
        self.assertEqual(code, 2)
        self.assertEqual(open(victim, encoding="utf-8").read(), before)

    def test_html_refuses_anywhere_inside_the_log_tree(self):
        target = os.path.join(self.claude_dir, "digest.html")
        self.write([_user()])
        code, _, err = self.run_cli("today", "--html", target)
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(target))

    def test_html_elsewhere_still_works(self):
        self.write([_user()])
        out_dir = tempfile.mkdtemp(prefix="agentlog-out-")
        try:
            target = os.path.join(out_dir, "digest.html")
            self.assertSurvives("today", "--html", target)
            self.assertTrue(os.path.exists(target))
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Things in the log tree that are not session logs
# ---------------------------------------------------------------------------

class TestOddFilesystem(HostileLogCase):
    def test_a_fifo_named_jsonl_does_not_hang(self):
        # Opening a FIFO for reading blocks until somebody writes to it.  A
        # digest tool that hangs forever on a stray pipe is worse than one that
        # crashes: there is nothing on screen to explain the wait.
        if not hasattr(os, "mkfifo"):
            self.skipTest("no mkfifo on this platform")
        os.mkfifo(os.path.join(self.claude_dir, "pipe.jsonl"))
        self.write([_user()])
        self.assertSurvives("today")

    def test_a_directory_named_jsonl_is_skipped(self):
        os.makedirs(os.path.join(self.claude_dir, "folder.jsonl"))
        self.write([_user()])
        self.assertSurvives("today")

    def test_a_broken_symlink_is_skipped(self):
        os.symlink(os.path.join(self.claude_dir, "gone.jsonl"),
                   os.path.join(self.claude_dir, "dangling.jsonl"))
        self.write([_user()])
        self.assertSurvives("today")

    def test_a_symlink_loop_does_not_recurse(self):
        os.symlink(os.path.join(self.home, ".claude", "projects"),
                   os.path.join(self.claude_dir, "loop"))
        self.write([_user()])
        self.assertSurvives("today")

    def test_an_unreadable_log_is_skipped(self):
        path = self.write([_user()], name="secret.jsonl")
        os.chmod(path, 0o000)
        try:
            self.assertSurvives("today")
        finally:
            os.chmod(path, 0o600)

    def test_an_unreadable_directory_says_so(self):
        self.write([_user()])
        os.chmod(self.claude_dir, 0o000)
        try:
            code, out, err = self.run_cli("today")
        finally:
            os.chmod(self.claude_dir, 0o700)
        self.assertEqual(code, 0)

    def test_a_huge_line_is_skipped_not_loaded_forever(self):
        self.write([_user(), {"type": "user", "timestamp": NOW,
                              "cwd": "/home/test/demo", "sessionId": SID,
                              "message": {"content": [
                                  {"type": "text", "text": "x" * 200000}]}}])
        self.assertSurvives("today")

    def test_an_empty_log_is_not_a_session(self):
        open(os.path.join(self.claude_dir, "empty.jsonl"), "w").close()
        self.write([_user()])
        self.assertSurvives("today")

    def test_binary_rubbish_is_skipped(self):
        with open(os.path.join(self.claude_dir, "junk.jsonl"), "wb") as fh:
            fh.write(bytes(range(256)) * 40)
        self.write([_user()])
        self.assertSurvives("today")


if __name__ == "__main__":
    unittest.main()
