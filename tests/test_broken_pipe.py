"""`agentlog today | head` is a normal thing to do, and it used to be a crash.

A digest is long.  Piping it into `head`, or into `less` and quitting with `q`,
or into `grep -q` that stops as soon as it has its answer — all of these close
the read end while we are still writing.  The next write fails with EPIPE,
Python raises `BrokenPipeError`, and with nobody catching it the interpreter
prints

    Exception ignored in: <_io.TextIOWrapper name='<stdout>' ...>
    BrokenPipeError: [Errno 32] Broken pipe

over the top of the output the person was reading, and exits 120 — or, when the
error escapes `main()` instead of the shutdown flush, a full traceback and exit
1.  Exit 1 is a verdict in this family, so that one is worse than noise.

141 is the shell's own spelling of "the reader hung up" (128 + SIGPIPE), the
same way 130 spells ctrl-c.  Neither is any command's answer, which is exactly
the point: a run that got cut off answered nothing, and must not be able to
impersonate a run that did.

The read end here is closed before the command writes a byte, so none of this
depends on how much output there is or on the size of the kernel's pipe buffer.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from tests.fixtures import a_now_that_keeps


# The oldest record here is an hour back, and it means "earlier today".  See
# fixtures.a_now_that_keeps for why that is not the same as an hour before now.
_NOW = a_now_that_keeps(60)


def _ago(seconds):
    return (_NOW - timedelta(seconds=seconds)).astimezone(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_with_no_reader(args, env=None):
    """Run the CLI with a stdout pipe whose read end is already closed."""
    read_fd, write_fd = os.pipe()
    os.close(read_fd)                       # the reader went away
    proc = subprocess.Popen(
        [sys.executable, "-m", "agentlog"] + list(args),
        stdout=write_fd, stderr=subprocess.PIPE, cwd=_ROOT,
        env=dict(os.environ, PYTHONPATH=_ROOT, **(env or {})))
    os.close(write_fd)
    _, err = proc.communicate(timeout=120)
    return proc.returncode, err.decode("utf-8", "replace")


def run_normally(args, env=None):
    proc = subprocess.Popen(
        [sys.executable, "-m", "agentlog"] + list(args),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=_ROOT,
        env=dict(os.environ, PYTHONPATH=_ROOT, **(env or {})))
    out, err = proc.communicate(timeout=120)
    return (proc.returncode,
            out.decode("utf-8", "replace"),
            err.decode("utf-8", "replace"))


class TestTheReaderHungUp(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="agentlog_epipe_")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        folder = os.path.join(self.home, ".claude", "projects", "-tmp-proj")
        os.makedirs(folder)
        sid = "pipe-0000-0000-0000-000000000001"
        records = []
        for i in range(40):
            at = _ago(3600 - i * 30)
            records.append({
                "type": "user", "sessionId": sid, "cwd": "/tmp/proj",
                "timestamp": at,
                "message": {"role": "user",
                            "content": [{"type": "text", "text": "turn"}]}})
            records.append({
                "type": "assistant", "sessionId": sid, "timestamp": at,
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t{}".format(i), "name": "Bash",
                     "input": {"command": "echo {}".format(i)}}]}})
        with open(os.path.join(folder, "s.jsonl"), "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

    def commands(self):
        home = ["--home", self.home]
        return [
            home + ["today"],
            home + ["week"],
            home + ["list"],
            home + ["since", "2h"],
            home + ["today", "--sessions"],
            home + ["today", "--json"],
            ["--version"],
            ["--help"],
        ]

    def test_nothing_is_printed_about_a_broken_pipe(self):
        for args in self.commands():
            with self.subTest(args=args[-2:]):
                _, err = run_with_no_reader(args)
                self.assertNotIn("BrokenPipeError", err, err)
                self.assertNotIn("Exception ignored", err, err)

    def test_it_is_not_a_traceback(self):
        for args in self.commands():
            with self.subTest(args=args[-2:]):
                _, err = run_with_no_reader(args)
                self.assertNotIn("Traceback", err, err)

    def test_the_exit_code_says_the_reader_hung_up(self):
        # Not 0, not 1, not 2 — a run that was cut off answered none of the
        # questions those codes answer.
        for args in self.commands():
            with self.subTest(args=args[-2:]):
                code, err = run_with_no_reader(args)
                self.assertEqual(code, 141,
                                 "{} -> {}\n{}".format(args[-2:], code, err))

    def test_help_and_version_are_covered_too(self):
        # argparse prints these and exits before the command ever runs, so a
        # handler that only wraps the command body misses them.
        for args in (["--version"], ["--help"]):
            with self.subTest(args=args):
                code, err = run_with_no_reader(args)
                self.assertEqual(code, 141, err)
                self.assertEqual(err, "", err)

    def test_a_reader_that_stays_still_gets_the_real_answer(self):
        # The regression guard: nothing above may cost a working run its
        # output or its exit code.
        code, out, err = run_normally(["--home", self.home, "today"])
        self.assertEqual(code, 0, err)
        self.assertIn("commands", out, out)

    def test_the_version_still_prints_when_anyone_is_listening(self):
        code, out, err = run_normally(["--version"])
        self.assertEqual(code, 0, err)
        self.assertTrue((out + err).strip(), "no version printed")


if __name__ == "__main__":
    unittest.main()
