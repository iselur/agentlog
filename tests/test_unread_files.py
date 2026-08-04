"""A log file agentlog could not read left no trace anywhere.

Three files in one project — one ordinary, one whose permissions had been
changed, one that had been truncated mid-write into unparseable bytes:

    $ agentlog today --verbose
    0s active across 1 project · today, Tue 4 Aug

      p           0s   1 command

      1 session · busiest 10:00–11:00

    $ agentlog list
    ID        PROJECT   WHEN              DUR   SRC
    --------  --------  ----------------  ----  ------
    s         p         2026-08-04 10:43  0s    claude

One session, said three times, with two files on disk that say otherwise.
This is the tool people use to answer "what did the agent do last night",
and the answer was wrong in the direction that looks fine.

The near-miss is what makes it worth a test.  `_read_lines` already returns
a read-error count, the parsers already fold it into ``skipped_lines``, and
the digest already has a `--verbose` line that reports the total:

    if verbose:
        skipped = sum(s["skipped_lines"] for s in sessions)

But a file that could not be read has no timestamps in it, so the session
carrying that count fell out of the day-window filter before the line ran.
The count of what was dropped was dropped.  Everything needed to say this
was already being computed; it just never reached the screen.

A zero-byte file is deliberately not one of these.  A session that has only
just started is empty on disk and nothing has been lost, which is not the
same as a file with contents that could not be used.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _records(sid="s"):
    # The session id has to vary per file: two files carrying the same id are
    # one session as far as the parser is concerned, which is correct and not
    # what any of these tests are about.
    now = datetime.now(timezone.utc).isoformat()
    return "\n".join([
        json.dumps({"type": "user", "timestamp": now, "sessionId": sid,
                    "message": {"role": "user", "content": "hi"}}),
        json.dumps({"type": "assistant", "timestamp": now, "sessionId": sid,
                    "message": {"role": "assistant", "id": "m1-" + sid,
                                "content": [{"type": "tool_use",
                                             "id": "t1-" + sid,
                                             "name": "Bash",
                                             "input": {"command": "ls"}}],
                                "usage": {"input_tokens": 10,
                                          "output_tokens": 5}}}),
    ]) + "\n"


class Case(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-unread-")
        self.addCleanup(self._cleanup)
        self.proj = os.path.join(self.home, ".claude", "projects", "p")
        os.makedirs(self.proj)
        self.write("aaa-good.jsonl", _records())

    def _cleanup(self):
        # Restore permissions first, or the tree cannot be removed.
        for dirpath, _, names in os.walk(self.home):
            for name in names:
                try:
                    os.chmod(os.path.join(dirpath, name), 0o644)
                except OSError:
                    pass
        shutil.rmtree(self.home, ignore_errors=True)

    def write(self, name, text, mode=0o644):
        path = os.path.join(self.proj, name)
        with open(path, "w") as fh:
            fh.write(text)
        os.chmod(path, mode)
        return path

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "agentlog", *argv, "--home", self.home],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))


class TestAFileThatCouldNotBeRead(Case):

    def setUp(self):
        super().setUp()
        self.write("bbb-locked.jsonl", _records("s2"), mode=0o000)

    def test_the_digest_says_a_file_was_not_counted(self):
        p = self.run_cli("today")
        self.assertIn("not counted", (p.stdout + p.stderr).lower(),
                      "a file it could not read went unmentioned:\n" + p.stdout)

    def test_the_digest_says_how_many(self):
        self.write("ccc-locked.jsonl", _records("s3"), mode=0o000)
        p = self.run_cli("today")
        # Not a bare "2": a digest is full of numbers and that assertion would
        # pass on a token count.
        self.assertIn("2 log files", p.stdout + p.stderr, p.stdout)

    def test_verbose_names_the_file(self):
        # A count tells you something is wrong; the name tells you what to
        # chmod.  The same argument the save command makes about skipped files.
        p = self.run_cli("today", "--verbose")
        self.assertIn("bbb-locked", p.stdout + p.stderr, p.stdout)

    def test_the_list_view_says_so_too(self):
        # `list` is where somebody goes looking for a session ID they know they
        # ran.  A short list with no explanation is the worst place for this.
        p = self.run_cli("list")
        self.assertIn("not counted", (p.stdout + p.stderr).lower(), p.stdout)

    def test_the_sessions_view_says_so_too(self):
        p = self.run_cli("today", "--sessions")
        self.assertIn("not counted", (p.stdout + p.stderr).lower(), p.stdout)

    def test_json_mode_still_prints_a_bare_list(self):
        # The published contract is a JSON array of sessions.  Warning about an
        # unread file must not change that shape — it goes to stderr.
        p = self.run_cli("today", "--json")
        self.assertIsInstance(json.loads(p.stdout), list)

    def test_json_mode_warns_on_stderr(self):
        p = self.run_cli("today", "--json")
        self.assertIn("not counted", p.stderr.lower(), p.stderr)

    def test_a_saved_report_says_so(self):
        # A file outlives the terminal it was made in.  If the note only ever
        # appeared on a digest nobody kept, the saved report would be the one
        # artefact that claims completeness with nothing to qualify it.
        out = os.path.join(tempfile.mkdtemp(prefix="al-out-"), "r.html")
        self.addCleanup(shutil.rmtree, os.path.dirname(out), ignore_errors=True)
        p = self.run_cli("today", "--html", out)
        self.assertIn("not counted", (p.stdout + p.stderr).lower(), p.stdout)

    def test_markdown_on_stdout_keeps_the_note_out_of_the_document(self):
        p = self.run_cli("today", "--md", "-")
        self.assertNotIn("not counted", p.stdout.lower(), p.stdout)
        self.assertIn("not counted", p.stderr.lower(), p.stderr)

    def test_the_exit_code_is_still_zero(self):
        # Deliberate: agentlog reports what an agent did, it does not gate
        # anything, and its README promises no failure exit.  What changes is
        # that the report stops claiming to be complete.
        p = self.run_cli("today")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class TestAFileWithNothingReadableInIt(Case):
    """Readable, and every line of it unusable — a truncated write, say."""

    def setUp(self):
        super().setUp()
        self.write("ccc-corrupt.jsonl", "not json at all\n{ broken\n\x00\x01\n")

    def test_it_is_reported_too(self):
        p = self.run_cli("today")
        self.assertIn("not counted", (p.stdout + p.stderr).lower(), p.stdout)

    def test_it_is_described_differently_from_an_unreadable_one(self):
        # Two different things to do about them: one is chmod, the other is a
        # file to go and look at.  A single count would hide which you have.
        p = self.run_cli("today", "--verbose")
        body = (p.stdout + p.stderr).lower()
        self.assertIn("ccc-corrupt", body, body)
        self.assertNotIn("could not be read", body,
                         "called a readable file unreadable:\n" + body)


class TestAnEmptyFileIsNotAProblem(Case):
    """A session that has only just started has nothing in it yet."""

    def setUp(self):
        super().setUp()
        self.write("ddd-fresh.jsonl", "")

    def test_it_is_not_reported(self):
        p = self.run_cli("today")
        self.assertNotIn("not counted", (p.stdout + p.stderr).lower(),
                         "warned about a file with nothing lost in it:\n"
                         + p.stdout)


class TestAnOrdinaryRunIsUnaffected(Case):

    def test_nothing_is_said_when_every_file_was_read(self):
        p = self.run_cli("today")
        self.assertNotIn("not counted", (p.stdout + p.stderr).lower(), p.stdout)

    def test_the_session_is_still_reported(self):
        p = self.run_cli("today")
        self.assertIn("1 session", p.stdout, p.stdout)

    def test_a_session_with_some_bad_lines_still_counts_as_a_session(self):
        # Damage inside an otherwise good file is a different thing: the
        # session is real, most of it parsed, and `skipped_lines` covers it.
        self.write("eee-partial.jsonl", "garbage\n" + _records("s2"))
        p = self.run_cli("today")
        self.assertIn("2 sessions", p.stdout, p.stdout)
        self.assertNotIn("not counted", (p.stdout + p.stderr).lower(), p.stdout)

    def test_the_list_view_is_unchanged(self):
        # `list` prints session ids, not file names — the good file's session
        # is "s", and it is the only row there should be.
        p = self.run_cli("list")
        self.assertIn("claude", p.stdout, p.stdout)
        self.assertNotIn("not counted", (p.stdout + p.stderr).lower(), p.stdout)


if __name__ == "__main__":
    unittest.main()
