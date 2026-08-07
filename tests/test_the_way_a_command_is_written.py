"""What `paths_as_shown` gives back: a command row that spends its cells on
what the command did rather than on where the reader already is.

`test_the_way_a_file_path_is_written.py` is the same set of questions asked of a
line that *is* a path.  This one is about a line that has paths *in* it, which
is what a command is, and the two differ in one thing that changes every answer:
there is other text to protect.  Cutting the row from the right was throwing
away the flags -- the part that says what happened -- to keep an absolute path
the row above had already printed in full.

Measured before it was built: across 15,834 real commands on this machine, 68%
were too wide for the row that carries them, and 47% of those lost a path to the
cut.  That is roughly a third of every command row agentlog and agentwatch print.

The decisions, each of which could be undone without another test in either
repository noticing:

  * what the reader already knows comes off every path always -- the project
    root, or their own home -- because it costs nothing to drop;
  * directories come off only under pressure, off the widest path first, one
    at a time, so a line with room says everything and a line without it gives
    up its least useful cells first;
  * the front of the *line* is kept when there is no path left to shorten,
    because `find` and `grep` are what name a command;
  * things that merely look like paths are left alone -- a URL, a `sed`
    expression, the second half of a `PATH=`;
  * the text between the paths comes back exactly as it went in; and
  * a path is the same shape here as it is anywhere else in the family, so the
    same file is spelled one way whichever row it lands in.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.render import render_text              # noqa: E402
from agentlog.terminal import display_width          # noqa: E402
from agentlog.which_file import as_shown, paths_as_shown  # noqa: E402

_HOME = "/home/somebody"


def _at_home(home=_HOME):
    """Pin the home directory: `~` is otherwise whoever is running the tests."""
    return mock.patch.dict(os.environ, {"HOME": home})


class TestWhatComesOffWithoutBeingAskedFor(unittest.TestCase):
    """The free half: dropping it cannot cost the reader anything."""

    def test_the_project_root_goes_even_with_room_to_spare(self):
        # Room of 200 for a line of 40: nothing here is pressure.  The root
        # still goes, because the reader is looking at that project -- the
        # cells it costs buy them a fact they already had.
        line = paths_as_shown("find /p/work/run1 -name '*.py'", "/p", 200)
        self.assertEqual(line, "find work/run1 -name '*.py'")

    def test_a_project_given_as_a_name_works_the_same(self):
        # agentlog knows the root directory; agentwatch knows only the name off
        # an event.  One parameter takes both, so neither caller fakes the
        # other's knowledge.
        line = paths_as_shown("cat /home/you/api/src/app.py", "api", 200)
        self.assertEqual(line, "cat src/app.py")

    def test_a_name_is_matched_as_a_whole_component(self):
        # `relay` must not shorten a path in `relayed`: a different project
        # whose name merely starts the same way.
        line = paths_as_shown("cat /home/you/relayed/x.py", "relay", 200)
        self.assertEqual(line, "cat /home/you/relayed/x.py")

    def test_home_goes_off_a_path_outside_the_project(self):
        with _at_home():
            line = paths_as_shown("bash /home/somebody/.local/bin/go.sh",
                                  "/p", 200)
        self.assertEqual(line, "bash ~/.local/bin/go.sh")

    def test_home_with_nothing_after_it_is_written_as_home(self):
        # `cd /home/you` is a real command, and the separator rule cannot see
        # it -- there is no separator.  Left out, it is the one path that gets
        # *longer* under pressure: `…/you`, a directory nobody can place,
        # standing in for the one everybody can.
        with _at_home():
            self.assertEqual(paths_as_shown("cd /home/somebody && make", "", 200),
                             "cd ~ && make")

    def test_a_path_that_is_neither_is_left_whole(self):
        with _at_home():
            line = paths_as_shown("tail /var/log/syslog", "/p", 200)
        self.assertEqual(line, "tail /var/log/syslog")


class TestWhatIsNotAPath(unittest.TestCase):
    """Everything with a slash in it that a reader would be upset to see cut."""

    def test_a_url_is_not_touched(self):
        # `//host/a/b` shortened out of the middle of a URL is a visible bug;
        # a `PATH=/a:/b` left alone is merely a missed shortening.  The `:` is
        # what tells them apart, and it is on neither side of the rule.
        line = "curl -s https://github.com/iselur/stillworks/releases"
        self.assertEqual(paths_as_shown(line, "/p", 200), line)
        # And asked again with no room, which is where it matters: with room to
        # spare a URL wrongly read as a path comes back unchanged anyway --
        # nothing about it is under home or under the project, so there is
        # nothing to take off it and the mistake is invisible.  Only pressure
        # makes the two answers differ.  A URL cut from the right is a URL you
        # can still see the host of; one shortened from the front is not a URL.
        self.assertTrue(paths_as_shown(line, "/p", 30)
                        .startswith("curl -s https://github.com"),
                        paths_as_shown(line, "/p", 30))

    def test_a_sed_expression_is_not_touched(self):
        line = "sed -i s/home/away/g notes.txt"
        self.assertEqual(paths_as_shown(line, "/p", 200), line)

    def test_a_search_path_is_not_read_as_one_enormous_path(self):
        # Without the colon ending the run, `/a:/usr/local/...` is one match and
        # gets shortened through its own separator.
        #
        # The first entry is the short one on purpose.  A search path whose
        # *first* entry is the long one shortens to the same string either way
        # -- the mark lands in the same place -- and a fixture that cannot tell
        # the two apart is not a test of anything.  Here nothing can give, so
        # the honest answer is to cut from the right and keep the front.
        line = "PATH=/a:/usr/local/lib/python3/site-packages make test"
        self.assertEqual(paths_as_shown(line, "/p", 200), line)
        with _at_home():
            tight = paths_as_shown(line, "/p", 30)
        self.assertTrue(tight.startswith("PATH=/a:/usr"), tight)

    def test_a_relative_path_is_left_where_it_is(self):
        # Nothing on the front of it is anything the reader already knows, so
        # there is nothing to take off and matching it is all risk.
        line = "python3 tools/probe.py --limit 5"
        self.assertEqual(paths_as_shown(line, "/p", 200), line)

    def test_a_flag_that_starts_with_a_slash_is_not_swallowed(self):
        # A quote ends the run as well as starting one, so the path inside the
        # quotes is what matches and the quote itself stays put.
        with _at_home():
            line = paths_as_shown("grep -r 'x' '/home/somebody/a/b.py'", "", 200)
        self.assertEqual(line, "grep -r 'x' '~/a/b.py'")


class TestUnderPressure(unittest.TestCase):
    """Directories come off only when the line will not otherwise fit."""

    LINE = "diff /p/one/two/three/left.py /p/aa/bb/right.py"

    def test_with_room_to_spare_no_directory_is_dropped(self):
        self.assertEqual(paths_as_shown(self.LINE, "/p", 200),
                         "diff one/two/three/left.py aa/bb/right.py")

    def test_the_widest_path_gives_first(self):
        # 38 cells: two directories must go, and both come off the wider path --
        # which is still the wider one after the first -- because that is where
        # the line's least useful cells are.  The narrow path keeps everything.
        shown = paths_as_shown(self.LINE, "/p", 38)
        self.assertEqual(shown, "diff …/three/left.py aa/bb/right.py")
        self.assertLessEqual(display_width(shown), 38)
        # Again with the two swapped round, because in the line above the widest
        # path is also the first one -- so a rule that simply took the first it
        # could shorten would give the same answer and look correct.
        swapped = "diff /p/aa/bb/right.py /p/one/two/three/left.py"
        self.assertEqual(paths_as_shown(swapped, "/p", 38),
                         "diff aa/bb/right.py …/three/left.py")

    def test_it_gives_one_directory_at_a_time(self):
        # One cell of pressure takes one directory, not the whole front of the
        # path.  A rule that dropped everything on the first squeeze would make
        # every tight row say `…/left.py`, and two files in two directories
        # with the same name would read as one file twice.
        widest = "diff one/two/three/left.py aa/bb/right.py"
        shown = paths_as_shown(self.LINE, "/p", display_width(widest) - 1)
        self.assertEqual(shown, "diff …/two/three/left.py aa/bb/right.py")

    def test_when_no_path_can_give_the_front_of_the_line_is_kept(self):
        # `find` is what names this row.  A line cut from the front would leave
        # the reader a fragment of a filename and no idea what was done to it.
        with _at_home():
            shown = paths_as_shown("findmyfiles --everywhere --and-then-some",
                                   "/p", 20)
        self.assertEqual(shown, "findmyfiles --every…")
        # And a line that has slashes in it, which is the case that tells the
        # two cutters apart.  A relative path is not shortened -- there is
        # nothing on its front the reader already knows -- so this line reaches
        # the same fallback, and the cutter that keeps the *file* would answer
        # `…/test_x.py -k something`: the end of a path, for a line that is not
        # one, with `pytest` gone.
        with _at_home():
            shown = paths_as_shown(
                "pytest tests/very/deep/nested/dir/test_x.py -k something",
                "/p", 24)
        self.assertEqual(shown, "pytest tests/very/deep/…")

    def test_the_answer_never_overruns_the_room_it_was_given(self):
        # The property, over every width a row could have.  A row that promises
        # a width and returns one cell more is a wrapped line, which costs the
        # fixed layout more than any amount of shortening does.
        lines = [self.LINE,
                 "run " + " ".join("/p/a/b/c/d/e/f/file%d.py" % i
                                   for i in range(6)),
                 "curl -s https://example.com/a/b/c | tee /p/out.log",
                 "cat /p/日本語のディレクトリ/app.py"]
        with _at_home():
            for line in lines:
                for room in range(1, 120):
                    shown = paths_as_shown(line, "/p", room)
                    self.assertLessEqual(display_width(shown), room,
                                         (room, line, shown))

    def test_no_room_at_all_shows_nothing(self):
        # Not the one cell the mark costs.  `as_shown` has said this since it
        # was written, and a second rule in the same file overflowing by one
        # instead would be the same bug twice with one of them fixed.
        self.assertEqual(paths_as_shown("cat /p/a.py", "/p", 0), "")
        self.assertEqual(paths_as_shown("", "/p", 40), "")

    def test_without_a_room_it_does_the_free_half_and_stops(self):
        # For a caller with its own ideas about width.  Nothing is cut, so a
        # long line comes back long.
        line = "diff " + "/p/" + "x" * 300
        self.assertEqual(paths_as_shown(line, "/p", None), "diff " + "x" * 300)

    def test_a_path_already_down_to_its_name_is_not_squeezed_again(self):
        # It has nothing left to give, and a loop that asked it again would
        # never end.  `~/name` is the same case wearing a different hat: `~`
        # and `…` are one cell each, so trading them buys nothing.
        with _at_home():
            shown = paths_as_shown("ls ~/r102-bench /p/a/b/c.py", "", 22)
        self.assertIn("~/r102-bench", shown)
        self.assertNotIn("…/r102-bench", shown)


class TestTheRestOfTheLineIsUntouched(unittest.TestCase):
    """Only the paths change; the line they sit in comes back as it went in."""

    def test_the_spacing_and_quoting_survive_exactly(self):
        line = 'grep -ril "led ger"  /p/a.md   --include="*.md" -l 2>/dev/null'
        shown = paths_as_shown(line, "/p", 200)
        self.assertEqual(shown,
                         'grep -ril "led ger"  a.md   --include="*.md" -l 2>/dev/null')

    def test_a_line_with_no_path_in_it_comes_back_whole(self):
        for line in ("make test", "echo hello world", "npm run build -- --watch",
                     "git commit -m 'no slashes here'"):
            self.assertEqual(paths_as_shown(line, "/p", 200), line, line)

    def test_a_path_at_the_very_start_of_the_line_is_found(self):
        # The one case a lookbehind cannot see: there is no character before it.
        self.assertEqual(paths_as_shown("/p/bin/tool --go", "/p", 200),
                         "bin/tool --go")

    def test_two_paths_running_together_keep_their_separator(self):
        self.assertEqual(paths_as_shown("cp /p/a.py /p/b.py", "/p", 200),
                         "cp a.py b.py")


class TestItSpellsAPathTheWayTheRestOfTheFamilyDoes(unittest.TestCase):
    """One file, one spelling, whichever row it lands in."""

    def test_a_line_that_is_one_path_reads_as_that_path(self):
        # The two rules meet here, and they have to agree: `agentwatch` prints
        # a written file through `as_shown` and the command that wrote it
        # through this one, on adjacent rows of the same feed.
        #
        # The floor is the width of `…/name`.  Below that the row cannot say
        # which file it is under either rule, and what the two do with the last
        # four cells is not a promise worth pinning.
        with _at_home():
            for path in ("/p/a/b/c/app.py", "/home/somebody/x/y/z.py",
                         "/q/w/e/r/t/y.py", "/p/very/deep/nest/of/d/f.py"):
                floor = display_width("…/" + path.rsplit("/", 1)[-1])
                for room in range(floor, 40):
                    self.assertEqual(paths_as_shown(path, "/p", room),
                                     as_shown(path, "/p", room),
                                     (path, room))

    def test_it_is_measured_in_cells_and_not_characters(self):
        # Seventeen characters, twenty-seven cells.  The row this lands in is
        # measured in cells, so counting characters here overruns it by ten.
        line = "cat /p/日本語のディレクトリ/app.py"
        self.assertEqual(len("日本語のディレクトリ/app.py"), 17)
        shown = paths_as_shown(line, "/p", 20)
        self.assertEqual(shown, "cat …/app.py")


class TestTheRowAPersonActuallySees(unittest.TestCase):
    """The detail view's `$` row, through the command a person runs.

    Everything above tests the rule.  This tests the row that uses it, because
    the rule being right and the row being told which project it is in are two
    separate things, and only one of them was true before.
    """

    def _session(self, command):
        return {
            "id": "abc12345-0000-0000-0000-000000000000",
            "source": "claude",
            "project": "/home/test/myproject",
            "project_name": "myproject",
            "start": datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 8, 7, 11, 0, tzinfo=timezone.utc),
            "duration_s": 3600.0,
            "models": ["claude-test"],
            "user_turns": 1,
            "files_read": [],
            "files_written": [],
            "commands": [command],
            "errors": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "ai_title": "",
            "version": "2.1.0",
            "skipped_lines": 0,
        }

    def _the_dollar_row(self, command):
        rows = [ln.strip() for ln in render_text([self._session(command)]).splitlines()
                if ln.strip().startswith("$ ")]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_the_row_says_the_file_and_not_the_directory_it_is_in(self):
        # The session's own directory is printed in the header two rows above,
        # so a command row that spells it out again is saying `myproject` twice
        # and calling the second one a path.  Short enough to fit either way --
        # so the row is not being *cut*, it is being *written* -- which is the
        # difference the row has to show.
        row = self._the_dollar_row(
            "pytest /home/test/myproject/tests/test_auth.py -k login")
        self.assertEqual(row, "$ pytest tests/test_auth.py -k login")

    def test_a_file_outside_the_project_keeps_enough_to_be_found(self):
        # The other half of the same promise: taking off what the reader knows
        # is not the same as taking off everything.  A file somewhere else is
        # still named from somewhere.
        row = self._the_dollar_row("cat /etc/hosts")
        self.assertEqual(row, "$ cat /etc/hosts")


if __name__ == "__main__":
    unittest.main()
