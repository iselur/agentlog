"""The sentence itself, in every shape a caller can ask for.

`test_unread_files.py` is about the note *arriving* -- that `today` and `list`
and a saved report all admit the day is short of the disk.  It checks for two
words on the screen and stops there on purpose, because the words are not that
file's to choose: they live in `unusable.py`, which `agentwatch` prints from as
well, and pinning them in one tool's tests would make the other tool's screen
change a failure over here.

This file is the other half.  It reads the module directly and says what comes
out of it, one shape per test, because each shape is a decision somebody made:

  * one file reads "1 session log is", not "1 session logs are";
  * two reasons at once read as one clause with counts, one reason reads as
    itself, because "2 session logs are not shown — 2 could not be read" says
    the number twice;
  * a caller with no room for paths gets told how to ask for them;
  * a caller with room for three and five to show says so rather than trailing
    off;
  * and a caller holding a mix says which file had which problem, since that is
    the whole reason the reason is carried.

Every one of those is a line somebody could delete without any other test in
either repository noticing.  Which is the definition of a line worth a test.
"""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.unusable import (  # noqa: E402
    ALL,
    NO_RECORDS,
    UNREADABLE,
    note_about,
)

_A = "/home/val/.claude/projects/p/a.jsonl"
_B = "/home/val/.claude/projects/p/b.jsonl"


class TestNothingToSay(unittest.TestCase):

    def test_no_entries_is_the_empty_string(self):
        """The ordinary case, so a caller can print it unconditionally.

        Returning `None` would be the other reasonable answer and it is the
        wrong one: `print(note or ...)` and `if note:` both read the same on a
        string, and one caller here appends it to a screen it is already
        building.
        """
        self.assertEqual(note_about([]), "")
        self.assertEqual(note_about([], ALL), "")
        self.assertEqual(note_about((), 3), "")


class TestOneFileIsNotFiles(unittest.TestCase):

    def test_one_reads_as_one(self):
        head = note_about([(_A, UNREADABLE)], ALL).splitlines()[0]
        self.assertIn("1 session log is not shown", head)
        self.assertNotIn("logs", head)

    def test_two_read_as_two(self):
        head = note_about([(_A, UNREADABLE), (_B, UNREADABLE)],
                          ALL).splitlines()[0]
        self.assertIn("2 session logs are not shown", head)


class TestWhyItIsNotShown(unittest.TestCase):

    def test_one_reason_is_not_counted_twice(self):
        """`2 session logs are not shown — could not be read`.

        And not `— 2 could not be read`: the count is already in the first half
        of the sentence, and a reader who meets it twice starts looking for the
        two groups it must be distinguishing.
        """
        head = note_about([(_A, UNREADABLE), (_B, UNREADABLE)],
                          ALL).splitlines()[0]
        self.assertTrue(head.endswith("— " + UNREADABLE), head)

    def test_two_reasons_are_one_clause_with_counts(self):
        """Here the counts are the point -- they are what tells the two apart.

        The order is the reasons', sorted, and not the files': a note whose
        clause reorders itself depending on which log happened to be locked
        first is a note that reads as two different notes.
        """
        head = note_about([(_B, UNREADABLE), (_A, NO_RECORDS)],
                          ALL).splitlines()[0]
        self.assertTrue(head.endswith(
            "— 1 {}, 1 {}".format(UNREADABLE, NO_RECORDS)), head)

    def test_the_two_reasons_are_different_sentences(self):
        """Otherwise carrying the reason through buys nothing.

        A file that will not open is a chmod.  A file that opens with nothing
        usable in it is not -- there is nothing to chmod, the bytes are the
        problem -- and telling somebody to fix the permissions on it sends them
        after a fix that cannot work.
        """
        self.assertNotEqual(UNREADABLE, NO_RECORDS)


class TestHowManyPathsThereIsRoomFor(unittest.TestCase):

    def _detail(self, *args):
        return [line.strip() for line in note_about(*args).splitlines()[1:]]

    def test_no_room_offers_the_flag_instead(self):
        self.assertEqual(self._detail([(_A, UNREADABLE)], 0),
                         ["(run with --verbose to see which)"])

    def test_no_room_is_the_default_because_most_callers_are_reports(self):
        self.assertEqual(note_about([(_A, UNREADABLE)]),
                         note_about([(_A, UNREADABLE)], 0))

    def test_all_names_every_one_of_them(self):
        entries = [("/p/{}.jsonl".format(i), UNREADABLE) for i in range(9)]
        self.assertEqual(self._detail(entries, ALL),
                         sorted(path for path, _why in entries))

    def test_room_for_three_out_of_five_says_so(self):
        """The count matters more than the names once they run out.

        Trailing off after the third would leave a reader counting the lines to
        find out how bad it is, and getting three.
        """
        entries = [("/p/{}.jsonl".format(i), UNREADABLE) for i in range(5)]
        self.assertEqual(self._detail(entries, 3),
                         ["/p/0.jsonl", "/p/1.jsonl", "/p/2.jsonl",
                          "... and 2 more"])

    def test_room_for_more_than_there_are_does_not_trail_off(self):
        """`... and 0 more` is a line saying a file is missing from a list of
        files that are missing."""
        entries = [("/p/{}.jsonl".format(i), UNREADABLE) for i in range(2)]
        self.assertEqual(self._detail(entries, 3),
                         ["/p/0.jsonl", "/p/1.jsonl"])

    def test_the_paths_are_sorted_however_they_arrived(self):
        """Two runs against one unchanged machine say one thing.

        The order files come back in is the filesystem's business and it is not
        stable across machines, so a note that passes it through is a note that
        reads differently for two people looking at the same problem.
        """
        entries = [(_B, UNREADABLE), (_A, UNREADABLE)]
        self.assertEqual(self._detail(entries, ALL), [_A, _B])


class TestWhichFileHadWhichProblem(unittest.TestCase):

    def test_a_mix_says_which_is_which(self):
        """The only case where a path alone is not enough.

        Two problems on screen and two paths under them, with nothing joining
        them up, is a note that has told you everything except the thing you
        would act on.
        """
        detail = note_about([(_A, UNREADABLE), (_B, NO_RECORDS)],
                            ALL).splitlines()[1:]
        self.assertEqual([line.strip() for line in detail],
                         ["{}  ({})".format(_A, UNREADABLE),
                          "{}  ({})".format(_B, NO_RECORDS)])

    def test_one_reason_leaves_the_paths_alone(self):
        """The headline already said it, once, for all of them."""
        detail = note_about([(_A, UNREADABLE), (_B, UNREADABLE)],
                            ALL).splitlines()[1:]
        self.assertEqual([line.strip() for line in detail], [_A, _B])


class TestItIsOneNoteAndNotSeveral(unittest.TestCase):

    def test_the_word_note_appears_once(self):
        """It is printed beside other lines a tool is already writing.

        `agentwatch` puts it under `watching 3 sessions`, `agentlog` under a
        digest.  A second `note:` halfway down reads as a second problem.
        """
        text = note_about([(_A, UNREADABLE), (_B, NO_RECORDS)], ALL)
        self.assertEqual(text.count("note:"), 1, text)

    def test_the_paths_sit_under_the_sentence_and_not_beside_it(self):
        text = note_about([(_A, UNREADABLE)], ALL)
        first, second = text.splitlines()
        self.assertFalse(first.startswith(" "), first)
        self.assertTrue(second.startswith("      "), repr(second))


if __name__ == "__main__":
    unittest.main()
