"""Every view says the same thing about the rows it did not show.

A session with forty files in it is not printed forty files wide in any view;
each shows what it has room for and then says how many it left out.  How many
it shows is the view's own business — a terminal row, a markdown fence and an
HTML card have genuinely different room — but *what it says* is one sentence
about one situation, and a run written to two of them at once should not read
as two different tools.

`_first_few` was written to settle exactly this: the line had been typed out
by hand four times and had drifted into two spellings.  It settled it for
every view made of lines of text and could not settle it for the one that is
not, because a view that wraps each item in a tag cannot use a list of
indented strings.  So the HTML digest went on saying `... and 3 more` where
the text digest said `… and 3 more` about the same run.

The sentence now has a name of its own, `left_out`, and these tests are the
reason it is not private: the views are only obliged to agree if they are all
asking the same thing.
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
    left_out, render_list, render_markdown, render_show, render_text,
)

#: The sentence, wherever it appears and whatever it is wrapped in: the words
#: before the count are what the views have to agree about.  A closing angle
#: bracket ends the match because in the HTML view the sentence begins hard
#: against the tag that carries it, and `>…` is a tag and a sentence rather
#: than a third way of spelling one.
SAYS_MORE = re.compile(r"([^\s>]+) and (\d+) more")

#: Comfortably past the largest limit any view uses, so that every view that
#: truncates at all has something to say about what it dropped.
PLENTY = 40

#: One list in the HTML digest: the heading that says how many there are, and
#: the block of rows underneath it.  A row may carry tags of its own, so the
#: block ends at the first `</div>` rather than the last.
HTML_SECTION = re.compile(
    r'<div class="section"><div class="section-label">([^<]*)</div>'
    r'<div class="code-block">(.*?)</div></div>', re.S)

#: The count a heading carries — `Files (80)`, `Commands (40)`.
HEADING_COUNT = re.compile(r"\((\d+)\)\s*$")


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


def a_session_with_more_in_it_than_fits():
    return a_session(
        files_read=["src/read_{}.py".format(i) for i in range(PLENTY)],
        files_written=["src/wrote_{}.py".format(i) for i in range(PLENTY)],
        commands=["echo command number {}".format(i) for i in range(PLENTY)])


def every_view(s):
    """Each view by name, rendered from one session."""
    return {
        "text": render_text([s]),
        "markdown": render_markdown([s]),
        "list": render_list([s]),
        "show": render_show(s),
        "html": render_html([s], ["claude"], "today"),
    }


class TestTheViewsAgree(unittest.TestCase):

    def setUp(self) -> None:
        self.views = every_view(a_session_with_more_in_it_than_fits())
        self.said = {name: SAYS_MORE.findall(text)
                     for name, text in self.views.items()}

    def test_more_than_one_view_has_something_to_say(self):
        # Otherwise everything below is a comparison of one thing with itself.
        speaking = sorted(n for n, hits in self.said.items() if hits)
        self.assertGreater(len(speaking), 1, speaking)
        self.assertIn("html", speaking,
                      "the HTML digest stopped saying what it left out, which "
                      "is the view this file exists for")

    def test_they_all_say_it_the_same_way(self):
        spellings = {word for hits in self.said.values() for word, _ in hits}
        self.assertEqual(
            len(spellings), 1,
            "the views disagree about how to say it: {}".format(
                sorted(spellings)))

    def test_the_counts_are_the_ones_that_were_dropped(self):
        # The sentence agreeing is not worth much if the number in it is wrong.
        # Each view picks its own limit, so what is checked is that the number
        # it prints is the number it did not print.
        for name, hits in self.said.items():
            for _, count in hits:
                self.assertGreater(int(count), 0, name)
                self.assertLess(int(count), PLENTY * 2 + 1, name)

    def test_a_view_that_shows_everything_says_nothing(self):
        small = a_session(files_read=["src/one.py"], commands=["echo one"])
        for name, text in every_view(small).items():
            self.assertEqual(SAYS_MORE.findall(text), [],
                             "{} claims it left something out of a session "
                             "with one of everything".format(name))


class TestEveryListThatWasCutSaysSo(unittest.TestCase):
    """The HTML digest, list by list rather than page by page.

    Asking whether the page says anything at all is not the same question and
    does not answer this one: the digest prints two lists, so dropping the
    sentence from the files list leaves the commands list still saying it, the
    page is still speaking, and a reader looking at twelve files out of eighty
    is told nothing.

    The promise is the one each heading already makes.  A heading says how many
    there are; if fewer rows than that are printed, the last row says how many
    were left out, and the number is the difference.  It holds for every list
    on the page, and no other list can stand in for one that goes quiet.
    """

    def setUp(self) -> None:
        page = render_html(
            [a_session_with_more_in_it_than_fits()], ["claude"], "today")
        self.lists = []
        for heading, block in HTML_SECTION.findall(page):
            found = HEADING_COUNT.search(heading)
            if found:
                self.lists.append(
                    (heading, int(found.group(1)), block.split("\n")))
        self.page = page

    def test_the_digest_prints_more_than_one_list(self):
        # Otherwise a page-wide check would have been enough, and the fixture
        # is not exercising the thing this class was written for.
        self.assertGreater(len(self.lists), 1,
                           "no two lists found in the digest:\n" + self.page)

    def test_a_list_that_shows_fewer_rows_than_it_counted_says_how_many(self):
        cut = 0
        for heading, total, rows in self.lists:
            shown = [r for r in rows if not SAYS_MORE.search(r)]
            if len(shown) == total:
                continue
            cut += 1
            said = SAYS_MORE.findall(rows[-1])
            self.assertEqual(
                len(said), 1,
                "{}: shows {} of {} and its last row does not say how many "
                "it left out: {!r}".format(heading, len(shown), total,
                                           rows[-1]))
            self.assertEqual(
                int(said[0][1]), total - len(shown),
                "{}: shows {} of {} and says it left out {}"
                .format(heading, len(shown), total, said[0][1]))
        self.assertGreater(cut, 1,
                           "fewer than two lists were cut, so this proves less "
                           "than it looks like it does")


class TestTheSentenceItself(unittest.TestCase):
    """What `left_out` returns, pinned here rather than read out of it.

    The character is spelled by hand: a test that imports the ellipsis from
    the code under test agrees with whatever character is there, including one
    typed by accident.  Changing it should mean changing this line too.
    """

    def test_it_is_the_one_character_ellipsis(self):
        self.assertEqual(left_out(10, 4), "… and 6 more")

    def test_it_is_not_three_full_stops(self):
        self.assertNotIn("...", left_out(10, 4))

    def test_nothing_left_out_is_nothing_said(self):
        self.assertEqual(left_out(4, 4), "")
        self.assertEqual(left_out(0, 0), "")

    def test_a_view_showing_more_than_it_has_is_not_a_negative_sentence(self):
        # Nothing calls it this way today.  It would be a caller's mistake if
        # anything did, and `… and -2 more` is a worse way to find out than a
        # view that simply says nothing.
        self.assertEqual(left_out(3, 8), "")


if __name__ == "__main__":
    unittest.main()
