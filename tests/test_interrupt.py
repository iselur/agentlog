"""What happens when somebody presses ctrl-c.

Reading a year of session logs takes a moment, and a moment is long enough to
change your mind in.  Interrupting is an ordinary thing to do to a command that
is taking longer than you expected — it should not be answered with twenty
lines of interpreter internals ending in ``KeyboardInterrupt``, which reads as a
crash and sends people looking for the bug they just caused.

The exit code carries the other half of it.  A report that was abandoned partway
through is not a report, so `agentlog today > digest.md && mail-it` must not
mail an empty file.  130 is the shell's own way of spelling "stopped by ctrl-c",
which is exactly what happened.
"""

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentlog import cli  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCtrlC(unittest.TestCase):

    def setUp(self):
        self.real = cli.find_sessions

    def tearDown(self):
        cli.find_sessions = self.real

    def _interrupt_during_the_scan(self):
        def boom(*args, **kwargs):
            raise KeyboardInterrupt
        cli.find_sessions = boom

    def test_it_does_not_report_success(self):
        # The one that matters in a pipeline: a half-read day is not a day.
        self._interrupt_during_the_scan()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["today"])
        self.assertEqual(code, 130)

    def test_it_does_not_print_a_traceback(self):
        self._interrupt_during_the_scan()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            cli.main(["today"])
        self.assertNotIn("Traceback", out.getvalue() + err.getvalue())

    def test_every_view_answers_the_same_way(self):
        for args in (["today"], ["week"], ["list"], ["today", "--json"]):
            self._interrupt_during_the_scan()
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(args)
            self.assertEqual(code, 130, args)

    def test_the_real_command_line_agrees(self):
        # In process is where the assertion is precise; this is here to catch a
        # guard that exists in `main` but is bypassed by the module entry point.
        env = dict(os.environ, PYTHONPATH=_ROOT)
        proc = subprocess.Popen(
            [sys.executable, "-c",
             "import sys; from agentlog import cli;"
             "cli.find_sessions = lambda *a, **k: (_ for _ in ()).throw("
             "KeyboardInterrupt());"
             "sys.exit(cli.main(['today']))"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=_ROOT)
        _, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 130, err.decode("utf-8", "replace"))
        self.assertNotIn(b"Traceback", err)


if __name__ == "__main__":
    unittest.main()
