"""The promises under ## Privacy, held to end-to-end.

    agentlog is strictly local.  No network code.  Nothing is uploaded or sent.

    Half of a conversation is shown, and it is your half. ... The agent's half
    is never shown, and neither is anything a command did.

That is the reason somebody points this tool at their own transcripts, so it is
a contract and not a description.  The parser tests check the reading, one
record shape at a time.  This file checks the whole tool the way a user meets
it: a home directory whose logs are full of marker words, every output mode run
over it, and each marker looked for in everything that comes back.

There are two markers, because the promise now has two halves and a test with
one marker can only hold one of them:

  - ``ASKED`` sits in the prompt somebody typed.  Every mode that describes a
    session **must** print it.  A digest that lists 247 commands and cannot say
    what any of them was for is the thing this half exists to prevent, and it
    would come back the moment nothing was watching for it.
  - ``SECRET`` sits in everything else that is text — what the agent replied,
    what it thought, what a command printed, what got written into a file, the
    summary, and the two record types nobody reads.  No mode may print it.

Both halves are checked in the same run over the same fixture, so neither can
pass by the output being empty: the run that proves the prompt came out is the
run that proves the reply did not.

agentlog has a wider output surface than a tailer does — a digest, a session
list, JSON, Markdown, a self-contained HTML file, a single-session view, and a
diagnostics mode — and each is a separate chance to print something.  The HTML
one matters most: it is a file, written to be sent to somebody, and the README
warns it carries paths, commands and what you typed.  It must not also carry
the agent's half, which the same README says is never extracted.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# A word that occurs nowhere in this package, so finding it in the output means
# it came out of a log.  This one is the agent's half of the conversation and
# must never come out.
SECRET = "SQUIRRELPLUM"

# The other half: a word inside the prompt somebody typed, which every mode
# that describes a session has to print.  Two words either side of it, so the
# prompt reads as an instruction rather than as an acknowledgement -- `asked`
# skips "ok" and "yes", and a one-word fixture would be testing that skip
# instead of the promise.
ASKED = "MARMALADEGOOSE"

# The activity around it, which is what agentlog exists to show.
COMMAND = "pytest -x"
WRITTEN = "/home/you/api/src/app.py"

CLAUDE_SID = "4ef1361b-07e4-4bc9-bb29-1783b761d677"
CODEX_SID = "019f80fa-4d34-7513-8add-a5368508ba77"

# Every stdlib module that can open a socket, plus the popular third-party
# clients.  A dependency-free tool that grew one of these would be the first
# place a reviewer looks, and nobody re-reads the imports by hand every release.
NETWORK_MODULES = {
    "asyncore", "ftplib", "http", "httplib", "httpx", "imaplib", "nntplib",
    "poplib", "requests", "smtplib", "socket", "socketserver", "ssl",
    "telnetlib", "urllib", "urllib2", "urllib3", "webbrowser", "xmlrpc",
    "aiohttp", "websockets",
}

# Running another program is how `--brief` reaches a model, so `subprocess` can
# no longer be forbidden outright.  It is confined instead: exactly one module
# may import it, and that module is named after the thing it does, so "does
# agentlog talk to anything?" stays a question with a one-line answer.
#
# Confinement is the whole guard.  Without it the promise would be "we only
# call out in the place we meant to", which is a sentence about intentions;
# with it the promise is a property of the tree that fails a test the moment it
# stops holding.
RUNS_ANOTHER_PROGRAM = {"subprocess", "multiprocessing", "asyncio", "pty"}
MAY_RUN_ANOTHER_PROGRAM = "asking_a_model.py"


def claude_log(day):
    """A Claude Code session: the secret in the agent's half, the ask in ours."""
    return "\n".join(json.dumps(r) for r in [
        {"type": "user", "timestamp": day + "T09:00:00Z",
         "sessionId": CLAUDE_SID, "cwd": "/home/you/api",
         # The one piece of text in this fixture that is supposed to come out.
         "message": {"role": "user", "content": [
             {"type": "text", "text": "deploy the " + ASKED + " service"}]}},
        {"type": "assistant", "timestamp": day + "T09:00:02Z",
         "sessionId": CLAUDE_SID, "cwd": "/home/you/api",
         "message": {"role": "assistant", "model": "claude-opus-5",
                     "usage": {"input_tokens": 10, "output_tokens": 5},
                     "content": [
                         {"type": "thinking", "thinking": "they said " + SECRET},
                         {"type": "text", "text": "I will use " + SECRET}]}},
        {"type": "assistant", "timestamp": day + "T09:00:05Z",
         "sessionId": CLAUDE_SID, "cwd": "/home/you/api",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Bash",
              # `description` is prose the model wrote, sitting inside the one
              # record agentlog does pull fields out of.
              "input": {"command": COMMAND,
                        "description": "run the tests for " + SECRET}}]}},
        {"type": "user", "timestamp": day + "T09:00:19Z",
         "sessionId": CLAUDE_SID, "cwd": "/home/you/api",
         # A command's output is where a real secret actually lives: a printed
         # environment, a connection string in a traceback.
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
              "content": "AWS_SECRET_ACCESS_KEY=" + SECRET}]}},
        {"type": "assistant", "timestamp": day + "T09:00:30Z",
         "sessionId": CLAUDE_SID, "cwd": "/home/you/api",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t2", "name": "Write",
              "input": {"file_path": WRITTEN,
                        "content": "PASSWORD = '" + SECRET + "'\n"}}]}},
        {"type": "summary", "timestamp": day + "T09:00:40Z",
         "sessionId": CLAUDE_SID,
         # A summary is a sentence the model wrote about the conversation.
         "summary": "set up deployment using " + SECRET},
        # Two record types agentlog has no branch for.  They are in the fixture
        # because that is exactly why they are worth having: a `user` record is
        # obviously message text and is handled carefully, and these carry the
        # same thing somewhere nobody is looking.  See TestTheRecordsNobodyReads.
        {"type": "queue-operation", "operation": "enqueue",
         "timestamp": day + "T09:00:45Z", "sessionId": CLAUDE_SID,
         "content": "then rotate the key " + SECRET},
        {"type": "frame-link", "sessionId": CLAUDE_SID,
         "timestamp": day + "T09:00:50Z",
         "path": "/home/you/api/out/report.html",
         "frameUrl": "https://example.invalid/artifact/1",
         "title": "How do I revoke " + SECRET + "?"},
    ]) + "\n"


def codex_log(day):
    """The same, in the other format."""
    patch = ("*** Begin Patch\n*** Update File: " + WRITTEN + "\n"
             "+password = '" + SECRET + "'\n*** End Patch")
    return "\n".join(json.dumps(r) for r in [
        {"timestamp": day + "T09:10:00Z", "type": "session_meta",
         "payload": {"id": CODEX_SID, "cwd": "/home/you/api",
                     "originator": "codex_cli_rs"}},
        {"timestamp": day + "T09:10:01Z", "type": "event_msg",
         "payload": {"type": "user_message",
                     "message": "ship the " + ASKED + " fix"}},
        {"timestamp": day + "T09:10:02Z", "type": "event_msg",
         "payload": {"type": "agent_message", "message": "using " + SECRET}},
        {"timestamp": day + "T09:10:03Z", "type": "response_item",
         "payload": {"type": "reasoning",
                     "summary": [{"type": "summary_text",
                                  "text": "recalling " + SECRET}]}},
        {"timestamp": day + "T09:10:05Z", "type": "response_item",
         "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "c1",
                     "input": 'tools.exec_command({"cmd":"%s"});' % COMMAND}},
        {"timestamp": day + "T09:10:19Z", "type": "response_item",
         "payload": {"type": "custom_tool_call_output", "call_id": "c1",
                     "output": json.dumps({"exit_code": 1,
                                           "output": "KEY=" + SECRET})}},
        {"timestamp": day + "T09:10:20Z", "type": "response_item",
         # The patch body is read — that is how the path is found — so what
         # gets *kept* out of it is the whole question.
         "payload": {"type": "function_call", "name": "apply_patch",
                     "call_id": "c2",
                     "arguments": json.dumps({"patch": patch,
                                              "workdir": "/home/you/api"})}},
        {"timestamp": day + "T09:10:21Z", "type": "event_msg",
         "payload": {"type": "token_count",
                     "info": {"last_token_usage": {"input_tokens": 10,
                                                   "output_tokens": 5},
                              "total_token_usage": {"input_tokens": 10,
                                                    "output_tokens": 5}}}},
    ]) + "\n"


def _tree_digest(root):
    """Path and content hash of everything under a directory."""
    out = {}
    for dirpath, _, names in os.walk(root):
        for name in sorted(names):
            full = os.path.join(dirpath, name)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root)] = hashlib.sha256(
                    fh.read()).hexdigest()
    return out


class Case(unittest.TestCase):
    """A home whose two logs are dated today, so the default window sees them."""

    def setUp(self):
        import datetime
        self.day = datetime.datetime.now().strftime("%Y-%m-%d")
        self.home = tempfile.mkdtemp(prefix="al-privacy-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.out = tempfile.mkdtemp(prefix="al-privacy-out-")
        self.addCleanup(shutil.rmtree, self.out, True)

        c = os.path.join(self.home, ".claude", "projects", "-home-you-api")
        parts = self.day.split("-")
        x = os.path.join(self.home, ".codex", "sessions", *parts)
        os.makedirs(c)
        os.makedirs(x)
        self.write(os.path.join(c, CLAUDE_SID + ".jsonl"), claude_log(self.day))
        self.write(os.path.join(
            x, "rollout-%sT09-10-00-%s.jsonl" % (self.day, CODEX_SID)),
            codex_log(self.day))

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_log(self, *argv, **extra_env):
        return subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home, *argv],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100", **extra_env))

    def a_model_that_keeps_what_it_was_sent(self, answer):
        """A stand-in for the `claude` command: records the prompt, prints back.

        The point of `--brief` is that something leaves this machine, so the
        test that matters is not "what did it print" but "what did it send".
        A real model would answer differently every run and could not be asked
        that question at all; this one hands the prompt back on disk.
        """
        capture = os.path.join(self.out, "sent-to-the-model.txt")
        script = os.path.join(self.out, "fake-model")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write("#!{}\n"
                     "import sys\n"
                     "open({!r}, 'w').write(sys.stdin.read())\n"
                     "sys.stdout.write({!r})\n".format(
                         sys.executable, capture, answer))
        os.chmod(script, 0o755)
        return script, capture


class TestMessageTextNeverReachesTheOutput(Case):

    # Every way this tool can be asked to say something.
    MODES = (
        (),
        ("--sessions",),
        ("--json",),
        ("--md",),
        ("--verbose",),
        ("week",),
        ("list",),
        ("list", "--all"),
        ("show", CLAUDE_SID[:8]),
        ("show", CODEX_SID[:8]),
        ("--project", "api"),
        ("today", "--json", "--sessions"),
    )

    def test_no_mode_prints_it(self):
        for mode in self.MODES:
            with self.subTest(mode=mode or ("default",)):
                p = self.run_log(*mode)
                said = p.stdout + p.stderr
                self.assertNotIn(SECRET, said,
                                 "message text reached the screen:\n" + said)

    def test_the_html_file_does_not_carry_it(self):
        # The one output built to be handed to somebody else.  The README warns
        # it holds paths and commands; it must hold nothing beyond that.
        dest = os.path.join(self.out, "digest.html")
        p = self.run_log("--html", dest)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(dest, encoding="utf-8") as fh:
            html = fh.read()
        self.assertNotIn(SECRET, html)
        # and it is not empty, or the assertion above proves nothing
        self.assertIn(COMMAND, html, "the HTML digest reported no activity")

    def test_the_markdown_file_does_not_carry_it(self):
        dest = os.path.join(self.out, "digest.md")
        p = self.run_log("--md", dest)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(dest, encoding="utf-8") as fh:
            md = fh.read()
        self.assertNotIn(SECRET, md)
        self.assertIn(COMMAND, md, "the Markdown digest reported no activity")

    def test_every_json_field_is_searched_not_just_the_rendering(self):
        # `--json` is the mode a script pipes somewhere else, so a secret
        # surviving in an unrendered field would travel further, not less far.
        p = self.run_log("--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(SECRET, json.dumps(json.loads(p.stdout)))

    def test_the_activity_beside_it_does_come_out(self):
        # Otherwise every assertion above passes on an empty report.
        p = self.run_log("--sessions")
        said = p.stdout
        self.assertIn(COMMAND, said, said + p.stderr)
        self.assertIn(os.path.basename(WRITTEN), said, said + p.stderr)

    def test_both_formats_are_actually_being_read(self):
        # One session from each log, so neither half of the fixture is silently
        # contributing nothing to the runs above.
        p = self.run_log("--json")
        data = json.loads(p.stdout)
        blob = json.dumps(data)
        self.assertIn(CLAUDE_SID[:8], blob, "the Claude log was not read")
        self.assertIn(CODEX_SID[:8], blob, "the Codex log was not read")

    def test_a_failure_is_named_by_its_command_not_its_output(self):
        # Both fixtures fail a call, and the failing output is where a secret
        # really lives.  What the digest may show is which command failed.
        p = self.run_log("--sessions")
        self.assertNotIn(SECRET, p.stdout + p.stderr)
        self.assertIn(COMMAND, p.stdout)


class TestWhatYouTypedDoesReachTheOutput(Case):
    """The other half of the promise, and the half that rots quietly.

    "Never show X" fails loudly the first time X appears.  "Always show Y"
    fails by Y going missing from one mode in a refactor, which looks like
    nothing at all -- the output is still there, still full of paths, and still
    answers a question nobody asked.  So every mode that describes a session is
    listed here by name, and each has to print the prompt.

    `list` is the exception and is named as one below.
    """

    MODES = (
        (),
        ("--sessions",),
        ("--json",),
        ("--md",),
        ("--verbose",),
        ("week",),
        ("show", CLAUDE_SID[:8]),
        ("show", CODEX_SID[:8]),
        ("--project", "api"),
        ("today", "--json", "--sessions"),
    )

    def test_every_mode_that_describes_a_session_says_what_it_was_for(self):
        for mode in self.MODES:
            with self.subTest(mode=mode or ("default",)):
                p = self.run_log(*mode)
                said = p.stdout + p.stderr
                self.assertIn(ASKED, said,
                              "no mode should report a session without saying "
                              "what it was asked for:\n" + said)
                # In the same run, so this cannot pass by printing everything.
                self.assertNotIn(SECRET, said)

    def test_both_logs_have_their_own_prompt_read(self):
        # One marker in two files: a mode could print the Claude prompt for
        # both sessions and satisfy the test above, so each is asked for by id.
        for sid in (CLAUDE_SID, CODEX_SID):
            with self.subTest(session=sid[:8]):
                p = self.run_log("show", sid[:8])
                self.assertIn(ASKED, p.stdout, p.stdout + p.stderr)

    def test_the_file_outputs_carry_it_because_that_is_the_point(self):
        # The two outputs that leave the machine.  They are the ones somebody
        # sends to a teammate, so they are the ones that most need to say what
        # the work was for -- and the README says plainly that they do.
        for flag, name in (("--html", "digest.html"), ("--md", "digest.md")):
            with self.subTest(output=flag):
                dest = os.path.join(self.out, name)
                p = self.run_log(flag, dest)
                self.assertEqual(p.returncode, 0, p.stderr)
                with open(dest, encoding="utf-8") as fh:
                    body = fh.read()
                self.assertIn(ASKED, body)
                self.assertNotIn(SECRET, body)

    def test_the_json_names_it_so_a_script_need_not_parse_prose(self):
        p = self.run_log("--json")
        data = json.loads(p.stdout)
        for s in data:
            with self.subTest(session=s["id"][:8]):
                self.assertIn(ASKED, s["asked"], s)

    def test_the_list_view_is_the_one_exception_and_is_meant_to_be(self):
        # `list` is a five-column index for finding a session id, not a
        # description of one: ID, PROJECT, WHEN, DUR, SRC, each a fixed width,
        # and a sentence does not go in a column.  Whoever finds their session
        # here runs `show` next, which does say.  Pinned rather than left
        # implicit so that adding it becomes a decision instead of an accident.
        p = self.run_log("list")
        self.assertNotIn(ASKED, p.stdout)
        self.assertIn(CLAUDE_SID[:8], p.stdout, "the list view listed nothing")


class TestTheOneCommandThatLeavesTheMachine(Case):
    """`--brief` sends the day to a model, and the README says which day.

    Every other mode is checked for what it *prints*.  This one has a second
    surface nobody can see from the terminal -- what went out -- and that is the
    surface a person actually cares about.  So the fixture's two markers are
    looked for in the prompt itself: the half of the conversation the README
    says is shown must be in it, because naming the work is the entire job, and
    the half the README says is never shown must not, because a promise that
    only covers the screen is not the promise the README makes.
    """

    ANSWER = ("THEME: get the service deployed\n"
              "PROJECTS: api\n"
              "DID: the tests were run and the change went in.\n"
              "OPEN: the deploy has not happened yet.\n")

    def test_the_prompt_carries_your_half_and_not_the_agents(self):
        model, capture = self.a_model_that_keeps_what_it_was_sent(self.ANSWER)
        p = self.run_log("--brief", AGENTLOG_MODEL_CMD=model)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(capture, encoding="utf-8") as fh:
            sent = fh.read()
        self.assertIn(ASKED, sent,
                      "the model was asked what the work was for without "
                      "being told what was asked for")
        self.assertNotIn(SECRET, sent,
                         "the agent's half of the conversation left the "
                         "machine:\n" + sent)

    def test_the_page_does_not_read_your_own_prompt_back_to_you(self):
        # The reason this view exists.  The digest prints `asked "..."`; a
        # report does not, because the person reading it typed it.
        model, _ = self.a_model_that_keeps_what_it_was_sent(self.ANSWER)
        p = self.run_log("--brief", AGENTLOG_MODEL_CMD=model)
        self.assertNotIn(ASKED, p.stdout, p.stdout)
        self.assertNotIn(SECRET, p.stdout + p.stderr)
        self.assertIn("get the service deployed", p.stdout, p.stdout)

    def test_with_no_model_it_still_prints_and_still_says_nothing(self):
        # The degraded page is the one that runs on a machine with no CLI
        # installed, so it is the one most likely to be seen and the least
        # likely to be looked at.
        gone = os.path.join(self.out, "no-such-model")
        p = self.run_log("--brief", AGENTLOG_MODEL_CMD=gone)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(SECRET, p.stdout + p.stderr)
        self.assertIn("no summary", p.stdout, p.stdout)

    def test_nothing_is_sent_by_any_other_mode(self):
        # `--brief` is the exception; the exception has to have an edge.  Every
        # other mode runs with the same model command pointed at a file, and
        # the file must not appear.
        model, capture = self.a_model_that_keeps_what_it_was_sent(self.ANSWER)
        for mode in ((), ("--sessions",), ("--json",), ("week",), ("list",),
                     ("show", CLAUDE_SID[:8])):
            with self.subTest(mode=mode or ("default",)):
                self.run_log(*mode, AGENTLOG_MODEL_CMD=model)
                self.assertFalse(os.path.exists(capture),
                                 "{} asked a model".format(mode or "default"))

    def test_the_file_outputs_do_not_quietly_become_briefs(self):
        # A brief is read and thrown away; `--html` and `--md` are files people
        # send to each other.  Mixing them would put model-written prose into a
        # document that is otherwise all facts, so the CLI refuses.
        for flag in ("--html", "--md", "--json", "--sessions"):
            with self.subTest(flag=flag):
                argv = ["--brief", flag]
                if flag in ("--html", "--md"):
                    argv.append(os.path.join(self.out, "out" + flag))
                p = self.run_log(*argv)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn("--brief", p.stderr)


class TestTheRecordsNobodyReads(Case):
    """The promise has to hold for records no branch was written for.

    Claude Code writes more into a session file than the conversation.  Two of
    those types carry message text, and neither is a `user` record, so neither
    passes any of the care that one gets:

      - `queue-operation` (4983 on this machine) carries, in `content`, the
        whole of a prompt somebody typed while the agent was busy.
      - `frame-link` (104) carries, in `title`, a question of theirs turned
        into a heading.

    agentlog has no branch for either, so today the marker cannot come out.
    That is the point of pinning it: "we never wrote the code to read that" is
    a fact about this version, and the sentence in the README is a promise
    about every version.  The wide output surface is what makes it worth
    pinning here — the HTML digest is a file somebody sends to somebody else,
    and a leak into it does not stay on one machine.
    """

    def test_no_mode_prints_it(self):
        for mode in ((), ("--sessions",), ("--json",), ("--verbose",),
                     ("list",), ("show", CLAUDE_SID[:8])):
            with self.subTest(mode=mode or ("default",)):
                p = self.run_log(*mode)
                self.assertNotIn(SECRET, p.stdout + p.stderr)

    def test_neither_file_output_carries_it(self):
        for flag, name in (("--html", "digest.html"), ("--md", "digest.md")):
            with self.subTest(output=flag):
                dest = os.path.join(self.out, name)
                p = self.run_log(flag, dest)
                self.assertEqual(p.returncode, 0, p.stderr)
                with open(dest, encoding="utf-8") as fh:
                    body = fh.read()
                self.assertNotIn(SECRET, body)
                self.assertIn(COMMAND, body, "the digest reported no activity")

    def test_a_queued_prompt_is_not_a_turn(self):
        # Tempting, because an enqueue is the most literal record there is of a
        # person typing.  It is still wrong twice over: the prompt is written
        # again as a `user` record when it is sent, and more than half are never
        # sent at all — 2494 enqueues on this machine against 1121 dequeues and
        # 1358 removes.  Counting them would report turns that never happened
        # and count the rest twice.
        p = self.run_log("--json", "--sessions")
        data = json.loads(p.stdout)
        self.assertIn(CLAUDE_SID[:8], json.dumps(data),
                      "the Claude log was not read")
        s = _claude_session(data)
        # Both the running count and the event stream, because they are kept
        # separately — the count is the parser's and the stream is what a
        # clipped window is recounted from, so a change to one and not the
        # other is a thing that happens and would slip past a single assertion.
        self.assertEqual(s["user_turns"], 1, s)
        self.assertEqual(len([e for e in s["events"] if e[1] == "turn"]), 1, s)

    def test_the_fixture_really_contains_them(self):
        # Without this the tests above pass on a fixture that lost the records
        # in an edit, which is the same shape of vacuous pass this file was
        # written to avoid.
        log = claude_log(self.day)
        types = [json.loads(l)["type"] for l in log.splitlines()]
        self.assertIn("queue-operation", types)
        self.assertIn("frame-link", types)
        # Eight places the agent's half of the conversation is written down,
        # and exactly one prompt.  Both counts, because the fixture now carries
        # two opposite promises and losing either marker in an edit would leave
        # half the file passing on nothing.
        self.assertEqual(log.count(SECRET), 8, "the secret marker moved")
        self.assertEqual(log.count(ASKED), 1, "the prompt marker moved")
        self.assertEqual(codex_log(self.day).count(ASKED), 1,
                         "the prompt marker moved in the Codex fixture")


def _claude_session(data):
    """The one session dict for the Claude fixture, out of `--json --sessions`."""
    for s in data:
        if s.get("id") == CLAUDE_SID:
            return s
    raise AssertionError("no session for " + CLAUDE_SID + ": " +
                         json.dumps(data)[:2000])


class TestTheSessionLogsAreNotWrittenTo(Case):

    def test_nothing_under_the_home_changes(self):
        before = _tree_digest(self.home)
        for mode in ((), ("--sessions",), ("--json",), ("week",), ("list",)):
            self.run_log(*mode)
        self.assertEqual(_tree_digest(self.home), before,
                         "a read-only tool changed something it read")

    def test_no_file_is_created_beside_them(self):
        # No cache, no index, no config: `--home` is somebody's real `~`, and
        # this tool's own state has no business being written into it.
        before = set(_tree_digest(self.home))
        self.run_log()
        self.run_log("--html", os.path.join(self.out, "d.html"))
        self.assertEqual(set(_tree_digest(self.home)), before)

    def test_the_html_lands_where_it_was_asked_to(self):
        # The one file this tool does write, written only where it was told.
        dest = os.path.join(self.out, "sub", "digest.html")
        os.makedirs(os.path.dirname(dest))
        before = _tree_digest(self.home)
        self.run_log("--html", dest)
        self.assertTrue(os.path.exists(dest))
        self.assertEqual(_tree_digest(self.home), before)


class TestThereIsNoNetworkCode(unittest.TestCase):
    """Read the package's own imports, rather than trusting the sentence."""

    def _sources(self):
        pkg = os.path.join(_ROOT, "agentlog")
        for dirpath, _, names in os.walk(pkg):
            for name in sorted(names):
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)

    def test_nothing_that_can_open_a_socket_is_imported(self):
        for path in self._sources():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    top = name.split(".")[0]
                    self.assertNotIn(
                        top, NETWORK_MODULES,
                        "{}:{} imports {}".format(
                            os.path.basename(path), node.lineno, name))

    def test_only_one_named_module_may_run_another_program(self):
        # The exception has to be *locatable*, not merely small.  A model call
        # added to `render.py` would be as offline-looking as the rest of the
        # file and nobody re-reads a package's imports by hand every release.
        offenders = []
        for path in self._sources():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] not in RUNS_ANOTHER_PROGRAM:
                        continue
                    if os.path.basename(path) == MAY_RUN_ANOTHER_PROGRAM:
                        continue
                    offenders.append("{}:{} imports {}".format(
                        os.path.basename(path), node.lineno, name))
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_one_module_that_may_is_still_there_to_be_confined(self):
        # Otherwise the test above passes forever on a package that no longer
        # has the exception -- and the day somebody adds a second one, it would
        # be this file that said nothing.
        here = os.path.join(_ROOT, "agentlog", MAY_RUN_ANOTHER_PROGRAM)
        self.assertTrue(os.path.exists(here), here)
        with open(here, encoding="utf-8") as fh:
            self.assertIn("import subprocess", fh.read())

    def test_running_a_program_by_the_back_door_is_not_a_way_round_it(self):
        # `os.system` and `os.popen` need no import to find, so the check above
        # cannot see them at all.
        for path in self._sources():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                if not isinstance(fn, ast.Attribute):
                    continue
                base = getattr(fn.value, "id", None)
                if base == "os" and fn.attr in ("system", "popen",
                                                "spawnl", "spawnv", "execv"):
                    self.fail("{}:{} runs a program through os.{}".format(
                        os.path.basename(path), node.lineno, fn.attr))

    def test_no_import_is_hidden_behind_a_string(self):
        # The check above reads import statements, so a module named by a
        # string would walk straight past it.
        for path in self._sources():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                self.assertNotIn(
                    name, ("__import__", "import_module"),
                    "{}:{} imports by name at runtime".format(
                        os.path.basename(path), node.lineno))

    def _digest_html(self):
        home = tempfile.mkdtemp(prefix="al-privacy-net-")
        self.addCleanup(shutil.rmtree, home, True)
        os.makedirs(os.path.join(home, ".claude", "projects"))
        dest = os.path.join(home, "digest.html")
        subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", home, "--html", dest],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))
        with open(dest, encoding="utf-8") as fh:
            return fh.read()

    def test_the_html_digest_fetches_nothing_when_opened(self):
        # "Self-contained" is a privacy claim as much as a convenience one: a
        # remote font, stylesheet or script tells its host every time the file
        # is opened, from wherever it was opened, and this file is the artifact
        # people share.
        #
        # What matters is what the browser fetches on load, not every mention
        # of a URL.  The footer links to the project on GitHub; a link is only
        # followed if a reader chooses to follow it, and stripping it would buy
        # nothing.  So the check is for the attributes and rules that load a
        # subresource, which is the actual leak.
        html = self._digest_html()
        for marker in ("src=", "<script", "<iframe", "<link ", "@import",
                       "url(http", "url(//", "srcset="):
            self.assertNotIn(marker, html,
                             "the HTML digest loads a subresource: " + marker)

    def test_the_only_outside_urls_are_links_a_reader_may_click(self):
        # The complement of the test above: prove the URLs that *are* in the
        # file are all `<a href>`, so the check above cannot be satisfied by a
        # remote reference written some way it does not name.
        import re
        html = self._digest_html()
        for m in re.finditer(r"https?://", html):
            start = html.rfind("<", 0, m.start())
            tag = html[start:m.start()]
            self.assertTrue(tag.startswith("<a ") and 'href="' in tag,
                            "a URL outside an <a href>: " + repr(
                                html[start:m.start() + 60]))

    def test_the_readme_still_makes_the_claim(self):
        # If a promise is ever dropped from the README, these tests should be
        # revisited rather than left guarding a sentence nobody makes any more.
        with open(os.path.join(_ROOT, "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        for claim in ("No network code",
                      "Nothing is uploaded or sent",
                      "Half of a conversation is shown, and it is your half",
                      "The agent's half is never shown"):
            self.assertIn(claim, text)
        # The promise has been narrowed twice, each time because something new
        # started being shown: first for `away_summary` recaps, then for the
        # prompt that names the work.  A README still making either older,
        # wider promise would be making a false one, and this file would be
        # guarding a sentence nobody keeps.
        self.assertNotIn("Message text is never extracted or displayed", text)
        self.assertNotIn("Conversation text is never extracted or displayed",
                         text)
        self.assertIn("away_summary", text)
        # And now there is one command that does send something, so a README
        # making the old unqualified claim would be making a false one.  The
        # exception has to be named in the same section as the promise: a
        # person deciding whether to run this tool reads one place.
        self.assertIn("--brief", text, "the README does not mention --brief")
        privacy = text.split("## Privacy", 1)[1].split("\n---", 1)[0]
        self.assertIn("--brief", privacy,
                      "the privacy section does not name the one command that "
                      "sends anything")
        self.assertIn("asking_a_model.py", privacy,
                      "the privacy section does not say where the exception "
                      "lives, so a reader cannot check it")


if __name__ == "__main__":
    unittest.main()
