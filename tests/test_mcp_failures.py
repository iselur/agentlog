"""A session that says `0 errors` and had failures in it.

Codex reports MCP tool calls in their own record, ``mcp_tool_call_end``, whose
``result`` is either ``{"Ok": ...}`` or ``{"Err": "..."}``.  Nothing read that
record, so an MCP call that failed was not an error, was not counted, and had no
name.  On the 1189 session files this was found with, six calls failed across
four sessions, and all four of those sessions reported ``0 errors``.

The count is small.  What it says is not: `0 errors` is a claim, not a partial
tally, and a reader has no way to tell a session that had no failures from one
whose failures were in a record the parser does not open.  Every other kind of
failure Codex reports — a command exiting non-zero, a patch that would not
apply — is counted, and this one was reported in exactly the same place, one
payload type away.

The failures were all real: `resources/read failed: unknown MCP server
'workspace'`, from a server that was named in the config and not running.  That
is the kind of thing a daily digest exists to surface.

Successful MCP calls are deliberately *not* turned into commands.  An MCP call
is not a shell command and the `commands` list has one meaning; counting them
there would trade a missing error for a wrong command count.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.parser import parse_codex_session  # noqa: E402

SID = "019fb76f-aad2-7851-b9d9-1db395a63dc3"
CWD = "/home/you/api"


def meta(ts="2026-08-04T09:00:00.000Z"):
    return {"timestamp": ts, "type": "session_meta",
            "payload": {"session_id": SID, "id": SID, "cwd": CWD,
                        "cli_version": "0.144.3", "timestamp": ts}}


def turn(ts="2026-08-04T09:00:01.000Z"):
    return {"timestamp": ts, "type": "event_msg",
            "payload": {"type": "user_message", "message": "go"}}


def mcp(result, server="workspace", tool="read_mcp_resource",
        ts="2026-08-04T09:00:05.000Z", call_id="call_1"):
    """One MCP call as Codex records it, in the shape found on real logs."""
    return {"timestamp": ts, "type": "event_msg",
            "payload": {"type": "mcp_tool_call_end", "call_id": call_id,
                        "invocation": {"server": server, "tool": tool,
                                       "arguments": {"uri": "file:///x.py"}},
                        "duration": {"secs": 0, "nanos": 16140},
                        "result": result}}


ERR = {"Err": "resources/read failed: unknown MCP server 'workspace'"}
OK = {"Ok": {"content": [{"type": "text", "text": "..."}]}}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="al-mcp-")
        self.addCleanup(_rmtree, self.tmp)

    def parsed(self, records):
        d = os.path.join(self.tmp, ".codex", "sessions", "2026", "08", "04")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "rollout-2026-08-04T09-00-00-" + SID + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        out = parse_codex_session(path)
        self.assertIsNotNone(out, "the session did not parse at all")
        return out


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class TestAFailedMcpCallIsAnError(Case):

    def test_it_is_counted(self):
        s = self.parsed([meta(), turn(), mcp(ERR)])
        self.assertEqual(s["errors"], 1)

    def test_it_is_named_after_the_tool_that_failed(self):
        # The server and the tool are both in the record, and a reader needs
        # both: `read_mcp_resource` alone does not say which server was down.
        s = self.parsed([meta(), turn(), mcp(ERR)])
        self.assertEqual(s["failed_cmds"], ["mcp workspace/read_mcp_resource"])

    def test_it_becomes_an_error_event(self):
        s = self.parsed([meta(), turn(), mcp(ERR)])
        self.assertEqual([t for _, k, t in s["events"] if k == "error"],
                         ["mcp workspace/read_mcp_resource"])

    def test_each_failure_counts_once(self):
        s = self.parsed([meta(), turn(),
                         mcp(ERR, call_id="a"),
                         mcp(ERR, server="filesystem", call_id="b")])
        self.assertEqual(s["errors"], 2)
        self.assertEqual(sorted(s["failed_cmds"]),
                         ["mcp filesystem/read_mcp_resource",
                          "mcp workspace/read_mcp_resource"])

    def test_a_failure_alongside_a_failing_command_adds_up(self):
        # The two kinds of failure are counted in different branches; neither
        # may swallow the other.
        s = self.parsed([
            meta(), turn(), mcp(ERR),
            {"timestamp": "2026-08-04T09:00:06.000Z", "type": "response_item",
             "payload": {"type": "custom_tool_call", "name": "exec",
                         "call_id": "c1",
                         "input": 'await tools.exec_command({cmd:"pytest -x"});'}},
            {"timestamp": "2026-08-04T09:00:07.000Z", "type": "response_item",
             "payload": {"type": "custom_tool_call_output", "call_id": "c1",
                         "output": "Script failed with exit code 1"}}])
        self.assertEqual(s["errors"], 2)
        self.assertEqual(sorted(s["failed_cmds"]),
                         ["mcp workspace/read_mcp_resource", "pytest -x"])


class TestASuccessfulCallIsNotAFailure(Case):
    """The half that keeps this from becoming an over-count."""

    def test_an_ok_result_is_not_an_error(self):
        s = self.parsed([meta(), turn(), mcp(OK)])
        self.assertEqual(s["errors"], 0)
        self.assertEqual(s["failed_cmds"], [])

    def test_an_ok_call_does_not_become_a_command(self):
        # An MCP call is not a shell command.  `commands` means one thing.
        s = self.parsed([meta(), turn(), mcp(OK)])
        self.assertEqual(s["commands"], [])

    def test_a_failed_call_does_not_become_a_command_either(self):
        s = self.parsed([meta(), turn(), mcp(ERR)])
        self.assertEqual(s["commands"], [])

    def test_a_call_with_no_result_at_all_is_not_guessed_at(self):
        # A truncated or future record.  Silence is not failure.
        rec = mcp(OK)
        del rec["payload"]["result"]
        s = self.parsed([meta(), turn(), rec])
        self.assertEqual(s["errors"], 0)

    def test_a_result_that_is_not_a_mapping_is_not_a_failure(self):
        s = self.parsed([meta(), turn(), mcp("done")])
        self.assertEqual(s["errors"], 0)


class TestTheRecordIsReadDefensively(Case):
    """It comes off disk, so every field in it is optional."""

    def test_a_missing_invocation_still_counts_the_error(self):
        # Better a counted failure with a plain name than a dropped one.
        rec = mcp(ERR)
        del rec["payload"]["invocation"]
        s = self.parsed([meta(), turn(), rec])
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["failed_cmds"], ["mcp call failed"])

    def test_a_tool_with_no_server_is_named_by_its_tool(self):
        rec = mcp(ERR)
        del rec["payload"]["invocation"]["server"]
        s = self.parsed([meta(), turn(), rec])
        self.assertEqual(s["failed_cmds"], ["mcp read_mcp_resource"])

    def test_an_invocation_that_is_not_a_mapping_does_not_raise(self):
        rec = mcp(ERR)
        rec["payload"]["invocation"] = "workspace.read"
        s = self.parsed([meta(), turn(), rec])
        self.assertEqual(s["errors"], 1)

    def test_a_session_of_nothing_but_a_failed_call_is_still_reported(self):
        # It has a turn in it, so it is a session; the failure is the only
        # thing that happened and is the whole reason to show it.
        s = self.parsed([meta(), turn(), mcp(ERR)])
        self.assertEqual(s["user_turns"], 1)
        self.assertEqual(s["errors"], 1)


class TestTheDigestShowsIt(Case):

    def test_the_failure_reaches_the_rendered_group(self):
        from agentlog.render import group_by_project
        s = self.parsed([meta(), turn(), mcp(ERR)])
        group = group_by_project([s])[0]
        self.assertEqual(group["errors"], 1)
        self.assertEqual([name for name, _n in group["top_failed"]],
                         ["mcp workspace/read_mcp_resource"])


if __name__ == "__main__":
    unittest.main()
