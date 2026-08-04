"""Codex parallel workers share one session ID, and share it honestly.

When Codex fans a turn out to worker agents, every worker writes its own
rollout file and all of them carry the same ``session_id``.  They are one
session, so collapsing them to one row is right.  Keeping the richest file and
throwing the others away is not: the discarded workers did real work, on
different files, with different commands.

Across the 1147 Codex session IDs on the machine this was found on, 21 had more
than one file — 42 files were being discarded, and 38 of those 42 contained
commands the kept file did not have.  Inside those sessions 299 of 616 commands
went missing, 49% of them.  No file on disk was a byte-for-byte copy of
another: every one was a distinct worker.

The docstring on ``find_sessions`` already states the rule this broke —

    the caller is expected to say so, because a report computed from fewer
    files than are on disk looks exactly like a complete one

— and the dedup sat directly beneath it, doing exactly that, silently.

So the fix is to merge rather than to choose.  Which means the interesting
tests here are the ones about *not* double-counting: a merge that summed
everything blindly would trade an under-count for an over-count, and the second
is worse, because an over-count cannot be spotted by looking at the source
files and adding up.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.parser import find_sessions  # noqa: E402

SID = "019fc384-1111-2222-3333-444455556666"
CWD = "/home/you/api"


def worker(commands, paths=(), turns=1, start="09:00:00", end="09:05:00",
           tokens=(100, 50), errors=(), session_id=SID):
    """One worker's rollout file, in the shape current Codex writes.

    The ID goes in the record, not just in the file name: that is where the
    parser reads it from, and a fixture that only renamed the file would look
    like two sessions to the test and be one to the code.
    """
    recs = [{"timestamp": "2026-08-04T%s.000Z" % start, "type": "session_meta",
             "payload": {"session_id": session_id, "id": session_id, "cwd": CWD,
                         "cli_version": "0.55.0",
                         "timestamp": "2026-08-04T%s.000Z" % start}}]
    for i in range(turns):
        recs.append({"timestamp": "2026-08-04T%s.000Z" % start,
                     "type": "event_msg",
                     "payload": {"type": "user_message", "message": "go"}})
    for i, cmd in enumerate(commands):
        recs.append({"timestamp": "2026-08-04T%s.000Z" % start,
                     "type": "response_item",
                     "payload": {"type": "custom_tool_call", "name": "exec",
                                 "call_id": "c%d" % i,
                                 "input": 'await tools.exec_command({cmd:"%s",'
                                          'workdir:"%s"});' % (cmd, CWD)}})
    for i, cmd in enumerate(errors):
        recs.append({"timestamp": "2026-08-04T%s.000Z" % start,
                     "type": "response_item",
                     "payload": {"type": "custom_tool_call", "name": "exec",
                                 "call_id": "e%d" % i,
                                 "input": 'await tools.exec_command({cmd:"%s",'
                                          'workdir:"%s"});' % (cmd, CWD)}})
        recs.append({"timestamp": "2026-08-04T%s.000Z" % start,
                     "type": "response_item",
                     "payload": {"type": "custom_tool_call_output",
                                 "call_id": "e%d" % i,
                                 "output": "Script failed with exit code 1"}})
    if paths:
        recs.append({"timestamp": "2026-08-04T%s.000Z" % end,
                     "type": "event_msg",
                     "payload": {"type": "patch_apply_end", "call_id": "p1",
                                 "success": True, "stdout": "", "stderr": "",
                                 "changes": {p: {"type": "update"}
                                             for p in paths}}})
    recs.append({"timestamp": "2026-08-04T%s.000Z" % end, "type": "event_msg",
                 "payload": {"type": "token_count",
                             "info": {"last_token_usage": {
                                 "input_tokens": tokens[0],
                                 "output_tokens": tokens[1]}}}})
    return recs


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="al-workers-")
        self.addCleanup(_rmtree, self.tmp)
        self.dir = os.path.join(self.tmp, ".codex", "sessions", "2026", "08", "04")
        os.makedirs(self.dir)
        self.n = 0

    def add(self, records, session_id=SID):
        self.n += 1
        path = os.path.join(
            self.dir, "rollout-2026-08-04T09-0%d-00-%s.jsonl" % (self.n, session_id))
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        return path

    def sessions(self):
        found, _sources, _unusable = find_sessions(self.tmp)
        return found


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class TestWorkersAreMergedNotDiscarded(Case):

    def three_workers(self):
        self.add(worker(["make lint", "make test"],
                        paths=["/home/you/api/a.py"]))
        self.add(worker(["pytest -x", "git status"],
                        paths=["/home/you/api/b.py"]))
        self.add(worker(["ruff check"], paths=["/home/you/api/c.py"]))

    def test_they_are_still_one_session(self):
        # The ID collision is real — collapsing to one row was never the bug.
        self.three_workers()
        self.assertEqual(len(self.sessions()), 1)

    def test_every_workers_commands_survive(self):
        self.three_workers()
        s = self.sessions()[0]
        self.assertEqual(sorted(s["commands"]),
                         ["git status", "make lint", "make test", "pytest -x",
                          "ruff check"])

    def test_every_workers_files_survive(self):
        self.three_workers()
        s = self.sessions()[0]
        self.assertEqual(sorted(s["files_written"]),
                         ["/home/you/api/a.py", "/home/you/api/b.py",
                          "/home/you/api/c.py"])

    def test_the_events_are_all_there_and_in_order(self):
        self.three_workers()
        s = self.sessions()[0]
        stamps = [e[0] for e in s["events"]]
        self.assertEqual(stamps, sorted(stamps), "events came back unordered")
        cmds = [t for _, k, t in s["events"] if k == "cmd"]
        self.assertEqual(len(cmds), 5)

    def test_turns_are_summed(self):
        self.add(worker(["a"], turns=2))
        self.add(worker(["b"], turns=3))
        self.assertEqual(self.sessions()[0]["user_turns"], 5)

    def test_errors_are_summed(self):
        self.add(worker([], errors=["false"]))
        self.add(worker([], errors=["exit 1", "no-such-cmd"]))
        self.assertEqual(self.sessions()[0]["errors"], 3)

    def test_the_failing_commands_are_all_named(self):
        self.add(worker([], errors=["false"]))
        self.add(worker([], errors=["no-such-cmd"]))
        self.assertEqual(sorted(self.sessions()[0]["failed_cmds"]),
                         ["false", "no-such-cmd"])

    def test_tokens_are_summed(self):
        # Each worker has its own usage; the session spent all of it.
        self.add(worker(["a"], tokens=(100, 50)))
        self.add(worker(["b"], tokens=(300, 70)))
        s = self.sessions()[0]
        self.assertEqual((s["tokens_in"], s["tokens_out"]), (400, 120))

    def test_the_span_covers_all_of_them(self):
        self.add(worker(["a"], start="09:00:00", end="09:05:00"))
        self.add(worker(["b"], start="09:02:00", end="09:40:00"))
        s = self.sessions()[0]
        self.assertEqual(s["start"].strftime("%H:%M:%S"), "09:00:00")
        self.assertEqual(s["end"].strftime("%H:%M:%S"), "09:40:00")
        self.assertEqual(s["duration_s"], 40 * 60)

    def test_write_counts_add_up_per_file(self):
        self.add(worker([], paths=["/home/you/api/a.py"]))
        self.add(worker([], paths=["/home/you/api/a.py"]))
        self.assertEqual(self.sessions()[0]["write_counts"],
                         {"/home/you/api/a.py": 2})


class TestTheMergeDoesNotInvent(Case):
    """An over-count is the worse mistake: it cannot be checked by hand."""

    def test_the_same_command_in_two_workers_is_listed_once(self):
        # `commands` is a list of distinct commands, as it always was within
        # one file.  Merging must not change what the list means.
        self.add(worker(["pytest -x"]))
        self.add(worker(["pytest -x"]))
        self.assertEqual(self.sessions()[0]["commands"], ["pytest -x"])

    def test_the_same_file_in_two_workers_is_listed_once(self):
        self.add(worker([], paths=["/home/you/api/a.py"]))
        self.add(worker([], paths=["/home/you/api/a.py"]))
        self.assertEqual(self.sessions()[0]["files_written"],
                         ["/home/you/api/a.py"])

    def test_a_session_with_one_file_is_untouched(self):
        # The overwhelming majority.  Merging must be a no-op for them.
        self.add(worker(["make test"], paths=["/home/you/api/a.py"], turns=2))
        s = self.sessions()[0]
        self.assertEqual(s["commands"], ["make test"])
        self.assertEqual(s["user_turns"], 2)
        self.assertEqual(s["errors"], 0)
        self.assertEqual((s["tokens_in"], s["tokens_out"]), (100, 50))

    def test_different_session_ids_are_not_merged(self):
        other = "019fc999-aaaa-bbbb-cccc-ddddeeeeffff"
        self.add(worker(["make test"]))
        self.add(worker(["pytest -x"], session_id=other), session_id=other)
        found = self.sessions()
        self.assertEqual(len(found), 2)
        self.assertEqual(sorted(sum((s["commands"] for s in found), [])),
                         ["make test", "pytest -x"])

    def test_a_symlink_to_a_worker_does_not_double_it(self):
        # The existing realpath guard has to keep working through the merge —
        # it is the one case where two paths really are one file.
        real = self.add(worker(["make test"], turns=2))
        link = os.path.join(self.dir, "rollout-2026-08-04T09-09-00-%s.jsonl" % SID)
        os.symlink(real, link)
        s = self.sessions()[0]
        self.assertEqual(s["user_turns"], 2)
        self.assertEqual(s["commands"], ["make test"])

    def test_the_version_and_project_are_not_multiplied(self):
        self.add(worker(["a"]))
        self.add(worker(["b"]))
        s = self.sessions()[0]
        self.assertEqual(s["version"], "0.55.0")
        self.assertEqual(s["project"], CWD)
        self.assertEqual(s["project_name"], "api")


if __name__ == "__main__":
    unittest.main()
