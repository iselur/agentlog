"""The promises under ## Privacy, held to end-to-end.

    agentlog is strictly local.  No network code.  Nothing is uploaded or sent.

    It shows metadata only: file paths, shell commands, durations, and model
    names.  Message text is never extracted or displayed.

That is the reason somebody points this tool at their own transcripts, so it
is a contract and not a description.  The parser tests check the reading, one
record shape at a time.  This file checks the whole tool the way a user meets
it: a home directory whose logs are full of a marker word, every output mode
run over it, and the marker looked for in everything that comes back.

agentlog has a wider output surface than a tailer does — a digest, a session
list, JSON, Markdown, a self-contained HTML file, a single-session view, and a
diagnostics mode — and each is a separate chance to print something.  The HTML
one matters most: it is a file, written to be sent to somebody, and the README
warns it carries paths and commands.  It must not also carry the message text
that the same README says is never extracted.

The marker goes only in fields that are message text.  What *must* come out is
the activity beside it — the command, the path — so a run that printed nothing
cannot pass this file by having no output to search.  That vacuous-pass shape
has caught this project before.
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
# it came out of a log.
SECRET = "SQUIRRELPLUM"

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


def claude_log(day):
    """A Claude Code session with a secret in every field that is message text."""
    return "\n".join(json.dumps(r) for r in [
        {"type": "user", "timestamp": day + "T09:00:00Z",
         "sessionId": CLAUDE_SID, "cwd": "/home/you/api",
         "message": {"role": "user", "content": [
             {"type": "text", "text": "deploy with token " + SECRET}]}},
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
         "payload": {"type": "user_message", "message": "the key is " + SECRET}},
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

    def run_log(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home, *argv],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100"))


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
                      "Message text is never extracted or displayed"):
            self.assertIn(claim, text)


if __name__ == "__main__":
    unittest.main()
