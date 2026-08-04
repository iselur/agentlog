"""An edit to a notebook is an edit to a file.

Claude Code writes files with four tools, and the fourth is `NotebookEdit`.
The parser knew three of them.  Worse than the missing name: `NotebookEdit`
does not put its path under `file_path` the way the other three do — it uses
`notebook_path` — so adding the name alone would still have dropped every
path.  A digest for a day spent on a notebook read `0 files written`.

Two things about this one are worth saying plainly.

It was found by reading the tool surface, not by measuring the logs.  There
are no `NotebookEdit` calls in the 864 session logs on this machine, so the
number this fixes is zero here and everything here is a written fixture.
Every other defect in this repo came with a measurement; this one comes with
an argument, and the argument is that a person who works in notebooks does
nothing else — their whole day is `NotebookEdit`, and their whole digest would
be empty.

And it is an under-count, which is the direction that can be caught: `0 files
written` after an afternoon of work is not believable, and a person who saw it
would know something was wrong even if they could not say what.  That is the
opposite of the turn over-count, and the reason this one waited.

`MultiEdit` is in the same set and also unused on this corpus — the set is the
tool surface, not a census of it.
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

from agentlog.parser import parse_claude_session  # noqa: E402

SID = "689e648c-e034-43ab-9783-a72191da648f"
CWD = "/home/you/api"
NB = "/home/you/api/notebooks/explore.ipynb"


def spoke(text="clean up the notebook", ts="2026-08-04T09:00:00.000Z"):
    return {"type": "user", "isSidechain": False, "timestamp": ts,
            "sessionId": SID, "cwd": CWD, "version": "2.1.220",
            "message": {"role": "user", "content": text}}


def called(name, inp, tool_use_id="t1", ts="2026-08-04T09:00:01.000Z"):
    return {"type": "assistant", "isSidechain": False, "timestamp": ts,
            "sessionId": SID, "cwd": CWD,
            "message": {"role": "assistant", "id": "msg_" + tool_use_id,
                        "model": "claude-opus-5",
                        "content": [{"type": "tool_use", "id": tool_use_id,
                                     "name": name, "input": inp}],
                        "usage": {"input_tokens": 10, "output_tokens": 5}}}


def edited_notebook(path=NB, tool_use_id="t1", ts="2026-08-04T09:00:01.000Z",
                    mode="replace"):
    return called("NotebookEdit",
                  {"notebook_path": path, "cell_id": "c1",
                   "edit_mode": mode, "new_source": "import pandas as pd"},
                  tool_use_id, ts)


def failed(tool_use_id="t1", ts="2026-08-04T09:00:02.000Z"):
    return {"type": "user", "isSidechain": False, "timestamp": ts,
            "sessionId": SID, "cwd": CWD,
            "message": {"role": "user",
                        "content": [{"type": "tool_result",
                                     "tool_use_id": tool_use_id,
                                     "is_error": True,
                                     "content": "cell not found"}]}}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="al-nb-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

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


class TestANotebookEditIsAWrite(Case):

    def test_it_counts_as_a_file_written(self):
        s = self.parsed([spoke(), edited_notebook()])
        self.assertEqual(s["files_written"], [NB])

    def test_the_path_comes_off_notebook_path(self):
        # The whole point: the field is not `file_path`, and reading only
        # `file_path` loses the path even once the name is known.
        s = self.parsed([spoke(), edited_notebook("/home/you/api/a.ipynb")])
        self.assertEqual(s["files_written"], ["/home/you/api/a.ipynb"])

    def test_it_emits_a_write_event(self):
        s = self.parsed([spoke(), edited_notebook()])
        self.assertEqual([(k, t) for _, k, t in s["events"] if k == "write"],
                         [("write", NB)])

    def test_editing_the_same_notebook_twice_counts_twice(self):
        s = self.parsed([spoke(),
                         edited_notebook(tool_use_id="t1"),
                         edited_notebook(tool_use_id="t2",
                                         ts="2026-08-04T09:00:05.000Z")])
        # files_written is the distinct files; write_counts carries how often.
        self.assertEqual(s["write_counts"][NB], 2)
        self.assertEqual(s["files_written"], [NB])

    def test_every_edit_mode_is_a_write(self):
        # insert and delete change the file exactly as much as replace does.
        for mode in ("replace", "insert", "delete"):
            s = self.parsed([spoke(), edited_notebook(mode=mode)])
            self.assertEqual(s["files_written"], [NB], mode)


class TestItSitsBesideTheOtherWriteTools(Case):

    def test_a_notebook_and_a_python_file_are_both_counted(self):
        s = self.parsed([
            spoke(),
            called("Write", {"file_path": "/home/you/api/x.py",
                             "content": "x = 1"}, "t1"),
            edited_notebook(tool_use_id="t2", ts="2026-08-04T09:00:02.000Z"),
        ])
        self.assertEqual(sorted(s["files_written"]),
                         ["/home/you/api/notebooks/explore.ipynb",
                          "/home/you/api/x.py"])

    def test_file_path_still_wins_for_the_ordinary_tools(self):
        # A `notebook_path` on a Write would be somebody else's record shape;
        # Write is read from file_path and nothing else.
        s = self.parsed([spoke(),
                         called("Write", {"notebook_path": NB,
                                          "content": "x"}, "t1")])
        self.assertEqual(s["files_written"], [])

    def test_a_read_is_still_a_read(self):
        # Read takes .ipynb too, and takes it under file_path.  Reading a
        # notebook is not writing one.
        s = self.parsed([spoke(), called("Read", {"file_path": NB}, "t1")])
        self.assertEqual(s["files_written"], [])
        self.assertEqual(s["files_read"], [NB])


class TestItIsNamedWhenItFails(Case):

    def test_a_failed_notebook_edit_names_the_notebook(self):
        # Without the fix the label is the bare tool name, so the failure
        # line says `NotebookEdit` and not which notebook.
        s = self.parsed([spoke(), edited_notebook(), failed()])
        self.assertEqual(s["failed_cmds"], ["edit explore.ipynb"])
        self.assertEqual(s["errors"], 1)


class TestTheInputIsReadDefensively(Case):

    def test_a_notebook_edit_with_no_path_writes_nothing(self):
        s = self.parsed([spoke(), called("NotebookEdit",
                                         {"new_source": "x = 1"}, "t1")])
        self.assertEqual(s["files_written"], [])

    def test_a_non_string_path_writes_nothing(self):
        s = self.parsed([spoke(), called("NotebookEdit",
                                         {"notebook_path": {"p": NB}}, "t1")])
        self.assertEqual(s["files_written"], [])

    def test_a_pathless_notebook_edit_still_names_itself_on_failure(self):
        # It falls through to the bare-name label, which is the most that can
        # honestly be said about it.
        s = self.parsed([spoke(),
                         called("NotebookEdit", {"new_source": "x"}, "t1"),
                         failed()])
        self.assertEqual(s["failed_cmds"], ["NotebookEdit"])

    def test_an_unknown_tool_is_not_a_write(self):
        # The path key is chosen per tool, so a tool nobody knows about does
        # not become a write by carrying a notebook_path.
        s = self.parsed([spoke(), called("SomeFutureTool",
                                         {"notebook_path": NB}, "t1")])
        self.assertEqual(s["files_written"], [])


if __name__ == "__main__":
    unittest.main()
