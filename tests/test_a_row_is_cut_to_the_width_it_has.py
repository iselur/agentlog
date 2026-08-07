"""One rule for cutting text to a row, in the units an eye reads.

`render.py` had five of these.  Three spellings of the mark, two units (cells
in one place, characters in four), two directions, and the mark added after the
cut in some of them and before it in others -- so the same command looked like a
different command depending on which view you were in, and two rows ran off the
side of the layout they were measured against.

Two of the faults were user-visible and are reproduced here as they appeared:

*   the digest's ``failed`` row, cut with `len`, drew 121 cells on an 80-cell
    layout for a command written in Japanese -- sitting directly under the
    ``edited`` row, whose comment says this exact fault was found and fixed for
    *that* row and nowhere else;
*   a long command in the detail view was cut to its last 80 characters and
    then to the first 72 of those, so the reader was shown the middle of the
    command and no part of either end.

Both are silent: nothing raises, the row just comes out wrong.  So the tests at
the bottom are structural -- they assert the views go through the one rule,
because a view that quietly grows its own cutter again would pass every test
above.
"""

import os
import re
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentlog import render
from agentlog.render import (
    _CUT,
    _cmd_headline,
    _first_few,
    _DIGEST_WIDTH,
    render_digest,
    render_markdown,
    render_text,
    shortened,
)
from agentlog.terminal import display_width


def _make_session(**overrides) -> dict:
    """A session with nothing interesting in it but the field under test."""
    base = {
        "id": "abc12345-0000-0000-0000-000000000000",
        "source": "claude",
        "project": "/home/test/myproject",
        "project_name": "myproject",
        "start": datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc),
        "end": datetime(2026, 8, 7, 11, 0, tzinfo=timezone.utc),
        "duration_s": 3600.0,
        "models": ["claude-test"],
        "user_turns": 5,
        "files_read": [],
        "files_written": [],
        "commands": [],
        "errors": 0,
        "tokens_in": 5000,
        "tokens_out": 1500,
        "ai_title": "fix the auth bug",
        "version": "2.1.0",
        "skipped_lines": 0,
    }
    base.update(overrides)
    return base


#: Nine characters, eighteen cells.  Every wide-character case below is built
#: out of this so the two units disagree by a factor of two and a test that
#: counts the wrong one cannot accidentally pass.
WIDE = "テストの名前が長い"


class TestItFitsTheWidthItWasGiven(unittest.TestCase):

    def test_text_that_already_fits_is_left_exactly_alone(self):
        self.assertEqual(shortened("git status", 40), "git status")
        self.assertEqual(shortened("git status", 10), "git status")

    def test_the_width_is_in_cells_not_characters(self):
        # The whole point.  Nine characters, eighteen cells: asked for ten
        # cells, a cutter counting characters hands back all nine and draws
        # eighteen.
        out = shortened(WIDE, 10)
        self.assertLessEqual(display_width(out), 10)
        self.assertLess(len(out), len(WIDE))

    def test_a_wide_character_is_never_split_down_the_middle(self):
        # An odd budget cannot be spent exactly on two-cell characters, so the
        # last cell goes unused rather than half a character being drawn.
        out = shortened(WIDE, 9)
        self.assertLessEqual(display_width(out), 9)
        self.assertTrue(all(c in WIDE + _CUT for c in out), out)

    def test_the_mark_comes_out_of_the_budget_not_after_it(self):
        # A width is a promise about the row the text goes in.  A mark added
        # once the cutting is over breaks that promise by the width of the
        # mark, which is how a row that fits becomes a row that wraps.
        for width in range(2, 40):
            out = shortened("x" * 200, width)
            self.assertEqual(display_width(out), width, (width, out))
            self.assertTrue(out.endswith(_CUT), out)

    def test_the_mark_is_one_cell_wide_and_one_character_long(self):
        # An equivalence, not a preference.  `room = width - len(_CUT)` and
        # `room = width - display_width(_CUT)` are the same line while the mark
        # is `…`, so no test can tell them apart -- which is exactly why this
        # is written down: pick a mark that draws in two cells and the first
        # spelling starts handing back rows a cell too wide, silently.
        self.assertEqual(display_width(_CUT), 1)
        self.assertEqual(len(_CUT), 1)

    def test_a_width_with_no_room_for_the_mark(self):
        # One cell is enough to say "there was more" and nothing else.
        self.assertEqual(shortened("x" * 20, 1), _CUT)
        # Zero cells is a column no text fits in; there is nothing honest to
        # return but nothing.
        self.assertEqual(shortened("x" * 20, 0), "")


class TestWhichEndIsKept(unittest.TestCase):

    def test_a_command_keeps_its_head(self):
        out = shortened("pytest tests/test_render.py -k something_long", 20)
        self.assertTrue(out.startswith("pytest "), out)
        self.assertTrue(out.endswith(_CUT), out)

    def test_a_path_keeps_its_basename(self):
        # A path is identified by its end -- `.../render.py` says what the file
        # is, `/home/val/agent…` says only that it is somewhere under a home
        # directory.
        out = shortened("/home/val/agentlog/agentlog/render.py", 20,
                        keep_the_end=True)
        self.assertTrue(out.endswith("render.py"), out)
        self.assertTrue(out.startswith(_CUT), out)
        self.assertEqual(display_width(out), 20)

    def test_keeping_the_end_is_still_measured_in_cells(self):
        out = shortened(WIDE * 3, 11, keep_the_end=True)
        self.assertLessEqual(display_width(out), 11)
        self.assertTrue(out.startswith(_CUT), out)
        self.assertTrue(out.endswith(WIDE[-1]), out)


class TestTheHeadlineOfACommand(unittest.TestCase):

    def test_both_marks_are_inside_the_width(self):
        # A multi-line command carries two marks: one for the lines below the
        # first, one for the part of the first line that did not fit.  Both are
        # part of what has to fit in the row.
        head = _cmd_headline("x" * 200 + "\nmore\n", width=12)
        self.assertEqual(display_width(head), 12, head)
        self.assertTrue(head.endswith(" " + _CUT), head)

    def test_a_short_multi_line_command_is_not_cut_but_is_marked(self):
        head = _cmd_headline("make test\nmake lint", width=40)
        self.assertEqual(head, "make test " + _CUT)

    def test_a_wide_first_line_is_measured_in_cells(self):
        head = _cmd_headline(WIDE * 4, width=20)
        self.assertLessEqual(display_width(head), 20)


class TestTheLineSayingWhatWasLeftOut(unittest.TestCase):

    def test_nothing_is_added_when_nothing_was_left_out(self):
        self.assertEqual(_first_few(["a", "b"], limit=6), ["a", "b"])

    def test_it_says_how_many_and_uses_the_one_mark(self):
        out = _first_few([str(i) for i in range(10)], limit=4)
        self.assertEqual(out[-1], "  " + _CUT + " and 6 more")

    def test_the_indent_is_the_only_thing_that_varies(self):
        out = _first_few([str(i) for i in range(10)], limit=4, indent="")
        self.assertEqual(out[-1], _CUT + " and 6 more")

    def test_exactly_the_limit_leaves_nothing_out(self):
        # The boundary, because off by one here prints "… and 0 more" under a
        # list that is showing every item it has -- a footnote that is not only
        # noise but a false statement about what the reader is looking at.
        out = _first_few([str(i) for i in range(4)], limit=4)
        self.assertEqual(out, ["0", "1", "2", "3"])


class TestTheRowsTheUserSaw(unittest.TestCase):
    """The two reproductions, at the views the reader actually looks at."""

    def _digest(self, **overrides):
        at = datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc)
        sess = _make_session(start=at, end=at, **overrides)
        return render_digest([sess])

    def test_the_failed_row_fits_the_digest_like_the_row_above_it(self):
        # Cut with `len`, this row measured 121 cells against a layout of 80.
        out = self._digest(failed_cmds=["pytest " + WIDE * 8])
        rows = [ln for ln in out.splitlines() if "failed" in ln]
        self.assertTrue(rows, out)
        for row in out.splitlines():
            self.assertLessEqual(display_width(row), _DIGEST_WIDTH, repr(row))

    def test_the_count_on_a_failed_row_is_inside_the_width_too(self):
        # `(3x)` is part of the row, so it comes out of the budget rather than
        # being stuck on once the cutting is over.
        out = self._digest(failed_cmds=["pytest " + WIDE * 8] * 3)
        self.assertIn("(3x)", out)
        for row in out.splitlines():
            self.assertLessEqual(display_width(row), _DIGEST_WIDTH, repr(row))

    def test_a_long_project_name_is_held_to_its_column(self):
        # The digest's first column is a fixed width and the rows after it are
        # laid out against that width, so a project nobody shortened does not
        # just overflow -- it pushes the duration and the stats out of line on
        # its own row and leaves every other row where it was.
        out = self._digest(project_name="a-" + WIDE * 4 + "-project")
        for row in out.splitlines():
            self.assertLessEqual(display_width(row), _DIGEST_WIDTH, repr(row))
        self.assertIn(_CUT, out)

    def test_a_long_command_shows_its_head_and_not_its_middle(self):
        # Cut twice in opposite directions -- to the last 80 characters and
        # then to the first 72 of those -- the reader was shown neither end.
        cmd = "git commit -m " + "a" * 300 + " THE-END"
        out = render_text([_make_session(commands=[cmd])])
        row = [ln for ln in out.splitlines() if ln.strip().startswith("$ ")][0]
        self.assertIn("git commit -m ", row)
        self.assertNotIn("THE-END", row)

    def test_a_long_path_shows_its_name_and_not_its_root(self):
        path = "/home/val/" + "deeply/" * 20 + "render.py"
        out = render_text([_make_session(files_written=[path])])
        row = [ln for ln in out.splitlines() if "render.py" in ln][0]
        self.assertIn(_CUT, row)

    def test_every_view_says_left_out_the_same_way(self):
        many_files = [f"/src/file{i:03d}.py" for i in range(40)]
        many_cmds = [f"echo {i}" for i in range(40)]
        sess = _make_session(files_written=many_files, commands=many_cmds)
        said = re.findall(r"\S+ and \d+ more",
                          render_text([sess]) + "\n" + render_markdown([sess]))
        self.assertTrue(said)
        for phrase in said:
            self.assertTrue(phrase.startswith(_CUT),
                            "{!r} does not use the one mark".format(phrase))


class TestItCannotComeBack(unittest.TestCase):
    """The two faults were silent, so these are the tests that catch a relapse.

    Spelled out by hand rather than derived from `render.py` -- a structural
    test that asks the module what it does agrees with the module by
    construction and proves nothing.
    """

    SOURCE = os.path.join(os.path.dirname(__file__), "..", "agentlog",
                          "render.py")

    def _source(self):
        with open(self.SOURCE, encoding="utf-8") as fh:
            return fh.read()

    def test_the_mark_is_written_down_exactly_once(self):
        # Three spellings is how the same event came to look like three
        # different ones.  Docstrings are allowed to quote the old ones -- they
        # are the record of why this rule exists -- so only code is counted.
        code = [ln for ln in self._source().splitlines()
                if not ln.lstrip().startswith(("#", "*"))]
        body = "\n".join(code)
        body = re.sub(r'"""[\s\S]*?"""', "", body)
        self.assertEqual(body.count('"…"'), 1, "the mark is spelled twice")
        self.assertNotIn('"..."', body)
        self.assertNotIn("... and ", body)

    #: Every place in `render.py` that cuts a string by a width, and why each
    #: is allowed to.  An allowlist rather than a pattern because the fault is
    #: not "a slice" -- it is a slice standing in for a cell count, and telling
    #: those apart takes a sentence per case, not a regex.
    CUTS_BY_CHARACTER = {
        # The detail view's flood control.  There is no column after it, so it
        # is not fitting anything -- it bounds a 5 MB heredoc and says in words
        # how much it is not showing.
        "flat[:width]": 1,
        # Not text for a row at all: the shortest prefix of a session id that
        # is still unique.  Ids are hex, one cell per character by definition.
        "i[:width]": 2,
        # Lists of items, not text.  How many things to show is a separate
        # question from how wide each may be, and splitting the two is what
        # this change was -- so these two staying list slices is the point.
        "items[:limit]": 1,
        "groups[:max_projects]": 1,
    }

    def test_no_view_cuts_text_with_a_character_count(self):
        # `text[:n]` standing in for a cell count is the fault itself, and it
        # is what made a Japanese command draw 121 cells in an 80-cell row.
        found = {}
        for cut in re.findall(r"\b[a-z_]+\[:\s*[a-z_]+\s*\]", self._source()):
            found[cut] = found.get(cut, 0) + 1
        self.assertEqual(found, self.CUTS_BY_CHARACTER,
                         "a view is cutting by characters again -- if the new "
                         "one is honest, say here in a sentence why")

    def test_the_failed_row_is_held_to_the_digest_width(self):
        # It is the row that was not, and the way it stopped being held was a
        # `len` where a cell count belonged.  Naming the constant here means
        # widening the digest cannot silently unhold it.
        source = self._source()
        self.assertIn(
            "room = _DIGEST_WIDTH - display_width(label) - display_width(times)",
            source)
        self.assertIn("_fitted_headline(head, more_below, room)", source)
        # And cut once, there.  A fixed width upstream of this -- 56 cells, on
        # a row that never has fewer than 59 -- makes the row's own width
        # decorative, so widening the digest moves nothing and the count
        # coming out of the budget stops mattering.
        self.assertNotIn("_cmd_headline(cmd)", source)

    #: Every row in this file that is cut to a width, named by what it holds.
    #: Written out by hand rather than counted, because a count says nothing
    #: about *which* one went missing: a view that quietly grows its own cutter
    #: again leaves the total unchanged and passes every test above this one.
    CUT_ROWS = sorted([
        # a command's headline, in the room the row carrying it has
        'return shortened(line, width - display_width(more)) + more',
        # a command in the detail view
        'return shortened(cmd.replace("\\n", " ").strip(), width)',
        # the digest's project column
        'f"  {_pad(shortened(g[\'name\'], name_w), name_w)}  "',
        # a file path in the detail view, keeping its basename
        'lines.append(f"      {shortened(f, 60, keep_the_end=True)}{tag}")',
        # the project named in a session header
        'project = shortened(s["project_name"] or "?", 24)',
    ])

    def test_every_row_that_is_cut_goes_through_the_one_rule(self):
        source = self._source()
        found = sorted(ln.strip() for ln in source.splitlines()
                       if "shortened(" in ln and not ln.startswith("def "))
        self.assertEqual(found, self.CUT_ROWS,
                         "a row is being cut somewhere other than the one rule")
        for gone in ("def _clip(", "def _truncate("):
            self.assertNotIn(gone, source, "{} is back".format(gone))


if __name__ == "__main__":
    unittest.main()
