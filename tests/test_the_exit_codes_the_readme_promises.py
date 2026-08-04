"""The exit codes the README promises, from real runs of the real command.

    Exit codes: 0 normal, 2 usage or argument error, 130 stopped by ctrl-c,
    141 the reader hung up (`agentlog today | head`, or `| less` quit with
    `q`). The last two are deliberately not 0: a digest that was cut off
    short reported nothing about your day, and `agentlog today > digest.md
    && mail-it` should not mail half of one.

Two of those already have tests, because producing them means sending signals
(test_interrupt, test_broken_pipe).  What was uncovered is the ordinary half:
nothing ran the command for each everyday case, and nothing read the README's
own sentence.

The distinction that carries weight here is 0 against 2, and this tool has an
unusual amount riding on it.  `agentlog today` finding nothing is a *normal*
0 — you did not use an agent today, which is an answer, not a failure.  A
mistyped day is a 2.  Both print little and both look like "nothing here" on
a terminal, so the number is the only thing telling them apart, and a nightly
`agentlog today > digest.md && mail-it` is reading it.

There is no 1 anywhere, deliberately: nothing this tool does can fail in the
"the command was fine and did not work" sense — it reads logs that are either
there or not.  A 1 appearing would mean something got a code nobody documented
and no caller knows how to read, so it is asserted against by name.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

README = os.path.join(_ROOT, "README.md")
CLI_SOURCE = os.path.join(_ROOT, "agentlog", "cli.py")

# "0 normal, 2 usage or argument error, 130 stopped by ctrl-c" — bare numbers,
# not backticked, so the pattern is a whole-word one.  It is deliberately
# scoped to that one paragraph: the README is full of counts and dates.
_DOCUMENTED = re.compile(r"(?<![\w.-])(\d{1,3})(?![\w.-])")


def readme() -> str:
    with open(README, encoding="utf-8") as handle:
        return handle.read()


def documented_codes(text):
    """The codes the README's exit-code paragraph lists."""
    start = text.find("Exit codes:")
    if start < 0:
        return set()
    return {int(code) for code in _DOCUMENTED.findall(text[start:].split("\n\n")[0])}


def source_codes():
    """Every constant exit code cli.py produces."""
    with open(CLI_SOURCE, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    codes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Return):
            values = [node.value]
        elif (isinstance(node, ast.Call)
              and getattr(node.func, "attr", None) == "exit"):
            values = [node.args[0]] if node.args else []
        else:
            continue
        for value in list(values):
            if isinstance(value, ast.IfExp):
                values += [value.body, value.orelse]
        for value in values:
            if (isinstance(value, ast.Constant)
                    and isinstance(value.value, int)
                    and not isinstance(value.value, bool)):
                codes.add(value.value)
    return codes


class TestTheExitCodesTheREADMEPromises(unittest.TestCase):
    def setUp(self):
        # An empty home, so every run below is about the command line rather
        # than about whatever happens to be in the real ~/.claude.
        self.home = tempfile.mkdtemp(prefix="al-exitcode-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "agentlog", *argv, "--home", self.home],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))

    # -- the prose and the code -------------------------------------------

    def test_the_readme_still_promises_exit_codes(self):
        # Without this the comparison below passes on an empty set, which is
        # what deleting the sentence looks like.
        self.assertGreaterEqual(len(documented_codes(readme())), 4,
                                "no exit-code sentence left in README.md")

    def test_the_documented_codes_are_the_ones_the_code_can_return(self):
        self.assertEqual(
            sorted(documented_codes(readme())), sorted(source_codes()),
            "README.md's exit codes and the ones agentlog/cli.py returns "
            "disagree")

    # -- and the runs -----------------------------------------------------

    def test_a_day_with_nothing_in_it_is_zero(self):
        # The one most likely to drift into an error code, because it is the
        # one that prints the least.  Nothing was wrong; there is nothing to
        # report, which is a report.
        proc = self.run_cli("today")
        self.assertEqual(proc.returncode, 0,
                         "an empty day was reported as a failure:\n"
                         + proc.stdout + proc.stderr)

    def test_an_unknown_command_is_two(self):
        proc = self.run_cli("yesteday")
        self.assertEqual(proc.returncode, 2,
                         "a mistyped command did not exit 2:\n"
                         + proc.stdout + proc.stderr)

    def test_an_unknown_flag_is_two(self):
        proc = self.run_cli("today", "--not-a-flag")
        self.assertEqual(proc.returncode, 2,
                         "an unknown flag did not exit 2:\n"
                         + proc.stdout + proc.stderr)

    def test_a_date_that_is_not_a_date_is_two(self):
        proc = self.run_cli("since", "last-tuesday-ish")
        self.assertEqual(proc.returncode, 2,
                         "an unparseable date did not exit 2:\n"
                         + proc.stdout + proc.stderr)

    def test_a_limit_that_is_not_a_number_is_two(self):
        proc = self.run_cli("list", "--limit", "lots")
        self.assertEqual(proc.returncode, 2,
                         "a non-numeric --limit did not exit 2:\n"
                         + proc.stdout + proc.stderr)

    def test_an_empty_day_and_a_mistyped_one_do_not_answer_the_same(self):
        # Both print almost nothing.  The number is the only thing that says
        # which happened, and a wrapper mailing a digest reads only that.
        empty = self.run_cli("today")
        mistyped = self.run_cli("since", "last-tuesday-ish")
        self.assertNotEqual(
            empty.returncode, mistyped.returncode,
            "a quiet day and a typo answer the same code, so nothing "
            "downstream can tell them apart")

    def test_nothing_ever_answers_one(self):
        # 1 is not in the README, so nothing knows how to read it.  This is
        # the assertion that keeps it that way as commands get added.
        self.assertNotIn(1, source_codes(),
                         "agentlog/cli.py returns 1 somewhere, and the README "
                         "does not say what it means")
        for argv in (("today",), ("yesteday",), ("since", "last-tuesday-ish"),
                     ("list", "--limit", "lots"), ("show", "no-such-session")):
            proc = self.run_cli(*argv)
            self.assertNotEqual(
                proc.returncode, 1,
                "`agentlog {}` answered 1, which the README does not "
                "document:\n{}".format(" ".join(argv),
                                       proc.stdout + proc.stderr))


if __name__ == "__main__":
    unittest.main()
