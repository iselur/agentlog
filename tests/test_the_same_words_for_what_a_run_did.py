"""Every view says what a run did in the same words, and can count to one.

`176 files edited · 874 commands · 75 errors` is one sentence about one
situation.  It had been typed out by hand in four places — the terminal
digest, the markdown document, the HTML digest and the summary line — and two
of those had drifted:

* the markdown document had no plural guard on two of its three counts, so a
  project with one command in it was reported as `1 commands`;
* only the summary line said what the files *were*.  Everywhere else the
  reader was told `176 files` and left to work out whether that meant read or
  written.  It means written, and there is no way to tell from the row.

`what_it_did` is now the only place the sentence exists, and these tests are
why it is not private: the views are only obliged to agree if they are all
asking the same thing.

The awkward number is one.  A fixture with plenty of everything in it cannot
see a missing plural guard — every count reads correctly in the plural — so
each view is rendered twice, once from a run with exactly one of each thing.
And each view is checked on its own: asking whether the *output as a whole*
ever says `1 commands` passes happily while one of four views says it, which
is the failure this file exists to catch.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from agentlog.html import render_html                          # noqa: E402
from agentlog.render import (                                  # noqa: E402
    render_markdown, render_text, summary_line, what_it_did,
)

#: A count of one followed by a plural — `1 files`, `1 commands`, `1 errors`,
#: `1 turns`.  Word boundaries on both sides so that `1 commands` is caught and
#: `21 commands` is not.
A_PLURAL_ONE = re.compile(r"\b1 (files|commands|errors|turns)\b")

#: What the sentence calls the files it counted.  A view saying `176 files`
#: has not said which files, so the word that matters is the one after it.
FILE_COUNT = re.compile(r"\b\d+ files? ?(\w*)")


def a_session(**overrides):
    """A session dict shaped the way the parser produces one."""
    start = datetime(2026, 7, 16, 10, 0).astimezone()
    base = {
        "id": "abc12345-0000-0000-0000-000000000000",
        "source": "claude",
        "project": "/home/test/myproject",
        "project_name": "myproject",
        "start": start,
        "end": start + timedelta(minutes=90),
        "duration_s": 5400.0,
        "models": ["claude-test"],
        "user_turns": 5,
        "files_read": [],
        "files_written": [],
        "commands": [],
        "errors": 0,
        "tokens_in": None,
        "tokens_out": None,
        "ai_title": None,
        "version": "2.1.0",
        "skipped_lines": 0,
    }
    base.update(overrides)
    return base


def one_of_everything():
    """A run with exactly one of each thing — the count that gives it away."""
    return a_session(user_turns=1, errors=1,
                     files_written=["src/only.py"],
                     commands=["echo the only command"])


def plenty_of_everything():
    return a_session(user_turns=9, errors=4,
                     files_written=["src/wrote_{}.py".format(i)
                                    for i in range(7)],
                     commands=["echo command {}".format(i) for i in range(6)])


def every_view(s):
    """Each view that reports what a run did, by name."""
    return {
        "digest": render_text([s]),
        "digest --verbose": render_text([s], verbose=True),
        "markdown": render_markdown([s]),
        "html": render_html([s], ["claude"], "today"),
        "summary line": summary_line([s]),
    }


class TestNoViewSaysOneOfSomethingPlural(unittest.TestCase):
    """One is the count that finds a missing plural guard, and only one is."""

    def test_the_views_are_reporting_the_counts_at_all(self):
        # Otherwise the loop below is checking five empty strings and would go
        # on passing after the sentence was deleted outright.
        for name, text in every_view(one_of_everything()).items():
            self.assertIn("1 command", text,
                          "{} does not report what the run did".format(name))

    def test_no_view_says_it(self):
        for name, text in every_view(one_of_everything()).items():
            self.assertEqual(
                A_PLURAL_ONE.findall(text), [],
                "{} counts to one and then uses the plural: {}".format(
                    name, sorted(set(A_PLURAL_ONE.findall(text)))))

    def test_the_plurals_are_still_there_when_there_are_several(self):
        # The opposite mistake — a guard that drops the `s` unconditionally
        # reads as correct to the test above and wrong to everybody else.
        for name, text in every_view(plenty_of_everything()).items():
            for word in ("files", "commands", "errors"):
                self.assertIn(word, text,
                              "{} has several of everything and does not say "
                              "'{}'".format(name, word))


class TestTheViewsUseTheSameWords(unittest.TestCase):
    """The sentence is one sentence, so no view may spell it its own way."""

    def test_they_all_say_which_files_they_counted(self):
        for name, text in every_view(plenty_of_everything()).items():
            found = FILE_COUNT.findall(text)
            self.assertTrue(found,
                            "{} does not count files".format(name))
            for after in found:
                self.assertEqual(
                    after, "edited",
                    "{} says '{} files {}' — a bare count of files does not "
                    "say whether they were read or written".format(
                        name, "N", after).replace(" ''", "'"))

    def test_more_than_one_view_is_speaking(self):
        # Otherwise the comparison above is a comparison of one thing with
        # itself, and the drift it exists to catch would go unseen.
        speaking = sorted(name for name, text
                          in every_view(plenty_of_everything()).items()
                          if FILE_COUNT.search(text))
        self.assertGreater(len(speaking), 1, speaking)


class TestTheSentenceItself(unittest.TestCase):
    """What `what_it_did` returns, pinned here rather than read out of it."""

    def test_it_is_the_three_phrases_in_order(self):
        self.assertEqual(what_it_did(176, 874, 75),
                         ["176 files edited", "874 commands", "75 errors"])

    def test_one_of_each_is_singular(self):
        self.assertEqual(what_it_did(1, 1, 1),
                         ["1 file edited", "1 command", "1 error"])

    def test_a_count_of_zero_is_not_mentioned(self):
        # A project with no errors should not have to say it has no errors.
        self.assertEqual(what_it_did(3, 0, 0), ["3 files edited"])
        self.assertEqual(what_it_did(0, 0, 0), [])

    def test_it_returns_phrases_rather_than_a_finished_line(self):
        # Two of the four callers put something in front of these and one puts
        # something after, so a caller that got a joined string back would have
        # to take it apart again — and taking it apart is how the spellings
        # drifted the first time.
        self.assertIsInstance(what_it_did(2, 2, 2), list)


if __name__ == "__main__":
    unittest.main()
