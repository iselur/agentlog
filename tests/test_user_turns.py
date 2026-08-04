"""What "turns" counts, and what a person would think it counts.

A Claude Code session log writes a `type: "user"` record for three different
things, and only one of them is a person typing:

  1. a person typing;
  2. every tool result, fed back into the loop — the agent's own machinery;
  3. every prompt sent to a subagent, marked `isSidechain: true`.

The parser counted all three.  On 896 real session logs that is 38318 records
against 2314 actual human turns — the reported number is **16.6x** the truth,
and on one session 3637 against 211.

It matters more than a wrong number usually does, because of which way it is
wrong.  An under-count can be caught: add up the sources and see that the
total does not match.  This over-count cannot be caught by anyone, from
anywhere, because there is nothing to compare it against — a person reading
`3637 turns` for a day they typed 211 times has no way to reach the second
number, and the first is not absurd enough to be disbelieved.  It reads as a
long day.

The tool result case is the larger half and the more obviously wrong: a
`tool_result` is the agent feeding itself.  agentwatch already got this half
right, deliberately and with a comment; the parser did not.  The subagent case
is the subtler half: the work is real work and its commands and files still
count — a subagent's `pytest -x` ran and belongs in the session — but the
prompt that started it was written by the agent, not by the person.

The count that is right is the one the label promises: times you said
something.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.parser import parse_claude_session  # noqa: E402

SID = "689e648c-e034-43ab-9783-a72191da648f"
CWD = "/home/you/api"


def spoke(text="fix the tests", ts="2026-08-04T09:00:00.000Z"):
    """A person typing."""
    return {"type": "user", "isSidechain": False, "timestamp": ts,
            "sessionId": SID, "cwd": CWD, "version": "2.1.220",
            "message": {"role": "user", "content": text}}


def spoke_in_blocks(text="fix the tests", ts="2026-08-04T09:00:00.000Z"):
    """The same thing, as a list of content blocks."""
    rec = spoke(text, ts)
    rec["message"]["content"] = [{"type": "text", "text": text}]
    return rec


def tool_result(tool_use_id="t1", is_error=False,
                ts="2026-08-04T09:00:02.000Z", sidechain=False):
    """The agent's own loop feeding itself.  Not a turn."""
    block = {"type": "tool_result", "tool_use_id": tool_use_id,
             "content": "ok"}
    if is_error:
        block["is_error"] = True
    return {"type": "user", "isSidechain": sidechain, "timestamp": ts,
            "sessionId": SID, "cwd": CWD,
            "message": {"role": "user", "content": [block]}}


def subagent_prompt(text="search the repo", ts="2026-08-04T09:00:03.000Z"):
    """A prompt the agent wrote for a subagent.  Not a person typing."""
    rec = spoke(text, ts)
    rec["isSidechain"] = True
    return rec


def ran(cmd="pytest -x", tool_use_id="t1", ts="2026-08-04T09:00:01.000Z",
        sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain, "timestamp": ts,
            "sessionId": SID, "cwd": CWD,
            "message": {"role": "assistant", "id": "msg_" + tool_use_id,
                        "model": "claude-opus-5",
                        "content": [{"type": "tool_use", "id": tool_use_id,
                                     "name": "Bash",
                                     "input": {"command": cmd}}],
                        "usage": {"input_tokens": 10, "output_tokens": 5}}}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="al-turns-")
        self.addCleanup(_rmtree, self.tmp)

    def parsed(self, records):
        d = os.path.join(self.tmp, ".claude", "projects", "-home-you-api")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, SID + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        out = parse_claude_session(path)
        self.assertIsNotNone(out, "the session did not parse at all")
        return out


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class TestAPersonTypingIsATurn(Case):

    def test_one_message_is_one_turn(self):
        s = self.parsed([spoke()])
        self.assertEqual(s["user_turns"], 1)

    def test_content_as_a_list_of_blocks_counts_the_same(self):
        # Both shapes are on disk; the shape must not change the count.
        s = self.parsed([spoke_in_blocks()])
        self.assertEqual(s["user_turns"], 1)

    def test_three_messages_are_three_turns(self):
        s = self.parsed([spoke("a"), spoke("b", "2026-08-04T09:05:00.000Z"),
                         spoke("c", "2026-08-04T09:10:00.000Z")])
        self.assertEqual(s["user_turns"], 3)

    def test_a_turn_is_still_an_event(self):
        s = self.parsed([spoke()])
        self.assertEqual([k for _t, k, _x in s["events"]], ["turn"])


class TestTheAgentFeedingItselfIsNot(Case):
    """The larger half: 19406 of 38318 records on the real logs."""

    def test_a_tool_result_is_not_a_turn(self):
        s = self.parsed([spoke(), ran(), tool_result()])
        self.assertEqual(s["user_turns"], 1)

    def test_a_session_of_nothing_but_tool_results_has_no_turns(self):
        s = self.parsed([ran(), tool_result("t1"),
                         tool_result("t2", ts="2026-08-04T09:00:04.000Z")])
        self.assertEqual(s["user_turns"], 0)

    def test_a_failed_tool_result_is_still_counted_as_an_error(self):
        # Dropping the turn must not drop the failure that rode in with it.
        s = self.parsed([spoke(), ran(), tool_result(is_error=True)])
        self.assertEqual(s["user_turns"], 1)
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["failed_cmds"], ["pytest -x"])

    def test_a_failed_tool_result_does_not_emit_a_turn_event(self):
        s = self.parsed([spoke(), ran(), tool_result(is_error=True)])
        self.assertEqual([k for _t, k, _x in s["events"]],
                         ["turn", "cmd", "error"])


class TestASubagentPromptIsNotAPersonTyping(Case):
    """The subtler half: 16598 records, written by the agent."""

    def test_a_sidechain_prompt_is_not_a_turn(self):
        s = self.parsed([spoke(), subagent_prompt()])
        self.assertEqual(s["user_turns"], 1)

    def test_a_session_of_nothing_but_subagent_prompts_has_no_turns(self):
        s = self.parsed([subagent_prompt("a"),
                         subagent_prompt("b", "2026-08-04T09:00:09.000Z")])
        self.assertEqual(s["user_turns"], 0)

    def test_the_subagents_work_still_counts(self):
        # The commands a subagent ran are commands that ran, in this session,
        # on this machine.  Only the prompt is not a turn.
        s = self.parsed([spoke(), subagent_prompt(),
                         ran("ruff check .", "t9", sidechain=True)])
        self.assertEqual(s["user_turns"], 1)
        self.assertEqual(s["commands"], ["ruff check ."])

    def test_a_subagents_failure_still_counts(self):
        s = self.parsed([spoke(), subagent_prompt(),
                         ran("ruff check .", "t9", sidechain=True),
                         tool_result("t9", is_error=True, sidechain=True)])
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["user_turns"], 1)

    def test_a_sidechain_tool_result_is_not_a_turn_either(self):
        s = self.parsed([spoke(), tool_result(sidechain=True)])
        self.assertEqual(s["user_turns"], 1)


class TestTheFlagIsReadDefensively(Case):
    """Old logs predate the field; a record off disk may say anything."""

    def test_a_record_with_no_sidechain_field_is_a_turn(self):
        # Absent means main thread.  Silence is not a subagent.
        rec = spoke()
        del rec["isSidechain"]
        s = self.parsed([rec])
        self.assertEqual(s["user_turns"], 1)

    def test_a_sidechain_field_that_is_not_a_bool_does_not_drop_the_turn(self):
        # Only an explicit true is a subagent.  Anything else, count it —
        # under-counting turns is the error that can be noticed.
        rec = spoke()
        rec["isSidechain"] = "yes"
        s = self.parsed([rec])
        self.assertEqual(s["user_turns"], 1)

    def test_a_message_that_is_not_a_mapping_is_still_a_turn(self):
        rec = spoke()
        rec["message"] = "fix the tests"
        s = self.parsed([rec])
        self.assertEqual(s["user_turns"], 1)

    def test_content_that_is_neither_string_nor_list_is_still_a_turn(self):
        rec = spoke()
        rec["message"]["content"] = None
        s = self.parsed([rec])
        self.assertEqual(s["user_turns"], 1)

    def test_the_session_metadata_still_comes_off_a_tool_result_record(self):
        # project, version and id were read from user records, including the
        # ones that are no longer turns.  A session whose first user record is
        # a tool result must not lose its project.
        s = self.parsed([ran(), tool_result()])
        self.assertEqual(s["project"], CWD)
        self.assertEqual(s["id"], SID)


class TestTheDigestShowsTheHonestNumber(Case):

    def test_a_realistic_session_reports_what_the_person_did(self):
        # Two things said, eight tool calls, four subagent prompts.  The old
        # count would say 15.
        records = [spoke("first")]
        for i in range(4):
            records.append(ran(f"cmd {i}", f"t{i}",
                               ts=f"2026-08-04T09:0{i}:01.000Z"))
            records.append(tool_result(f"t{i}",
                                       ts=f"2026-08-04T09:0{i}:02.000Z"))
            records.append(subagent_prompt(f"sub {i}",
                                           ts=f"2026-08-04T09:0{i}:03.000Z"))
        records.append(spoke("second", "2026-08-04T09:30:00.000Z"))
        s = self.parsed(records)
        self.assertEqual(s["user_turns"], 2)
        self.assertEqual(len(s["commands"]), 4)


if __name__ == "__main__":
    unittest.main()
