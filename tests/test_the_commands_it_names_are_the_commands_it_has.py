"""The four places this tool lists its own commands, held to the dispatcher.

agentlog has no subparsers.  Its commands are a single positional argument
matched by name in an if/elif chain, which means argparse does not know they
exist and cannot check anything about them: `agentlog yesteday` parses
perfectly, and the typo is only noticed at the bottom of the chain.

Everything that tells a person or an agent what the commands *are* is
therefore hand-written prose, in four separate places:

  - the `COMMAND` argument's help string, printed by `--help`
  - the epilog's worked examples, printed under it
  - the "unknown command" hint, printed when the chain falls through
  - the README's synopses

Four copies of one list, none of them generated, all of them read by somebody
deciding what to type.  A command added to the chain and not to the hint is
invisible; a command dropped from the chain and left in the hint is worse,
because the hint is printed *at the moment somebody already got it wrong* —
it is the one piece of text that has to be right, and it is the one nothing
was checking.

The other family test that would cover this, `test_every_synopsis_describes_
a_real_subcommand`, reads `parser._subparsers` and finds nothing here, so it
skips.  This is that check, written against the dispatcher instead.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.cli import _build_parser as build_parser
from agentlog import window

CLI_SOURCE = os.path.join(_ROOT, "agentlog", "cli.py")
WINDOW_SOURCE = os.path.join(_ROOT, "agentlog", "window.py")
README = os.path.join(_ROOT, "README.md")

# `agentlog` on its own is `today`, which argparse supplies as the default
# rather than the chain matching it, so it is not a name to be listed.
_WORD = re.compile(r"(?<![\w-])([a-z][a-z0-9-]*)(?![\w-])")


def dispatched_commands():
    """Every name this tool actually answers to, from the two places it decides.

    The chain is in two halves now.  `list` and `show` are matched in `cli`,
    where they belong: they take an id and print a thing.  The commands that
    name a stretch of time are matched in `window`, which is what a time
    command means, and that half declares its names as `PERIODS` and `DATED`
    rather than burying them in an if/elif.

    Both halves are read rather than written down: the `cli` half by walking
    its comparisons, the `window` half by asking the module for the tuples it
    dispatches on.  A list typed out here would be a fifth copy of exactly the
    thing being checked.
    """
    found = set(window.PERIODS) | set(window.DATED)
    with open(CLI_SOURCE, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        left = node.left
        if not (isinstance(left, ast.Attribute) and left.attr == "command"):
            continue
        right = node.comparators[0]
        if isinstance(node.ops[0], ast.Eq) and isinstance(right, ast.Constant):
            found.add(right.value)
        elif isinstance(node.ops[0], ast.In) and isinstance(right, (ast.Tuple, ast.List)):
            found.update(item.value for item in right.elts
                         if isinstance(item, ast.Constant))
    return found


def command_help():
    """The help string on the COMMAND positional."""
    for action in build_parser()._actions:
        if action.dest == "command":
            return action.help or ""
    return ""


def epilog():
    return build_parser().epilog or ""


def unknown_command_hint():
    """The `try: ...` lines printed when the chain falls through.

    In `window`, with the chain it is the fall-through of.  A hint that is
    printed at the moment somebody typed a command wrong belongs next to the
    code deciding which commands are right; keeping it in `cli` would have put
    two files between the list and the message about the list.

    Read as source, which means two things are in the text that a person
    reading the terminal never sees.  The f-string placeholders:
    `{args.command}` is the name of a variable, not a command being offered.
    And the escape sequences: `\\n` at the end of a line is a newline, but as
    source it is a backslash and the letter `n`, which reads as a one-letter
    command nobody has.  Both come out before anything counts words.
    """
    with open(WINDOW_SOURCE, encoding="utf-8") as handle:
        source = handle.read()
    start = source.find("unknown command")
    end = source.find('".format(', start)
    if start < 0 or end < 0:
        # Both ends, and "" rather than a slice, on purpose.  A missing end
        # marker used to leave `find` returning -1, which is a legal index:
        # the slice quietly became the rest of the file and every word in it
        # counted as a command being offered.  Nothing failed; the check just
        # stopped being one.
        return ""
    text = re.sub(r"\{[^}]*\}", " ", source[start:end])
    return re.sub(r"\\.", " ", text)


def readme() -> str:
    with open(README, encoding="utf-8") as handle:
        return handle.read()


class TestTheCommandsItNamesAreTheCommandsItHas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.commands = dispatched_commands()

    def test_the_dispatcher_was_actually_read(self):
        # Every assertion below is a subset check against this set, so an
        # empty one passes all of them and means nothing.  The AST walk is
        # looking for a very specific shape and would go quiet if the chain
        # were rewritten around, say, a dict lookup.
        self.assertGreaterEqual(
            len(self.commands), 5,
            "found {} commands in the dispatcher, which is not what the "
            "if/elif chain looks like — the walk needs updating"
            .format(sorted(self.commands)))
        self.assertIn("show", self.commands)
        self.assertIn("week", self.commands)

    def test_the_help_string_names_every_command(self):
        text = command_help()
        for command in sorted(self.commands):
            self.assertIn(command, _WORD.findall(text),
                          "`agentlog {}` works and `--help` does not list it"
                          .format(command))

    def test_the_hint_names_every_command(self):
        # This is the one printed to somebody who already typed something
        # wrong.  A command missing from here is a command they will not find.
        text = unknown_command_hint()
        self.assertTrue(text, "no unknown-command hint found in cli.py")
        for command in sorted(self.commands):
            self.assertIn(command, _WORD.findall(text),
                          "`agentlog {}` works, and the message shown to "
                          "somebody who mistyped a command does not mention it"
                          .format(command))

    def test_the_hint_does_not_name_a_command_that_is_gone(self):
        # The direction that actually misleads: being told to try something
        # that lands you back on the same error.
        offered = set(_WORD.findall(unknown_command_hint()))
        offered -= {"agentlog", "try", "unknown", "command", "id", "date", "day"}
        for name in sorted(offered):
            self.assertIn(
                name, self.commands,
                "the unknown-command hint offers `{}`, which the dispatcher "
                "does not answer to — following it lands on the same error"
                .format(name))

    def test_the_examples_under_help_all_run(self):
        # The epilog is what an agent reads first, being the last thing on
        # screen after `--help`.  Every example line must name a real command
        # or be the bare `agentlog`, which defaults to today.
        for line in epilog().splitlines():
            line = line.strip()
            if not line.startswith("agentlog"):
                continue
            words = line.split()
            if len(words) == 1:
                continue
            head = words[1]
            if head.startswith("--"):
                continue
            self.assertIn(
                head, self.commands,
                "`{}` is offered as an example and `{}` is not a command"
                .format(line, head))

    def test_the_readme_synopses_all_name_a_real_command(self):
        # The synopsis block is two columns — the command, then a gloss lined
        # up to the right of it — so the command ends at the first run of two
        # or more spaces.  Reading the whole line as one command makes the
        # gloss's first word look like an argument: `agentlog   same as:
        # agentlog today` documents the bare invocation, not a `same` command.
        text = readme()
        for block in re.findall(r"```[a-z]*\n(.*?)```", text, re.S):
            for line in block.splitlines():
                stripped = line.strip().lstrip("$ ").strip()
                if not stripped.startswith("agentlog "):
                    continue
                words = re.split(r"\s{2,}", stripped)[0].split()
                if len(words) == 1:
                    continue            # bare `agentlog`, which is `today`
                head = words[1]
                if head.startswith("-"):
                    continue
                self.assertIn(
                    head, self.commands,
                    "README.md shows `{}` and `{}` is not a command this tool "
                    "dispatches".format(stripped, head))


if __name__ == "__main__":
    unittest.main()
