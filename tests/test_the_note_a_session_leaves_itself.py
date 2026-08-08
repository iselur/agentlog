"""`agentlog handover` — written before compaction, read back after it.

The promises worth pinning, in the order they can fail:

- the note is about *this* session, found by the id compaction keeps, so two
  sessions running side by side never read each other's;
- it is handed over once, because a note read twice states two-hour-old facts
  as present ones;
- it says what the transcript says, not what a model made of it;
- and none of it, on any input, is ever a reason the agent stops.  That last is
  the whole of why this is safe to put in a settings file: every failure below
  comes back as exit 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog import handover  # noqa: E402
from tests.fixtures import (  # noqa: E402
    a_now_that_keeps,
    claude_assistant,
    claude_user,
    tool_bash,
    tool_edit,
)


class Case(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.now = a_now_that_keeps(90)

    def a_transcript(self, name="live.jsonl", sid="sess-1",
                     cwd="/home/you/thing", cmd="pytest -q"):
        when = (self.now - timedelta(minutes=20)).isoformat()
        path = os.path.join(self.home, name)
        with open(path, "w", encoding="utf-8") as fh:
            for rec in (
                claude_user(sid, when, cwd=cwd, text="get the suite green"),
                claude_assistant(sid, when, tools=[
                    tool_edit(os.path.join(cwd, "widget.py")),
                    tool_bash(cmd),
                ]),
            ):
                fh.write(json.dumps(rec) + "\n")
        return path

    def pre_compact(self, sid="sess-1", path=None, **over):
        payload = {"hook_event_name": "PreCompact", "session_id": sid,
                   "transcript_path": path or self.a_transcript(sid=sid),
                   "cwd": "/home/you/thing"}
        payload.update(over)
        return handover.handle(json.dumps(payload), self.home)

    def session_start(self, sid="sess-1"):
        return handover.handle(json.dumps({
            "hook_event_name": "SessionStart", "session_id": sid,
            "transcript_path": "unread", "cwd": "/home/you/thing"}), self.home)

    def injected(self, out):
        """The context a SessionStart hook's stdout actually delivers."""
        payload = json.loads(out)
        spec = payload["hookSpecificOutput"]
        self.assertEqual(spec["hookEventName"], "SessionStart")
        return spec["additionalContext"]


class TestItSaysWhatTheTranscriptSays(Case):

    def test_the_note_carries_the_work_the_session_had_done(self):
        self.pre_compact()
        out, err = self.session_start()
        self.assertEqual(err, "")
        text = self.injected(out)
        # The three things a compacted agent cannot get back: where it was
        # working, what it changed, and what it ran.
        self.assertIn("thing", text)
        self.assertIn("widget.py", text)
        self.assertIn("1 file edited", text)

    def test_it_says_it_is_a_record_so_it_is_not_read_as_another_summary(self):
        self.pre_compact()
        text = self.injected(self.session_start()[0])
        self.assertIn("compacted", text.splitlines()[0])
        self.assertIn("agentlog", text)

    def test_nothing_is_sent_anywhere_to_write_it(self):
        # The handover is deliberately model-free: compaction already produces
        # a written summary, and a second account of the same conversation
        # would drift the same way.  Its evidence never leaves the machine, so
        # it is safe in a hook that fires unattended.
        source = os.path.join(_ROOT, "agentlog", "handover.py")
        with open(source, encoding="utf-8") as fh:
            body = fh.read()
        for reaching_out in ("asking_a_model", "subprocess", "urllib", "socket"):
            self.assertNotIn(reaching_out, body)


class TestItIsThisSessionsNoteAndItIsHandedOverOnce(Case):

    def test_another_session_running_beside_it_gets_its_own(self):
        # Two agents in two terminals compact minutes apart.  Handing one the
        # other's work would be worse than handing it nothing.
        self.pre_compact(sid="sess-a",
                         path=self.a_transcript("a.jsonl", "sess-a",
                                                cwd="/home/you/alpha"))
        self.pre_compact(sid="sess-b",
                         path=self.a_transcript("b.jsonl", "sess-b",
                                                cwd="/home/you/beta"))
        alpha = self.injected(self.session_start("sess-a")[0])
        beta = self.injected(self.session_start("sess-b")[0])
        self.assertIn("alpha", alpha)
        self.assertNotIn("beta", alpha)
        self.assertIn("beta", beta)
        self.assertNotIn("alpha", beta)

    def test_a_session_with_no_note_waiting_is_handed_nothing(self):
        out, err = self.session_start("never-compacted")
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_the_note_is_handed_over_once_and_then_it_is_gone(self):
        # Left behind, it would be injected again at the next compaction --
        # hours-old facts stated in the present tense, which is worse than
        # having said nothing.
        self.pre_compact()
        self.assertNotEqual(self.session_start()[0], "")
        self.assertEqual(self.session_start()[0], "")

    def test_a_second_compaction_replaces_the_first_note(self):
        self.pre_compact()
        later = self.a_transcript("later.jsonl", "sess-1",
                                  cwd="/home/you/somewhere-else")
        self.pre_compact(path=later)
        text = self.injected(self.session_start()[0])
        self.assertIn("somewhere-else", text)
        self.assertNotIn("/home/you/thing", text)

    def test_a_session_id_that_is_a_path_cannot_write_outside_the_store(self):
        # The id arrives from another program and names a file, which is the
        # whole of what a path traversal needs.  Nothing on this machine sends
        # one shaped like this -- which is exactly why no corpus of real
        # payloads could show whether it was handled.
        store = os.path.realpath(handover.state_dir(self.home))
        self.pre_compact(sid="../../../../etc/sneaky")
        written = []
        for root, _dirs, names in os.walk(self.home):
            written.extend(os.path.realpath(os.path.join(root, n))
                           for n in names)
        notes = [p for p in written if p.endswith(".txt")]
        self.assertTrue(notes, written)
        for path in notes:
            self.assertEqual(os.path.dirname(path), store, path)

    def test_a_subagents_compaction_writes_nothing_and_takes_nothing(self):
        # Codex fires PreCompact for a subagent's compaction carrying the
        # *parent's* session_id plus an agent_id of its own.  A note written
        # then would be the subagent's story, handed to the root session at
        # its next resume and stated as the root's own past.
        self.pre_compact()  # the root's real note, written first
        out, err = self.pre_compact(
            path=self.a_transcript("sub.jsonl", "sess-1",
                                   cwd="/home/you/sub-errand"),
            agent_id="agent-77")
        self.assertEqual((out, err), ("", ""))
        text = self.injected(self.session_start()[0])
        self.assertIn("thing", text)  # the root's note, untouched
        self.assertNotIn("sub-errand", text)

    def test_the_store_and_the_note_are_private_to_their_owner(self):
        # A note is a condensed transcript -- prompts, paths, failing
        # commands -- sitting in a directory another local user could list.
        self.pre_compact()
        store = handover.state_dir(self.home)
        self.assertEqual(os.stat(store).st_mode & 0o777, 0o700)
        note = os.path.join(store, "sess-1.txt")
        self.assertEqual(os.stat(note).st_mode & 0o777, 0o600)

    def test_old_notes_are_swept_so_the_store_does_not_grow_forever(self):
        store = handover.state_dir(self.home)
        os.makedirs(store)
        stale = os.path.join(store, "long-gone.txt")
        with open(stale, "w", encoding="utf-8") as fh:
            fh.write("from another month")
        long_ago = handover.KEEP_FOR_DAYS * 86400 + 3600
        import time as _time
        os.utime(stale, (_time.time() - long_ago, _time.time() - long_ago))
        self.pre_compact()
        self.assertFalse(os.path.exists(stale))
        self.assertNotEqual(self.session_start()[0], "")  # and the new one lives


class TestNothingHereStopsTheAgent(Case):

    def bad_payloads(self):
        return [
            ("empty stdin", ""),
            ("not json", "this is not json at all"),
            ("json but not an object", "[1, 2, 3]"),
            ("no event name", json.dumps({"session_id": "s"})),
            ("no session id", json.dumps({"hook_event_name": "PreCompact"})),
            ("an event we do not serve",
             json.dumps({"hook_event_name": "PreToolUse", "session_id": "s"})),
            ("a transcript that is not there",
             json.dumps({"hook_event_name": "PreCompact", "session_id": "s",
                         "transcript_path": "/no/such/file.jsonl"})),
            ("a transcript that is a directory",
             json.dumps({"hook_event_name": "PreCompact", "session_id": "s",
                         "transcript_path": "/tmp"})),
        ]

    def test_no_payload_makes_it_raise(self):
        for why, payload in self.bad_payloads():
            with self.subTest(why):
                out, _err = handover.handle(payload, self.home)
                # Whatever went wrong, stdout stays clean: a hook's stdout on
                # SessionStart is injected verbatim, so a complaint printed
                # there would arrive as a fact about the session.
                self.assertEqual(out, "", why)

    def test_no_payload_makes_the_command_exit_nonzero(self):
        # The property the settings file rests on.  A PreCompact hook that
        # exits 2 blocks the compaction it was watching; the agent then cannot
        # go on, and the reason is the note-taker.
        for why, payload in self.bad_payloads():
            with self.subTest(why):
                r = subprocess.run(
                    [sys.executable, "-m", "agentlog", "handover",
                     "--home", self.home],
                    input=payload, capture_output=True, text=True,
                    env=dict(os.environ, PYTHONPATH=_ROOT))
                self.assertEqual(r.returncode, 0, (why, r.stderr))
                self.assertNotIn("Traceback", r.stderr, why)

    def test_a_problem_is_still_said_out_loud_on_the_error_stream(self):
        # Silent is not the same as harmless: a hook that never works and
        # never complains is one nobody notices is broken.  stderr is where a
        # hook's output is kept for whoever goes looking.
        _out, err = handover.handle("not json", self.home)
        self.assertIn("agentlog handover", err)

    def test_typed_at_a_terminal_it_says_what_it_is_instead_of_hanging(self):
        # The unknown-command hint offers 'handover', so somebody will type it.
        # With no payload coming, a read on a keyboard never returns -- the
        # command would sit there looking hung.  A pipe cannot see this: on a
        # pipe stdin is already closed, so the read returns "" and the branch
        # under test never runs.  It takes a real terminal.
        import pty
        parent, child = pty.openpty()
        try:
            done = subprocess.run(
                [sys.executable, "-m", "agentlog", "handover"],
                stdin=child, capture_output=True, text=True, timeout=30,
                env=dict(os.environ, PYTHONPATH=_ROOT))
        finally:
            os.close(child)
            os.close(parent)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("hook", done.stderr)
        self.assertIn("settings.json", done.stderr)
        self.assertEqual(done.stdout, "")

    def test_end_to_end_through_the_command_the_settings_file_names(self):
        path = self.a_transcript()
        wrote = subprocess.run(
            [sys.executable, "-m", "agentlog", "handover", "--home", self.home],
            input=json.dumps({"hook_event_name": "PreCompact",
                              "session_id": "sess-1",
                              "transcript_path": path}),
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))
        self.assertEqual(wrote.returncode, 0, wrote.stderr)
        self.assertEqual(wrote.stdout, "")
        read = subprocess.run(
            [sys.executable, "-m", "agentlog", "handover", "--home", self.home],
            input=json.dumps({"hook_event_name": "SessionStart",
                              "session_id": "sess-1"}),
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertIn("widget.py", self.injected(read.stdout))


if __name__ == "__main__":
    unittest.main()
