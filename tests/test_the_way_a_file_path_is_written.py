"""What `as_shown` gives back, one shape per test.

`test_render.py` is about the *room* the digest gives a path; the family test in
the stillworks tree is about both commands agreeing.  Neither can see the
spelling itself, and the spelling is where the decisions are:

  * what comes off the front is what the reader already knows -- the project, or
    their own home -- and nothing else, because a bare `todo.md` in a list of
    files is a file you cannot go and look at;
  * a project is whatever the caller happens to know it as, a root directory or
    a name, since one caller has each;
  * a name is matched as a whole path component, or `relay` shortens paths in
    `relayed`;
  * room is taken off the *front*, because the end of a path is the file; and
  * it is measured in terminal cells, not characters, or a path with a wide
    character in it overflows the column it was measured into.

Every one of those is a line that could go without another test in either
repository noticing.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.which_file import as_shown  # noqa: E402

_HOME = "/home/somebody"


def _at_home(home=_HOME):
    """Pin the home directory: `~` is otherwise whoever is running the tests."""
    return mock.patch.dict(os.environ, {"HOME": home})


class TestNothingToShow(unittest.TestCase):

    def test_no_path_is_the_empty_string(self):
        self.assertEqual(as_shown(""), "")
        self.assertEqual(as_shown("", "/p", 20), "")


class TestTheProjectComesOffTheFront(unittest.TestCase):

    def test_a_root_directory_is_an_answer(self):
        self.assertEqual(
            as_shown("/home/test/proj/src/app.py", "/home/test/proj"),
            "src/app.py")

    def test_a_trailing_slash_on_the_root_changes_nothing(self):
        self.assertEqual(as_shown("/home/test/proj/a.py", "/home/test/proj/"),
                         "a.py")

    def test_a_root_is_a_directory_and_not_a_prefix(self):
        """`/home/test/projX` is a different project that starts the same."""
        with _at_home():
            self.assertEqual(as_shown("/home/test/projX/a.py",
                                      "/home/test/proj"),
                             "/home/test/projX/a.py")

    def test_a_name_is_a_whole_component(self):
        """`agentwatch` has the name and not the path, so it looks for it."""
        self.assertEqual(as_shown("/home/somebody/relay/src/app.py", "relay"),
                         "src/app.py")

    def test_a_name_does_not_match_a_project_that_merely_starts_the_same(self):
        """`relayed` is a different repository, and shortening it lies."""
        with _at_home():
            self.assertEqual(as_shown("/home/somebody/relayed/x.py", "relay"),
                             "~/relayed/x.py")

    def test_a_name_does_not_match_one_that_merely_ends_the_same(self):
        """And `myrelay` is a third one, caught at the other end."""
        with _at_home():
            self.assertEqual(as_shown("/home/somebody/myrelay/x.py", "relay"),
                             "~/myrelay/x.py")

    def test_a_project_directly_under_the_root_is_still_found(self):
        """Unusual, and the one place the match sits at position zero."""
        self.assertEqual(as_shown("/relay/x.py", "relay"), "x.py")

    def test_no_project_leaves_the_path_where_it_is(self):
        with _at_home():
            self.assertEqual(as_shown("/home/somebody/proj/a.py"),
                             "~/proj/a.py")


class TestAFileOutsideTheProjectIsStillFindable(unittest.TestCase):
    """The bug this module was written for.

    The digest used to fall back to the basename, so a session that edited
    `~/notes/todo.md` and one that edited `/etc/todo.md` both said `todo.md`,
    and neither said where.  Two `cli.py` from two repositories were the same
    line twice.
    """

    def test_under_home_it_becomes_a_tilde(self):
        with _at_home():
            self.assertEqual(as_shown("/home/somebody/notes/todo.md",
                                      "/home/somebody/proj"),
                             "~/notes/todo.md")

    def test_outside_home_it_stays_whole(self):
        with _at_home():
            self.assertEqual(as_shown("/etc/hosts", "/home/somebody/proj"),
                             "/etc/hosts")

    def test_the_home_directory_itself_is_not_a_prefix(self):
        """`~` for the home directory, not `~` for anything starting with it.

        `/home/somebodyelse/x` shares the string and shares nothing else.
        """
        with _at_home():
            self.assertEqual(as_shown("/home/somebodyelse/x.py"),
                             "/home/somebodyelse/x.py")

    def test_a_home_of_slash_shortens_nothing(self):
        """A `~` in front of every path on the disk says nothing at all.

        Rare, but it is what a daemon account or a bare container gives you,
        and the answer there is to leave the paths alone.
        """
        with _at_home("/"):
            self.assertEqual(as_shown("/etc/hosts"), "/etc/hosts")


class TestRoomIsTakenOffTheFront(unittest.TestCase):

    def test_a_path_that_fits_is_untouched(self):
        self.assertEqual(as_shown("/p/src/app.py", "/p", 40), "src/app.py")

    def test_a_path_that_exactly_fills_the_room_is_not_cut(self):
        """The room is what there is, not one less than what there is."""
        self.assertEqual(as_shown("/p/abc.py", "/p", 6), "abc.py")

    def test_no_room_asked_for_means_no_cutting(self):
        long = "/p/" + "nested/" * 20 + "app.py"
        self.assertEqual(as_shown(long, "/p"), "nested/" * 20 + "app.py")

    def test_directories_go_and_the_file_stays(self):
        shown = as_shown("/p/" + "nested/" * 8 + "app.py", "/p", 20)
        self.assertTrue(shown.endswith("app.py"), shown)
        self.assertTrue(shown.startswith("…/"), shown)
        self.assertLessEqual(len(shown), 20)

    def test_it_keeps_as_many_directories_as_it_has_room_for(self):
        """The room is there to be used.

        Cutting straight to the last two parts threw away directories the row
        had space to show, and where a file sits is most of what tells two
        files of the same name apart.
        """
        tight = as_shown("/p/" + "aa/" * 10 + "app.py", "/p", 20)
        roomy = as_shown("/p/" + "aa/" * 10 + "app.py", "/p", 32)
        self.assertGreater(len(roomy), len(tight))
        self.assertLessEqual(len(roomy), 32)
        for shown in (tight, roomy):
            self.assertTrue(shown.endswith("/app.py"), shown)

    def test_one_name_too_wide_keeps_its_front(self):
        """The other way round, and on purpose.

        Directories are dropped from the front because the end of a path is
        the file.  Inside a name it reverses: `test_the_note_about…` is what
        you recognise it by, and it is what every other column in these tools
        does with a string too long for it.
        """
        self.assertEqual(as_shown("/p/" + "n" * 50, "/p", 10), "n" * 9 + "…")

    def test_the_name_kept_is_the_file_and_not_the_first_directory(self):
        """With directories in front of it, the last part is still the file.

        The case above has only one part, so it cannot tell the two apart.
        """
        self.assertEqual(as_shown("/p/dir/" + "n" * 50, "/p", 10),
                         "n" * 9 + "…")

    def test_a_single_cell_is_the_mark_and_nothing_else(self):
        self.assertEqual(as_shown("/p/app.py", "/p", 1), "…")

    def test_no_room_at_all_shows_nothing(self):
        self.assertEqual(as_shown("/p/app.py", "/p", 0), "")


class TestItIsMeasuredInCellsAndNotCharacters(unittest.TestCase):

    def test_a_wide_path_is_cut_by_what_it_is_drawn_in(self):
        """Seventeen characters, twenty-seven cells.

        A column told to hold twenty would have taken this whole path on a
        `len` and then been overrun by seven, which is the fault the family's
        `display_width` exists for -- and this was the one path left counting
        characters.
        """
        path = "/p/日本語のディレクトリ/app.py"
        self.assertEqual(len("日本語のディレクトリ/app.py"), 17)
        self.assertEqual(as_shown(path, "/p", 20), "…/app.py")

    def test_a_wide_name_is_cut_inside_itself_by_cells(self):
        shown = as_shown("/p/" + "日" * 20, "/p", 9)
        self.assertEqual(shown, "日" * 4 + "…")


if __name__ == "__main__":
    unittest.main()
