"""A session that patched a file and has nothing to show for it.

``patch_apply_end`` is the right record to read for Codex writes: it names the
files absolutely and it is the only place a patch that *failed* is admitted.
Where it exists it stays authoritative, and nothing here changes that.

But it does not always exist.  Some builds send the patch as a
``custom_tool_call`` and never emit an end record for it at all, and on the
1189 session files this was found with, five sessions patched a file and were
reported as having written nothing — the same blank line a session that only
talked gets.  Five is small; the shape of the mistake is not, and it is the
third one of exactly this kind in this parser.

So the envelope in the call is used as a fallback, and *only* as a fallback:
if the session emitted any ``patch_apply_end`` at all, that build is one that
reports its own patches and the envelopes are ignored.  Reading both would
count patches that never applied as writes, which is the opposite error and
the worse one — a file listed as edited that was not is a report you cannot
check against anything.

The second half of this file is about the error label.  A ``custom_tool_call``
carrying a patch has no ``cmd:`` in it, so when one failed the error was
recorded with an empty name.  The digest drops nameless failures from the
`failed` list while still counting them, so a project would say `4 errors` and
name two of them, with no indication that the other two had names it could not
work out.  Three of the five Codex errors in a real two-day window were that.
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

SID = "019f80fd-314c-7002-a041-000000000001"
CWD = "/home/you/api"
TARGET = "/home/you/api/src/csvparser.py"

# How the envelope actually sits in a real record: one JSON string, with the
# newlines escaped, because it was built as a JavaScript string literal.
ENVELOPE = ("*** Begin Patch\n"
            "*** Update File: " + TARGET + "\n"
            "@@\n"
            "-    return None\n"
            "+    return {}\n"
            "*** End Patch\n")

JS_PATCH = ('const patch = "' + ENVELOPE.replace("\n", "\\n") + '";\n'
            'const r = await tools.apply_patch({input: patch});\n'
            'console.log(r);')


def meta(ts="2026-08-04T09:00:00.000Z"):
    return {"timestamp": ts, "type": "session_meta",
            "payload": {"session_id": SID, "id": SID, "cwd": CWD,
                        "cli_version": "0.144.3", "timestamp": ts}}


def patch_call(body=None, call_id="p1", name="exec",
               ts="2026-08-04T09:00:05.000Z"):
    return {"timestamp": ts, "type": "response_item",
            "payload": {"type": "custom_tool_call", "name": name,
                        "call_id": call_id,
                        "input": JS_PATCH if body is None else body}}


def call_output(output, call_id="p1", ts="2026-08-04T09:00:09.000Z"):
    return {"timestamp": ts, "type": "response_item",
            "payload": {"type": "custom_tool_call_output",
                        "call_id": call_id, "output": output}}


def patch_end(paths, success=True, call_id="zz", ts="2026-08-04T09:00:20.000Z"):
    return {"timestamp": ts, "type": "event_msg",
            "payload": {"type": "patch_apply_end", "call_id": call_id,
                        "success": success, "stdout": "", "stderr": "",
                        "changes": {p: {"type": "update"} for p in paths}}}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="al-patch-fallback-")
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


class TestThePatchIsReadWhenNothingElseReportsIt(Case):

    def test_the_file_is_found_in_the_envelope(self):
        s = self.parsed([meta(), patch_call()])
        self.assertEqual(s["files_written"], [TARGET])

    def test_it_becomes_a_write_event(self):
        s = self.parsed([meta(), patch_call()])
        self.assertEqual([t for _, k, t in s["events"] if k == "write"], [TARGET])

    def test_a_patch_sent_under_its_own_call_name_works_too(self):
        # Some builds name the call `apply_patch` and put the bare envelope in,
        # with no JavaScript around it.
        s = self.parsed([meta(), patch_call(ENVELOPE, name="apply_patch")])
        self.assertEqual(s["files_written"], [TARGET])

    def test_relative_paths_are_resolved_against_the_project(self):
        rel = ENVELOPE.replace(TARGET, "src/csvparser.py")
        s = self.parsed([meta(), patch_call(rel, name="apply_patch")])
        self.assertEqual(s["files_written"], [TARGET])

    def test_adds_and_deletes_count_as_writes_too(self):
        env = ("*** Begin Patch\n*** Add File: /home/you/api/new.py\n"
               "*** Delete File: /home/you/api/old.py\n*** End Patch\n")
        s = self.parsed([meta(), patch_call(env, name="apply_patch")])
        self.assertEqual(sorted(s["files_written"]),
                         ["/home/you/api/new.py", "/home/you/api/old.py"])


class TestTheEndRecordStaysAuthoritative(Case):
    """The fallback must never turn into a second opinion."""

    def test_a_session_that_reports_its_patches_is_not_double_counted(self):
        # Note the end record's call_id does not match the call's: on real logs
        # it almost never does, which is why this cannot be deduplicated per
        # call and has to be decided per session.
        s = self.parsed([meta(), patch_call(), patch_end([TARGET])])
        self.assertEqual(s["files_written"], [TARGET])
        self.assertEqual(s["write_counts"], {TARGET: 1})

    def test_a_patch_that_did_not_apply_is_still_not_a_write(self):
        # The whole reason the end record is preferred.  The envelope names the
        # file either way; only the end record knows it never landed.
        s = self.parsed([meta(), patch_call(), patch_end([TARGET], success=False)])
        self.assertEqual(s["files_written"], [])
        self.assertEqual(s["errors"], 1)

    def test_a_file_only_the_end_record_knows_about_is_not_lost(self):
        other = "/home/you/api/README.md"
        s = self.parsed([meta(), patch_call(), patch_end([other])])
        self.assertEqual(s["files_written"], [other])

    def test_a_snippet_with_no_envelope_writes_nothing(self):
        s = self.parsed([meta(), patch_call(
            'const r = await tools.exec_command({cmd:"pytest -x"});')])
        self.assertEqual(s["files_written"], [])
        self.assertEqual(s["commands"], ["pytest -x"])


class TestAFailedPatchIsNamed(Case):
    """A counted error with no name is a count the reader cannot act on."""

    def test_the_failure_is_labelled_with_the_file(self):
        s = self.parsed([meta(), patch_call(),
                         call_output("Script failed with exit code 1")])
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["failed_cmds"], ["patch csvparser.py"])

    def test_the_event_carries_the_same_label(self):
        s = self.parsed([meta(), patch_call(),
                         call_output("Script failed with exit code 1")])
        self.assertEqual([t for _, k, t in s["events"] if k == "error"],
                         ["patch csvparser.py"])

    def test_a_command_is_still_named_after_the_command(self):
        # The label only fills in where there was nothing; it does not take
        # over from the command name.
        s = self.parsed([meta(),
                         patch_call('await tools.exec_command({cmd:"pytest -x"});'),
                         call_output("Script failed with exit code 1")])
        self.assertEqual(s["failed_cmds"], ["pytest -x"])

    def test_a_failure_with_nothing_to_name_it_after_is_still_counted(self):
        # An honest blank: better a counted error with no name than a guess.
        s = self.parsed([meta(), patch_call("const r = 1;"),
                         call_output("Script failed with exit code 1")])
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["failed_cmds"], [""])


class TestTheDigestNamesWhatFailed(Case):
    """`errors: 4` next to two named failures is the bug this file is about."""

    def test_every_counted_error_that_has_a_name_is_shown(self):
        from agentlog.render import group_by_project
        s = self.parsed([meta(),
                         {"timestamp": "2026-08-04T09:00:01.000Z",
                          "type": "event_msg",
                          "payload": {"type": "user_message", "message": "go"}},
                         patch_call(),
                         call_output("Script failed with exit code 1")])
        group = group_by_project([s])[0]
        self.assertEqual(group["errors"], 1)
        self.assertEqual([name for name, _n in group["top_failed"]],
                         ["patch csvparser.py"])


if __name__ == "__main__":
    unittest.main()
