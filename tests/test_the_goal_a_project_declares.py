"""`agentlog goal` — declared once, replayed at every resume from compaction.

The promises worth pinning, in the order they can fail:

- what was declared is what comes back, verbatim, with nothing tidied;
- bloat is refused at the door: over the cap nothing is stored, and the
  refusal says the count;
- the newest declaration wins, and clearing forgets -- an immutable goal
  would amplify exactly the staleness it exists to cure;
- each directory keeps its own goal, and no directory path, however shaped,
  can write outside the private store;
- at resume the goal rides in front of the note, arrives even when there is
  no note, and -- unlike the note -- is not deleted on the way out;
- its label says when it was declared and that it is not the last word, so
  a stale goal re-anchors without overruling a legitimate pivot;
- and none of it, on any input, is ever a reason the agent stops.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog import goal, handover  # noqa: E402
from tests.fixtures import (  # noqa: E402
    a_now_that_keeps,
    claude_assistant,
    claude_user,
    tool_bash,
    tool_edit,
)

A_GOAL = ("Ship the importer.\n"
          "Done when: a malformed row is reported and clean rows still land.\n"
          "Constraint: no new dependencies.")


class Case(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.cwd = "/home/you/thing"
        self.clock = time.time()

    # session="" pins the declaration as the directory's shared goal: this
    # suite itself runs inside a Claude Code session, and leaving the default
    # would let that session's exported id bind every fixture to it.
    def declare(self, text=A_GOAL, cwd=None, now=None, session=""):
        return goal.declare(text, cwd or self.cwd, self.home,
                            self.clock if now is None else now, session)


class TestWhatWasDeclaredIsWhatComesBack(Case):

    def test_read_back_verbatim_with_nothing_tidied(self):
        message, complaint = self.declare()
        self.assertEqual(complaint, "")
        self.assertIn("goal declared", message)
        shown = goal.show(self.cwd, self.home, self.clock)
        # The declaration, whitespace and all -- a goal that came back
        # reworded would be the drift this seam exists to prevent.
        self.assertIn(A_GOAL, shown)

    def test_over_the_cap_is_refused_and_nothing_is_stored(self):
        long = "x" * (goal.CAP + 1)
        _message, complaint = self.declare(long)
        self.assertIn(str(goal.CAP + 1), complaint)
        self.assertIn(str(goal.CAP), complaint)
        self.assertIn("no goal declared", goal.show(self.cwd, self.home))

    def test_exactly_the_cap_is_accepted(self):
        # The cap is a limit, not a neighborhood: refusing at the line would
        # make the advertised number a lie by one.
        _message, complaint = self.declare("x" * goal.CAP)
        self.assertEqual(complaint, "")

    def test_an_empty_goal_is_refused(self):
        for empty in ("", "   ", "\n\t"):
            _message, complaint = self.declare(empty)
            self.assertNotEqual(complaint, "", repr(empty))

    def test_redeclaring_replaces_the_old_goal_outright(self):
        self.declare("the old brief")
        self.declare("the new brief, after the pivot")
        shown = goal.show(self.cwd, self.home, self.clock)
        self.assertIn("the new brief", shown)
        self.assertNotIn("the old brief", shown)

    def test_clearing_forgets_and_clearing_nothing_is_not_an_error(self):
        self.declare()
        self.assertIn("cleared", goal.clear(self.cwd, self.home))
        self.assertIn("no goal declared", goal.show(self.cwd, self.home))
        self.assertIn("no goal was declared", goal.clear(self.cwd, self.home))

    def test_each_directory_keeps_its_own_goal(self):
        self.declare("goal for alpha", cwd="/home/you/alpha")
        self.declare("goal for beta", cwd="/home/you/beta")
        alpha = goal.show("/home/you/alpha", self.home, self.clock)
        self.assertIn("alpha", alpha)
        self.assertNotIn("beta", alpha)

    def test_the_same_directory_through_a_symlink_is_the_same_goal(self):
        real = os.path.join(self.home, "project")
        os.makedirs(real)
        link = os.path.join(self.home, "shortcut")
        os.symlink(real, link)
        self.declare("one project, two spellings", cwd=real)
        self.assertIn("one project, two spellings",
                      goal.show(link, self.home, self.clock))

    def test_a_hostile_directory_path_cannot_write_outside_the_store(self):
        # The cwd reaches `declare` from the shell and `anchor` from a hook
        # payload another program wrote; either way it names a file.
        store = os.path.realpath(goal.state_dir(self.home))
        self.declare(cwd="../../../../etc/sneaky\x00name")
        written = []
        for root, _dirs, names in os.walk(self.home):
            written.extend(os.path.realpath(os.path.join(root, n))
                           for n in names)
        self.assertTrue(written)
        for path in written:
            self.assertEqual(os.path.dirname(path), store, path)

    def test_two_sessions_in_one_directory_keep_two_goals(self):
        # Two concurrent sessions in one directory are two briefs.  Sharing
        # one slot would replay A's brief into B's freshly compacted context
        # with the salience of a system message -- the exact drift this seam
        # exists to prevent.
        self.declare("brief for session A", session="sess-a")
        self.declare("brief for session B", session="sess-b")
        a = goal.anchor(self.cwd, "sess-a", self.home, self.clock)
        b = goal.anchor(self.cwd, "sess-b", self.home, self.clock)
        self.assertIn("brief for session A", a)
        self.assertNotIn("brief for session B", a)
        self.assertIn("brief for session B", b)

    def test_a_terminal_declaration_is_the_shared_north_star(self):
        # Declared with no session to bind to, the goal is the directory's,
        # and any session without a goal of its own resumes with it.
        self.declare("the project's north star", session="")
        self.assertIn("the project's north star",
                      goal.anchor(self.cwd, "sess-a", self.home, self.clock))
        self.assertIn("the project's north star",
                      goal.anchor(self.cwd, "sess-b", self.home, self.clock))

    def test_a_sessions_own_goal_outranks_the_shared_one(self):
        self.declare("the project's north star", session="")
        self.declare("this session's brief", session="sess-a")
        mine = goal.anchor(self.cwd, "sess-a", self.home, self.clock)
        self.assertIn("this session's brief", mine)
        self.assertNotIn("north star", mine)
        other = goal.anchor(self.cwd, "sess-b", self.home, self.clock)
        self.assertIn("north star", other)

    def test_clearing_takes_the_sessions_goal_before_the_shared_one(self):
        self.declare("the project's north star", session="")
        self.declare("this session's brief", session="sess-a")
        first = goal.clear(self.cwd, self.home, session="sess-a")
        self.assertIn("session", first)
        self.assertIn("north star",
                      goal.show(self.cwd, self.home, self.clock, "sess-a"))
        second = goal.clear(self.cwd, self.home, session="sess-a")
        self.assertIn("shared", second)
        self.assertIn("no goal declared",
                      goal.show(self.cwd, self.home, self.clock, "sess-a"))

    def test_a_dead_sessions_goal_is_swept_and_the_shared_one_is_not(self):
        # A goal bound to a session is rubbish once the session is over; the
        # shared goal is the project's and holds until somebody clears it.
        self.declare("a dead session's brief", session="sess-dead")
        self.declare("the project's north star", session="")
        long_ago = self.clock - (goal.KEEP_SESSION_GOALS_FOR_DAYS + 1) * 86400
        store = goal.state_dir(self.home)
        for name in os.listdir(store):
            os.utime(os.path.join(store, name), (long_ago, long_ago))
        self.declare("a fresh declaration", session="sess-live")
        self.assertEqual(
            goal.anchor(self.cwd, "sess-dead", self.home, self.clock)
                .count("dead session"), 0)
        self.assertIn("north star",
                      goal.anchor(self.cwd, "sess-other", self.home,
                                  self.clock))

    def test_the_store_and_the_goal_are_private_to_their_owner(self):
        # A goal says in plain words what somebody is building -- in a
        # directory another local user could list.
        self.declare()
        store = goal.state_dir(self.home)
        self.assertEqual(os.stat(store).st_mode & 0o777, 0o700)
        names = os.listdir(store)
        self.assertEqual(len(names), 1)
        record = os.path.join(store, names[0])
        self.assertEqual(os.stat(record).st_mode & 0o777, 0o600)


class TestItRidesInFrontOfTheNoteAtEveryResume(Case):
    """Through `handover.handle`, which is what the hook actually runs."""

    def setUp(self):
        super().setUp()
        self.now = a_now_that_keeps(90)

    def a_transcript(self):
        when = (self.now - timedelta(minutes=20)).isoformat()
        path = os.path.join(self.home, "live.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for rec in (
                claude_user("sess-1", when, cwd=self.cwd,
                            text="get the suite green"),
                claude_assistant("sess-1", when, tools=[
                    tool_edit(os.path.join(self.cwd, "widget.py")),
                    tool_bash("pytest -q"),
                ]),
            ):
                fh.write(json.dumps(rec) + "\n")
        return path

    def pre_compact(self):
        return handover.handle(json.dumps({
            "hook_event_name": "PreCompact", "session_id": "sess-1",
            "transcript_path": self.a_transcript(), "cwd": self.cwd}),
            self.home)

    def session_start(self, **over):
        payload = {"hook_event_name": "SessionStart", "session_id": "sess-1",
                   "transcript_path": "unread", "cwd": self.cwd}
        payload.update(over)
        return handover.handle(json.dumps(payload), self.home)

    def injected(self, out):
        payload = json.loads(out)
        spec = payload["hookSpecificOutput"]
        self.assertEqual(spec["hookEventName"], "SessionStart")
        return spec["additionalContext"]

    def test_the_goal_arrives_first_and_the_note_after_it(self):
        # What the work is for, then what it has done -- the order a person
        # briefing a colleague would use.
        self.declare()
        self.pre_compact()
        text = self.injected(self.session_start()[0])
        self.assertLess(text.index("Ship the importer"),
                        text.index("widget.py"))

    def test_a_goal_with_no_note_still_arrives(self):
        # A session's first compaction can precede any note -- and a fresh
        # resume in a project with a declared goal deserves the anchor even
        # when there is nothing else to hand over.
        self.declare()
        text = self.injected(self.session_start()[0])
        self.assertIn("Ship the importer", text)

    def test_a_note_with_no_goal_is_still_handed_over(self):
        self.pre_compact()
        text = self.injected(self.session_start()[0])
        self.assertIn("widget.py", text)
        self.assertNotIn("declared goal", text)

    def test_with_neither_goal_nor_note_nothing_is_said(self):
        out, err = self.session_start()
        self.assertEqual((out, err), ("", ""))

    def test_the_label_says_when_and_that_it_is_not_the_last_word(self):
        self.declare(now=self.clock - 3 * 3600)
        text = self.injected(self.session_start()[0])
        self.assertIn("declared goal", text)
        self.assertIn("3h ago", text)
        # The one sentence that keeps a quotation from overruling a pivot.
        self.assertIn("newer instructions from the user override", text)
        self.assertLess(text.index("override"),
                        text.index("Ship the importer"))

    def test_it_is_replayed_at_every_resume_not_handed_over_once(self):
        # The note describes a moment and is deleted on the way out; the
        # goal holds until redeclared or cleared, and replaying it is the
        # entire point.
        self.declare()
        self.pre_compact()
        first = self.injected(self.session_start()[0])
        second = self.injected(self.session_start()[0])
        self.assertIn("widget.py", first)
        self.assertIn("Ship the importer", second)
        self.assertNotIn("widget.py", second)

    def test_a_payload_without_a_cwd_still_hands_over_the_note(self):
        self.declare()
        self.pre_compact()
        text = self.injected(self.session_start(cwd=None)[0])
        self.assertIn("widget.py", text)
        self.assertNotIn("Ship the importer", text)

    def test_the_resuming_sessions_own_goal_is_handed_over(self):
        # Bound to sess-1, injected into sess-1: the hook must hand the
        # payload's session id to the lookup, or bound goals never replay.
        self.declare("this session's own brief", session="sess-1")
        text = self.injected(self.session_start()[0])
        self.assertIn("this session's own brief", text)

    def test_a_payload_without_a_cwd_gets_nobodys_goal(self):
        # realpath("") is the hook process's own directory; without the
        # empty-cwd guard a goal declared for wherever the hook happens to
        # run from would leak into every session that omitted its cwd.
        self.declare("the hook's own directory", cwd=os.getcwd(), session="")
        out, err = self.session_start(cwd=None)
        self.assertEqual((out, err), ("", ""))

    def test_another_sessions_goal_is_not_handed_over(self):
        # The resuming session is sess-1; a goal bound to a different session
        # must not reach it, however fresh -- but the shared one still does.
        self.declare("a stranger's brief", session="sess-2")
        out, err = self.session_start()
        self.assertEqual((out, err), ("", ""))
        self.declare("the project's north star", session="")
        text = self.injected(self.session_start()[0])
        self.assertIn("north star", text)
        self.assertNotIn("stranger", text)

    def test_a_subagents_resume_takes_nothing(self):
        # A subagent resuming from its own compaction carries the parent's
        # session_id plus an agent_id (Codex does this).  Answering it would
        # take -- and delete -- the note the root session is waiting on, and
        # hand the project's goal to an errand that has its own brief.
        self.declare()
        self.pre_compact()
        out, err = self.session_start(agent_id="agent-77")
        self.assertEqual((out, err), ("", ""))
        text = self.injected(self.session_start()[0])
        self.assertIn("widget.py", text)  # still there for the root


class TestTheCommandBehavesAtTheTerminal(Case):

    def run_cli(self, *words, session=None):
        # The suite itself runs inside a Claude Code session; a bare terminal
        # is simulated by dropping its exported id, a session by setting one.
        env = dict(os.environ, PYTHONPATH=_ROOT)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        if session:
            env["CLAUDE_CODE_SESSION_ID"] = session
        return subprocess.run(
            [sys.executable, "-m", "agentlog", *words, "--home", self.home],
            capture_output=True, text=True, cwd=self.home, env=env)

    def test_declare_show_clear_end_to_end(self):
        said = self.run_cli("goal", A_GOAL)
        self.assertEqual(said.returncode, 0, said.stderr)
        self.assertIn("goal declared", said.stdout)
        self.assertIn("shared by every session", said.stdout)
        shown = self.run_cli("goal")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("Ship the importer", shown.stdout)
        cleared = self.run_cli("goal", "--clear")
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        self.assertIn("no goal declared", self.run_cli("goal").stdout)

    def test_declared_inside_a_session_it_binds_to_that_session(self):
        # The agent accepting a brief runs in a shell whose harness exported
        # the session id; the declaration must say which kind it made.
        said = self.run_cli("goal", A_GOAL, session="sess-cli")
        self.assertEqual(said.returncode, 0, said.stderr)
        self.assertIn("bound to this session", said.stdout)
        # The bare terminal next door sees no goal; the session sees its own.
        self.assertIn("no goal declared", self.run_cli("goal").stdout)
        self.assertIn("Ship the importer",
                      self.run_cli("goal", session="sess-cli").stdout)

    def test_a_declaration_over_the_cap_is_a_usage_error(self):
        refused = self.run_cli("goal", "x" * (goal.CAP + 1))
        self.assertEqual(refused.returncode, 2)
        self.assertIn(str(goal.CAP), refused.stderr)
        self.assertEqual(refused.stdout, "")

    def test_clear_with_text_is_a_typo_answered(self):
        # `goal --clear "new text"` is somebody holding both halves of a
        # redeclaration; guessing which half they meant would do the wrong
        # one silently.
        confused = self.run_cli("goal", "some text", "--clear")
        self.assertEqual(confused.returncode, 2)
        self.assertIn("takes no text", confused.stderr)

    def test_clear_on_another_command_is_a_typo_answered(self):
        # Silence here would read as "cleared" to the person who typed it.
        confused = self.run_cli("today", "--clear")
        self.assertEqual(confused.returncode, 2)
        self.assertIn("goal", confused.stderr)


class TestEverythingDeclared(Case):
    """The brief's view of the store: every goal, newest per directory.

    ``everything_declared`` walks the raw store files rather than asking
    per-directory, so its promises are about the walk: a session-bound and
    a shared declaration for one directory collapse to the newest, junk in
    the store is skipped rather than fatal, and a store that does not exist
    is an empty answer, not an error.
    """

    def store(self):
        return goal.state_dir(self.home)

    def test_newest_declaration_wins_across_shared_and_session_bound(self):
        self.declare("the shared brief", now=self.clock)
        self.declare("the session brief", now=self.clock + 10,
                     session="sess-1")
        held = goal.everything_declared(self.home)
        record = held[os.path.realpath(self.cwd)]
        self.assertEqual(record["goal"], "the session brief")

    def test_a_newer_shared_goal_outranks_an_older_session_one(self):
        # The same promise with the ages swapped: whichever file the
        # listing yields first, the comparison -- not the walk order --
        # must decide.
        self.declare("the session brief", now=self.clock, session="sess-1")
        self.declare("the shared brief", now=self.clock + 10)
        held = goal.everything_declared(self.home)
        record = held[os.path.realpath(self.cwd)]
        self.assertEqual(record["goal"], "the shared brief")

    def test_each_directory_appears_under_its_real_path(self):
        self.declare("goal for alpha", cwd="/home/you/alpha")
        self.declare("goal for beta", cwd="/home/you/beta")
        held = goal.everything_declared(self.home)
        self.assertEqual(
            {os.path.realpath("/home/you/alpha"): "goal for alpha",
             os.path.realpath("/home/you/beta"): "goal for beta"},
            {key: record["goal"] for key, record in held.items()})

    def test_a_file_that_is_not_json_named_is_not_read(self):
        # A stray file holding a plausible record must stay invisible: if
        # the name filter went, this decoy -- newer than anything declared
        # -- would win the directory.
        self.declare("the declared goal", now=self.clock)
        decoy = {"goal": "the decoy goal", "cwd": self.cwd,
                 "set_at": self.clock + 999}
        with open(os.path.join(self.store(), "notes.txt"), "w",
                  encoding="utf-8") as fh:
            json.dump(decoy, fh)
        held = goal.everything_declared(self.home)
        record = held[os.path.realpath(self.cwd)]
        self.assertEqual(record["goal"], "the declared goal")

    def test_junk_in_the_store_is_skipped_not_fatal(self):
        self.declare("the declared goal")
        for name, body in (("broken.json", "{not json"),
                           ("alist.json", "[1, 2]"),
                           ("nogoal.json", json.dumps({"cwd": self.cwd})),
                           ("nocwd.json", json.dumps({"goal": "orphaned"}))):
            with open(os.path.join(self.store(), name), "w",
                      encoding="utf-8") as fh:
                fh.write(body)
        held = goal.everything_declared(self.home)
        self.assertEqual([os.path.realpath(self.cwd)], sorted(held))
        self.assertEqual(held[os.path.realpath(self.cwd)]["goal"],
                         "the declared goal")

    def test_a_store_that_does_not_exist_is_an_empty_answer(self):
        self.assertEqual({}, goal.everything_declared(
            os.path.join(self.home, "never-made")))


if __name__ == "__main__":
    unittest.main()
