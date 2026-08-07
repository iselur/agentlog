"""One answer to "where are the logs", reached by everything that asks.

Claude Code writes under ``~/.claude/projects`` and Codex under
``~/.codex/sessions``.  That fact was spelled out four times: the finder, the
sentence printed when it finds nothing, the guard that refuses to write on top
of a log, and the walk the live view does.

The four fail differently, and that is why this file exists rather than one
test of `log_dirs` returning two strings.  The finder looking in the wrong
place prints "no sessions" -- wrong, but audible.  The **guard** looking in the
wrong place says nothing at all: it does not refuse, it waves the write
through, and a digest lands on top of a day's work.  So the tests below are
mostly about the *agreement* between the askers, not the answer itself.  A
change that moved one copy and not another used to pass every test here.

Two things are deliberately not folded into the shared roster, and each has a
test saying what breaks if somebody folds them in later:

* the home directory, because ``AGENTLOG_HOME`` and ``AGENTWATCH_HOME`` are
  different names on purpose and one of the two commands errors on a directory
  it was handed;
* ``realpath``, because the guard has to see through a symlinked home to answer
  at all, while the other three call sites *print* their directory and must
  print the one the person recognises as theirs.
"""

from __future__ import annotations

import ast
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentlog import cli  # noqa: E402
from agentlog.parser import find_sessions  # noqa: E402
from agentlog.where_the_logs_are import SOURCES, log_dirs  # noqa: E402
from tests.fixtures import (  # noqa: E402
    claude_user,
    codex_session_meta,
    codex_user_message,
    make_claude_project,
    make_codex_dir,
)

_ROSTER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "agentlog", "where_the_logs_are.py")


class TestTheRoster(unittest.TestCase):
    """What `log_dirs` answers, on its own."""

    def test_it_names_the_two_agents_in_the_order_sources_gives(self):
        # The order is part of the answer: a digest that names its sources
        # names them the same way every run, and a list that sorts differently
        # on a different box is a diff nobody can explain.
        got = log_dirs("/home/you")
        self.assertEqual([source for source, _, _ in got], list(SOURCES))
        self.assertEqual(
            got,
            [("claude", "Claude Code", "/home/you/.claude/projects"),
             ("codex", "Codex", "/home/you/.codex/sessions")])

    def test_a_directory_that_does_not_exist_still_comes_back(self):
        # The ordinary case is a box with one of the two agents on it.  Filter
        # here and the sentence saying where it looked stops naming the place
        # that was empty, which is the one thing the reader wants to know.
        empty = tempfile.mkdtemp(prefix="agentlog-roster-")
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        directories = [d for _, _, d in log_dirs(empty)]
        self.assertEqual(len(directories), len(SOURCES))
        for directory in directories:
            self.assertFalse(os.path.exists(directory), directory)

    def test_no_home_means_this_process_s_home(self):
        self.assertEqual(log_dirs(None), log_dirs(os.path.expanduser("~")))

    def test_an_empty_home_is_no_home_rather_than_the_root_of_the_disk(self):
        # `--home ""` reaches here as "".  Joined literally it gives
        # `.claude/projects`, a relative path read against whatever directory
        # the command happened to start in.
        self.assertEqual(log_dirs(""), log_dirs(None))

    def test_the_directory_is_not_resolved(self):
        # A home reached through a symlink is what the person typed, and it is
        # what three of the four call sites print back at them.  `realpath`
        # belongs at the fourth -- see the guard tests below.
        real = tempfile.mkdtemp(prefix="agentlog-real-")
        self.addCleanup(shutil.rmtree, real, ignore_errors=True)
        link = real + "-link"
        os.symlink(real, link)
        self.addCleanup(os.unlink, link)
        for _, _, directory in log_dirs(link):
            self.assertTrue(directory.startswith(link + os.sep), directory)


class TestEverybodyAsksTheSameQuestion(unittest.TestCase):
    """The finder, the guard and the sentence agree because they share a source.

    Each test here fails if one copy of the layout moves without the others,
    which is the failure the shared module exists to make impossible.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="agentlog-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def test_the_guard_refuses_a_write_into_every_directory_on_the_roster(self):
        # The silent failure, tested directly: for each place the tools read
        # from, a file inside it must be refused.  Add a third agent to the
        # roster and this test covers it without being edited.
        for source, _, directory in log_dirs(self.home):
            os.makedirs(directory, exist_ok=True)
            target = os.path.join(directory, "digest.md")
            reason = cli._refuses_to_write(target, self.home)
            self.assertIsNotNone(
                reason,
                "would have written a digest inside the {} logs at {}"
                .format(source, target))
            self.assertIn("never writes to the logs it reads", reason)

    def test_the_guard_refuses_the_log_directory_itself(self):
        # Not the same test as the one above: the guard asks whether the target
        # is *under* a log directory, and a path that **is** one is the case
        # that check misses.  `agentlog --md ~/.claude/projects` then gets past
        # the promise and dies on an IsADirectoryError from deep inside the
        # writer, which reads as a broken tool rather than a refused write.
        for _, _, directory in log_dirs(self.home):
            os.makedirs(directory, exist_ok=True)
            reason = cli._refuses_to_write(directory, self.home)
            self.assertIsNotNone(
                reason, "said nothing about being handed {} itself"
                .format(directory))
            self.assertIn("never writes to the logs it reads", reason)

    def test_the_guard_sees_through_a_symlinked_home(self):
        # `/home` is a link to `/mnt/home` on plenty of boxes.  Compare the
        # spellings rather than the places and the guard says "fine" about the
        # session log directory itself.
        real_home = tempfile.mkdtemp(prefix="agentlog-realhome-")
        self.addCleanup(shutil.rmtree, real_home, ignore_errors=True)
        linked_home = real_home + "-link"
        os.symlink(real_home, linked_home)
        self.addCleanup(os.unlink, linked_home)

        for _, _, directory in log_dirs(real_home):
            os.makedirs(directory, exist_ok=True)
        # Asked about the real path, told about the linked one, and vice versa.
        under_real = os.path.join(real_home, ".claude", "projects", "out.md")
        under_link = os.path.join(linked_home, ".claude", "projects", "out.md")
        self.assertIsNotNone(cli._refuses_to_write(under_real, linked_home))
        self.assertIsNotNone(cli._refuses_to_write(under_link, real_home))

    def test_a_path_outside_them_is_still_allowed(self):
        # The other half: a guard that refuses everything keeps the promise and
        # breaks the command, and no test above would notice.
        outside = os.path.join(self.home, "digest.md")
        self.assertIsNone(cli._refuses_to_write(outside, self.home))

    def test_the_sentence_names_the_places_that_were_looked_in(self):
        # "No sessions found, try looking in X" naming an X nothing read is a
        # wrong answer to the only question the reader has.
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            cli._no_sessions_msg(self.home)
        screen = out.getvalue()
        for _, shown_as, directory in log_dirs(self.home):
            # The name has to be on the *same line* as the directory.  The
            # sentence underneath already says "Claude Code (claude) or Codex
            # (codex)", so looking for the name anywhere on the screen passes
            # whatever the list above is labelled with -- a mutant that
            # labelled the rows `claude:` and `codex:` survived that version of
            # this test.
            rows = [line for line in screen.splitlines() if directory in line]
            self.assertEqual(len(rows), 1,
                             "expected one row naming {}:\n{}"
                             .format(directory, screen))
            self.assertTrue(
                rows[0].strip().startswith(shown_as + ":"),
                "the row for {} is labelled {!r}, not {!r}"
                .format(directory, rows[0].strip(), shown_as + ":"))

    def test_the_finder_reads_the_directories_the_roster_names(self):
        # The fixture spells the layout out by hand, on purpose.  Written
        # through `log_dirs` it would move wherever the roster moved and pass
        # over a roster pointing at the wrong place -- the exact bug.  Two
        # independent statements of one fact is what a test *is*; four
        # independent statements inside the tool was the problem.
        ts = "2026-01-01T09:00:00Z"
        make_claude_project(self.home, "a-project",
                            [[claude_user("s-claude", ts)]])
        codex_dir = make_codex_dir(self.home)
        with open(os.path.join(codex_dir, "rollout-s-codex.jsonl"),
                  "w", encoding="utf-8") as fh:
            for rec in (codex_session_meta("s-codex", "/home/test/x", ts),
                        codex_user_message(ts)):
                fh.write(json.dumps(rec) + "\n")

        sessions, sources, _unusable = find_sessions(home_dir=self.home)
        self.assertEqual(len(sessions), 2, sessions)
        # Named the way the roster names them, in the roster's order.
        self.assertEqual(sources,
                         [shown for _, shown, _ in log_dirs(self.home)])


class TestWhatWasLeftOutOfTheRoster(unittest.TestCase):
    """The two facts the shared module deliberately does not know.

    Both would widen its interface to the width of the thing behind it.  These
    say what stops working if a later change folds them in anyway.
    """

    def test_the_roster_never_reads_the_environment(self):
        # agentwatch reads AGENTWATCH_HOME.  If the roster started reading
        # AGENTLOG_HOME, agentwatch would silently follow agentlog's home.
        # Read off the parsed code, not the text: the docstring explains this
        # decision and says "environment" while doing so, and a substring
        # search that its own explanation fails is a test nobody can keep.
        with open(_ROSTER, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        reads = {
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in ("environ",
                                                                 "getenv")}
        self.assertEqual(reads, set(),
                         "the roster reads the environment: os.{}"
                         .format(", os.".join(sorted(reads))))

    def test_the_home_the_command_uses_beats_the_environment(self):
        # The other side of that: the *caller* is where the env var is read,
        # and an explicit --home still wins over it.
        typed = tempfile.mkdtemp(prefix="agentlog-typed-")
        self.addCleanup(shutil.rmtree, typed, ignore_errors=True)
        other = tempfile.mkdtemp(prefix="agentlog-env-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        old = os.environ.get("AGENTLOG_HOME")
        os.environ["AGENTLOG_HOME"] = other
        try:
            resolved = cli._log_dirs(typed)
        finally:
            if old is None:
                os.environ.pop("AGENTLOG_HOME", None)
            else:
                os.environ["AGENTLOG_HOME"] = old
        self.assertTrue(all(d.startswith(os.path.realpath(typed))
                            for d in resolved), resolved)


if __name__ == "__main__":
    unittest.main()
