"""The shape current Codex actually writes to disk.

Codex used to announce work as a ``function_call`` named ``exec_command`` or
``apply_patch``, with the command sitting in a structured ``arguments`` field.
The parser reads that shape and nothing else.  Current Codex builds send a
``custom_tool_call`` instead: the call carries a snippet of JavaScript, and the
command has to be read back out of it.

Counted over the 1189 session files on the machine this was found on, 6166 of
the 9396 tool calls are the new shape and were invisible: 65.6% of all the work
recorded, and 74% of the sessions with any work in them showed *none* of it.
For the current month it was 98%.  agentlog did not fail on those sessions.  It
printed `2 sessions · 1 claude, 1 codex` and a project line with no commands
and no files under it — the same thing it prints for a session where the agent
genuinely did nothing but talk.

That is this project's recurring bug, in its worst spot yet: a total computed
from fewer inputs than exist, printed as though it were complete.  Here the
missing inputs are most of them.

agentwatch, reading the same files, has parsed this shape from the start — so
the two tools in one family disagreed about the same log, and the disagreement
was silent in the direction that under-reports.

Three record types make up the new shape, and all three are needed for a
session to come out right:

  custom_tool_call         the JavaScript, carrying one or more commands
  patch_apply_end          which files a patch actually changed, absolutely
  custom_tool_call_output  whether the script failed

The fixtures below are trimmed copies of real records.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.parser import parse_codex_session  # noqa: E402

SID = "4ef1361b-07e4-4bc9-bb29-1783b761d677"
CWD = "/home/you/api"


def meta(ts="2026-08-04T09:00:00.000Z"):
    return {"timestamp": ts, "type": "session_meta",
            "payload": {"session_id": SID, "id": SID, "cwd": CWD,
                        "cli_version": "0.55.0", "timestamp": ts}}


def script(input_js, call_id="exec-1", ts="2026-08-04T09:00:05.000Z"):
    """A ``custom_tool_call`` — how current Codex runs everything."""
    return {"timestamp": ts, "type": "response_item",
            "payload": {"type": "custom_tool_call", "name": "exec",
                        "call_id": call_id, "input": input_js}}


def script_result(output, call_id="exec-1", ts="2026-08-04T09:00:09.000Z"):
    return {"timestamp": ts, "type": "response_item",
            "payload": {"type": "custom_tool_call_output",
                        "call_id": call_id, "output": output}}


def patch_end(changes, success=True, call_id="exec-2",
              ts="2026-08-04T09:00:20.000Z"):
    """``patch_apply_end`` — the only record that says which files changed."""
    listed = "".join("A %s\n" % p for p in changes)
    return {"timestamp": ts, "type": "event_msg",
            "payload": {"type": "patch_apply_end", "call_id": call_id,
                        "stdout": ("Success. Updated the following files:\n"
                                   + listed) if success else "",
                        "stderr": "" if success else "patch failed",
                        "success": success,
                        "changes": {p: {"type": "update"} for p in changes}}}


# One command, the plainest form real logs contain.
ONE = ('const r = await tools.exec_command({cmd:"pytest -x",'
       'workdir:"/home/you/api",yield_time_ms:10000,max_output_tokens:12000});'
       '\nconsole.log(r);')

# Several in one snippet, which is the common form: a Promise.all of calls.
# The old shape was one command per record, so nothing in the parser was ever
# built to find more than one.
MANY = ('const r = await Promise.all([\n'
        '  tools.exec_command({cmd:"git status --short",'
        'workdir:"/home/you/api",yield_time_ms:10000}),\n'
        '  tools.exec_command({cmd:"pytest -x",'
        'workdir:"/home/you/api",yield_time_ms:10000}),\n'
        ']);\nconsole.log(r);')

# An escaped quote inside the command, which a naive scan for the next `"`
# would cut in half.
ESCAPED = ('const r = await tools.exec_command({cmd:"rg -n \\"def main\\" '
           'src/app.py",workdir:"/home/you/api"});')


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="al-codex-script-")
        self.addCleanup(_rmtree, self.tmp)

    def session(self, records, name=None):
        d = os.path.join(self.tmp, ".codex", "sessions", "2026", "08", "04")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(
            d, name or ("rollout-2026-08-04T09-00-00-" + SID + ".jsonl"))
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        return path

    def parsed(self, records):
        out = parse_codex_session(self.session(records))
        self.assertIsNotNone(out, "the session did not parse at all")
        return out


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class TestCommandsInAScriptCall(Case):

    def test_the_one_command_in_a_snippet_is_found(self):
        s = self.parsed([meta(), script(ONE)])
        self.assertEqual(s["commands"], ["pytest -x"])

    def test_every_command_in_a_snippet_is_found(self):
        # Not just the first: a Promise.all of four calls is four commands,
        # and reporting one of them is the under-count in miniature.
        s = self.parsed([meta(), script(MANY)])
        self.assertEqual(s["commands"], ["git status --short", "pytest -x"])

    def test_an_escaped_quote_does_not_truncate_the_command(self):
        s = self.parsed([meta(), script(ESCAPED)])
        self.assertEqual(s["commands"], ['rg -n "def main" src/app.py'])

    def test_they_become_events_in_order(self):
        s = self.parsed([meta(), script(MANY)])
        cmds = [text for _, kind, text in s["events"] if kind == "cmd"]
        self.assertEqual(cmds, ["git status --short", "pytest -x"])

    def test_the_old_shape_still_works(self):
        # The new shape is added beside the old one, not in place of it:
        # months of sessions on disk are still the old shape.
        old = {"timestamp": "2026-08-04T09:00:05.000Z", "type": "response_item",
               "payload": {"type": "function_call", "name": "exec_command",
                           "call_id": "fc1",
                           "arguments": json.dumps({"cmd": "make test"})}}
        s = self.parsed([meta(), old])
        self.assertEqual(s["commands"], ["make test"])

    def test_both_shapes_in_one_session_are_both_counted(self):
        old = {"timestamp": "2026-08-04T09:00:03.000Z", "type": "response_item",
               "payload": {"type": "function_call", "name": "exec_command",
                           "call_id": "fc1",
                           "arguments": json.dumps({"cmd": "make test"})}}
        s = self.parsed([meta(), old, script(ONE)])
        self.assertEqual(sorted(s["commands"]), ["make test", "pytest -x"])

    def test_a_snippet_with_no_command_in_it_adds_nothing(self):
        # Not every script runs something — and a parser that guessed here
        # would trade an under-count for an over-count.
        s = self.parsed([meta(), script("const r = 1 + 1;\nconsole.log(r);")])
        self.assertEqual(s["commands"], [])

    def test_a_malformed_snippet_does_not_raise(self):
        for bad in ("", None, 42, [], '{"cmd": unterminated',
                    'tools.exec_command({cmd:"'):
            with self.subTest(input=bad):
                s = self.parsed([meta(), script(bad)])
                self.assertIsInstance(s["commands"], list)


class TestFilesWrittenByAPatch(Case):

    PATHS = ["/home/you/api/src/app.py", "/home/you/api/README.md"]

    def test_patch_apply_end_names_the_files(self):
        s = self.parsed([meta(), patch_end(self.PATHS)])
        self.assertEqual(sorted(s["files_written"]), sorted(self.PATHS))

    def test_they_become_write_events(self):
        s = self.parsed([meta(), patch_end(self.PATHS)])
        writes = sorted(t for _, k, t in s["events"] if k == "write")
        self.assertEqual(writes, sorted(self.PATHS))

    def test_a_patch_that_did_not_apply_is_not_a_write(self):
        # The record is the only place a failed patch is admitted.  Counting
        # it would be the opposite mistake: reporting an edit that never
        # reached the disk.
        s = self.parsed([meta(), patch_end(self.PATHS, success=False)])
        self.assertEqual(s["files_written"], [])

    def test_a_patch_that_did_not_apply_is_an_error(self):
        s = self.parsed([meta(), patch_end(self.PATHS, success=False)])
        self.assertEqual(s["errors"], 1)

    def test_the_same_file_patched_twice_is_listed_once(self):
        s = self.parsed([meta(),
                         patch_end(self.PATHS[:1], call_id="a"),
                         patch_end(self.PATHS[:1], call_id="b",
                                   ts="2026-08-04T09:05:00.000Z")])
        self.assertEqual(s["files_written"], self.PATHS[:1])

    def test_no_changes_dict_is_not_a_crash(self):
        rec = patch_end([])
        rec["payload"].pop("changes")
        s = self.parsed([meta(), rec])
        self.assertEqual(s["files_written"], [])


class TestAScriptThatFailed(Case):

    def test_a_failed_script_is_an_error(self):
        s = self.parsed([meta(), script(ONE),
                         script_result("Script failed with exit code 1\n...")])
        self.assertEqual(s["errors"], 1)

    def test_the_error_is_named_after_the_command(self):
        s = self.parsed([meta(), script(ONE),
                         script_result("Script failed with exit code 1")])
        errs = [t for _, k, t in s["events"] if k == "error"]
        self.assertEqual(errs, ["pytest -x"])

    def test_a_script_that_completed_is_not_an_error(self):
        s = self.parsed([meta(), script(ONE),
                         script_result("Script completed\nok")])
        self.assertEqual(s["errors"], 0)

    def test_a_list_shaped_output_is_read_too(self):
        # Some builds wrap the output in content blocks rather than a string.
        s = self.parsed([meta(), script(ONE),
                         script_result([{"type": "text",
                                         "text": "Script failed: boom"}])])
        self.assertEqual(s["errors"], 1)


class TestTheDigestStopsUnderReporting(Case):
    """End to end, because the count in the digest is what a user reads."""

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.tmp, *argv],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))

    def a_full_session(self):
        return [meta(),
                {"timestamp": "2026-08-04T09:00:01.000Z", "type": "event_msg",
                 "payload": {"type": "user_message", "message": "do it"}},
                script(MANY),
                patch_end(["/home/you/api/src/app.py"])]

    def test_show_lists_the_commands_and_the_file(self):
        self.session(self.a_full_session())
        p = self.run_cli("show", SID[:8])
        self.assertIn("pytest -x", p.stdout, p.stdout + p.stderr)
        self.assertIn("git status --short", p.stdout, p.stdout + p.stderr)
        self.assertIn("src/app.py", p.stdout, p.stdout + p.stderr)

    def test_the_json_counts_match_what_happened(self):
        self.session(self.a_full_session())
        p = self.run_cli("since", "3650d", "--json")
        blob = json.loads(p.stdout)
        found = json.dumps(blob)
        self.assertIn("pytest -x", found, found[:2000])
        self.assertIn("src/app.py", found, found[:2000])

    def test_a_session_of_pure_talk_still_reads_as_empty(self):
        # The other side of the same coin: this fix must not invent activity
        # where a session really had none.
        self.session([meta(),
                      {"timestamp": "2026-08-04T09:00:01.000Z",
                       "type": "event_msg",
                       "payload": {"type": "user_message", "message": "hi"}}])
        s = parse_codex_session(os.path.join(
            self.tmp, ".codex", "sessions", "2026", "08", "04",
            "rollout-2026-08-04T09-00-00-" + SID + ".jsonl"))
        self.assertEqual(s["commands"], [])
        self.assertEqual(s["files_written"], [])


if __name__ == "__main__":
    unittest.main()
