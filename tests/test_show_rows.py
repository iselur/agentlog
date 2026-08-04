"""A command could write its own rows into `agentlog show`.

`safe_for_terminal` says what the rule is meant to be:

    Tabs and newlines are kept: they are this module's own layout, applied
    after the untrusted text has already passed through here.

`render_show` broke the second half.  It put commands and paths *into* the
layout and sanitised the joined result, so by then a newline that came out of a
log file was indistinguishable from one this module wrote itself.  A command
containing a newline arrived on screen as extra rows:

    commands (1):
      $ echo harmless
      $ npm publish --access public
      $ git push --force

One command ran.  Three are shown, two of them written by the thing being
audited, in exactly the shape of a real row.  `agentlog show` is the view a
person opens to find out what an agent actually did, so a row it cannot vouch
for is the whole problem.  The header disagreeing with the rows underneath it
is the only tell, and only if you count them.

It is not only an attack.  Agents write heredocs and `python3 -c '...'` all
day, so this fires on ordinary sessions: every multi-line command silently
became several, and `commands (12)` sat above forty rows.

Every other view was already fine — `_shorten_cmd` flattens newlines, which is
why the summary, `list`, Markdown and HTML never showed this.  Only the detail
view put raw text into its own layout.

Length went the same way.  One 5 MB command — an agent pasting a file into a
heredoc — printed as a single 5 MB row and took the rest of the session off
the screen with it.
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

from agentlog.render import render_show


def _session(**over):
    s = {
        "id": "8ef1361b-07e4-4bc9-bb29-1783b761d671",
        "source": "claude",
        "project": "proj",
        "start": None,
        "end": None,
        "duration_s": 0.0,
        "models": [],
        "user_turns": 1,
        "errors": 0,
        "files_read": [],
        "files_written": [],
        "commands": [],
    }
    s.update(over)
    return s


def _section(text, header):
    """The rows under a `header (n):` line, up to the blank line after them."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith(header + " ("):
            inside = True
            continue
        if inside:
            if not line.strip():
                break
            out.append(line)
    return out


class TestOneCommandIsOneRow(unittest.TestCase):

    def test_a_newline_does_not_make_a_second_row(self):
        text = render_show(_session(commands=[
            "echo harmless\n  $ npm publish --access public"]))
        rows = _section(text, "commands")
        self.assertEqual(len(rows), 1,
                         "one command produced {} rows:\n{}".format(
                             len(rows), "\n".join(rows)))

    def test_the_forged_row_is_still_readable_on_the_real_one(self):
        # Flattened, not dropped: it is what the agent ran and you came here
        # to read it.  It just cannot have a row of its own.
        text = render_show(_session(commands=[
            "echo harmless\n  $ npm publish --access public"]))
        rows = _section(text, "commands")
        self.assertIn("npm publish --access public", rows[0])

    def test_the_header_count_matches_the_rows(self):
        cmds = ["a\nb\nc", "plain", "d\ne"]
        text = render_show(_session(commands=cmds))
        rows = _section(text, "commands")
        self.assertIn("commands (3):", text)
        self.assertEqual(len(rows), 3,
                         "header says 3, screen shows {}:\n{}".format(
                             len(rows), "\n".join(rows)))

    def test_a_carriage_return_does_not_make_a_row_either(self):
        text = render_show(_session(commands=["real\rFORGED"]))
        self.assertEqual(len(_section(text, "commands")), 1, text)

    def test_a_line_separator_does_not_make_a_row_either(self):
        # U+2028 is a newline to a terminal and not to `str.split("\n")`.
        text = render_show(_session(commands=["real FORGED"]))
        self.assertEqual(len(_section(text, "commands")), 1, text)

    def test_an_ordinary_command_is_printed_whole(self):
        cmd = "pytest tests/test_auth.py -x --maxfail=1 -q"
        text = render_show(_session(commands=[cmd]))
        self.assertIn("  $ " + cmd, text)


class TestPathsAreRowsToo(unittest.TestCase):
    """Paths come out of the same log file and get the same layout."""

    def test_a_written_path_with_a_newline_is_one_row(self):
        text = render_show(_session(files_written=["src/a.py\n  src/forged.py"]))
        self.assertEqual(len(_section(text, "files written")), 1, text)

    def test_a_read_path_with_a_newline_is_one_row(self):
        text = render_show(_session(files_read=["src/a.py\n  src/forged.py"]))
        self.assertEqual(len(_section(text, "files read")), 1, text)

    def test_ordinary_paths_are_untouched(self):
        text = render_show(_session(files_written=["src/auth/session.py"]))
        self.assertIn("  src/auth/session.py", text)


class TestOneCommandCannotFillTheScreen(unittest.TestCase):

    def test_a_huge_command_is_cut(self):
        text = render_show(_session(commands=["x" * 5_000_000]))
        rows = _section(text, "commands")
        self.assertEqual(len(rows), 1)
        self.assertLess(len(rows[0]), 1000,
                        "a 5 MB command printed as a 5 MB row")

    def test_it_says_it_cut_something(self):
        # A detail view that quietly shows less than it has is the same class
        # of problem in the other direction.
        text = render_show(_session(commands=["x" * 5_000_000]))
        row = _section(text, "commands")[0]
        self.assertIn("…", row, row[:200])
        self.assertIn("json", row.lower(),
                      "does not say where the whole thing is: " + row[-120:])

    def test_the_rest_of_the_session_survives_it(self):
        text = render_show(_session(
            commands=["x" * 5_000_000, "pytest -x"],
            files_written=["src/after.py"]))
        self.assertIn("pytest -x", text)
        self.assertIn("src/after.py", text)


class TestNothingElseMoves(unittest.TestCase):

    def test_the_header_block_is_unchanged(self):
        text = render_show(_session(models=["claude-opus-5"], errors=2))
        for expected in ("session  8ef1361b", "source   claude",
                         "project  proj", "models   claude-opus-5",
                         "errors   2"):
            self.assertIn(expected, text, text)

    def test_an_empty_session_still_renders(self):
        text = render_show(_session())
        self.assertIn("session  ", text)
        self.assertNotIn("commands (", text)

    def test_escapes_are_still_stripped(self):
        text = render_show(_session(commands=["echo \x1b[2Jhi"]))
        self.assertNotIn("\x1b", text)


if __name__ == "__main__":
    unittest.main()
