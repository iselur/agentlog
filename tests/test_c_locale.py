"""What agentlog does on a machine whose locale says ASCII.

A container with no locale set is the ordinary case, not the exotic one: it is
what CI runs on, what a Dockerfile without `ENV LANG` gives you, and what cron
hands a hook — and a daily summary is exactly the sort of thing somebody puts
in cron.  Python takes the locale at its word there, so stdout encodes as ASCII
and argv decodes as ASCII too.

Both fail rather than degrade, and in different ways.  The digest prints an em
dash of its own, so on that machine the whole report dies partway through with a
traceback.  And `--project 設定` arrives as a run of surrogates and matches
nothing, which is the worse of the two: it does not look like a failure, it
looks like a quiet day.

Everything here runs the real command in a real subprocess with that
environment, because the codec is chosen when the process starts and cannot be
faked from inside one.
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


def _ascii_env():
    """The environment of a container nobody gave a locale to."""
    env = dict(os.environ)
    env.update(LC_ALL="C", LANG="C", LANGUAGE="C",
               PYTHONCOERCECLOCALE="0",   # or Python quietly upgrades C to C.UTF-8
               PYTHONUTF8="0",            # or UTF-8 mode overrides the locale
               PYTHONPATH=_ROOT)
    env.pop("PYTHONIOENCODING", None)
    return env


def _ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


class TestAnAsciiMachine(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="agentlog_locale_")
        folder = os.path.join(self.home, ".claude", "projects", "-home-you-設定")
        os.makedirs(folder)
        with open(os.path.join(folder, "s.jsonl"), "w", encoding="utf-8") as fh:
            for line in (
                {"type": "user", "cwd": "/home/you/設定", "timestamp": _ago(30),
                 "message": {"role": "user",
                             "content": [{"type": "text", "text": "hi"}]}},
                {"type": "assistant", "timestamp": _ago(29), "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "t1", "name": "Edit",
                                 "input": {"file_path": "/home/you/設定/請求書.py"}}]}},
                {"type": "user", "timestamp": _ago(28), "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "t1",
                                 "content": "ok"}]}},
            ):
                fh.write(json.dumps(line) + "\n")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_log(self, *args):
        result = subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home] + list(args),
            capture_output=True, text=True, encoding="utf-8", env=_ascii_env(),
            cwd=_ROOT, timeout=60)
        self.assertNotIn("Traceback", result.stderr,
                         "{}: {}".format(args, result.stderr))
        return result

    def test_the_digest_prints_without_a_traceback(self):
        # Nothing here is unusual.  The em dash is ours.
        result = self.run_log("today")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_view_prints_without_a_traceback(self):
        for args in (("today",), ("today", "--sessions"), ("list",),
                     ("week",), ("today", "--json")):
            self.run_log(*args)

    def test_the_project_it_names_is_the_project(self):
        self.assertIn("設定", self.run_log("today").stdout)

    def test_filtering_by_a_project_named_in_japanese_finds_it(self):
        # The failure that does not look like one: no rows, exit 0, and a
        # perfectly calm report of a day in which apparently nothing happened.
        out = self.run_log("today", "--project", "設定").stdout
        self.assertIn("1 session", out, out)
        self.assertIn("設定", out, out)

    def test_filtering_a_codex_session_by_project_finds_it(self):
        # Claude Code spells the project into the folder name, so a filter on
        # that name matches the path by luck even when both sides are mangled
        # the same way.  A Codex log is a bare UUID under a date, and the only
        # place the project is named is inside the file — so here the filter
        # has nothing mangled to match against, and the day comes back empty.
        folder = os.path.join(self.home, ".codex", "sessions", "2026", "08", "04")
        os.makedirs(folder)
        sid = "0199c1d4-0000-7000-8000-000000000001"
        with open(os.path.join(folder, "rollout-{}.jsonl".format(sid)), "w",
                  encoding="utf-8") as fh:
            for line in (
                {"timestamp": _ago(20), "type": "session_meta",
                 "payload": {"session_id": sid, "id": sid, "cwd": "/srv/請求",
                             "timestamp": _ago(20), "cli_version": "0.1.0"}},
                {"timestamp": _ago(19), "type": "response_item",
                 "payload": {"type": "function_call", "name": "exec_command",
                             "arguments": json.dumps({"command": "pytest"})}},
            ):
                fh.write(json.dumps(line) + "\n")

        # Asserted against the session's own contents, not the project name:
        # the "nothing matched" line quotes the filter back, so looking for the
        # name would be satisfied by the very message that says it found none.
        out = self.run_log("today", "--project", "請求").stdout
        self.assertNotIn("no ", out.split("\n")[0].lower(), out)
        self.assertIn("1 session", out, out)

    def test_the_json_stays_json(self):
        data = json.loads(self.run_log("today", "--json").stdout)
        self.assertIn("設定", json.dumps(data, ensure_ascii=False))

    def test_the_written_report_is_readable_afterwards(self):
        # An HTML report is written on one machine and opened on another; if
        # the locale picked the codec it would not survive the trip.
        for flag, name in (("--html", "r.html"), ("--md", "r.md")):
            path = os.path.join(self.home, name)
            self.run_log("today", flag, path)
            with open(path, encoding="utf-8") as fh:
                self.assertIn("設定", fh.read(), path)


if __name__ == "__main__":
    unittest.main()
