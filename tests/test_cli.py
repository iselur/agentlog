"""Tests for agentlog.cli — argument parsing, filtering, and exit codes."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentlog.cli import main
from agentlog.window import _filter_sessions
from tests.fixtures import (
    claude_user,
    claude_assistant,
    tool_bash,
)

import json as _json


def _write_jsonl(path: str, records: list) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(_json.dumps(rec) + "\n")


def _setup_claude_project(tmp: str, sessions_records: list) -> None:
    """Write session files into tmp/.claude/projects/-home-test/"""
    proj = os.path.join(tmp, ".claude", "projects", "-home-test")
    os.makedirs(proj, exist_ok=True)
    for i, recs in enumerate(sessions_records):
        _write_jsonl(os.path.join(proj, f"sess{i}.jsonl"), recs)


class TestFilterSessions(unittest.TestCase):
    def _make_sessions(self):
        from datetime import datetime, timezone
        return [
            {
                "id": "a",
                "start": datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc),
                "end": datetime(2026, 7, 16, 11, 0, tzinfo=timezone.utc),
            },
            {
                "id": "b",
                "start": datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc),
                "end": datetime(2026, 7, 17, 11, 0, tzinfo=timezone.utc),
            },
        ]

    def test_since_filters_old(self):
        from datetime import datetime, timezone
        sessions = self._make_sessions()
        since = datetime(2026, 7, 17, tzinfo=timezone.utc)
        result = _filter_sessions(sessions, since=since)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "b")

    def test_until_filters_new(self):
        from datetime import datetime, timezone
        sessions = self._make_sessions()
        until = datetime(2026, 7, 17, tzinfo=timezone.utc)
        result = _filter_sessions(sessions, until=until)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "a")

    def test_no_start_excluded(self):
        sessions = [{"id": "x", "start": None}]
        result = _filter_sessions(sessions)
        self.assertEqual(result, [])


class TestMainCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Capture stdout
        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)
        sys.stdout = self._old_stdout
        sys.stderr = self._old_stderr

    def _run(self, argv):
        import io
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        code = main(argv)
        out = sys.stdout.getvalue()
        err = sys.stderr.getvalue()
        sys.stdout = self._old_stdout
        sys.stderr = self._old_stderr
        return code, out, err

    def test_no_logs_exits_0(self):
        code, out, err = self._run(["--home", self.tmp, "today"])
        self.assertEqual(code, 0)
        self.assertIn("No agent session logs", out)

    def test_today_with_session(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        sid = "test-today-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        code, out, err = self._run(["--home", self.tmp, "today"])
        self.assertEqual(code, 0)
        self.assertIn("session", out)

    def test_list_command(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        sid = "test-list-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        code, out, err = self._run(["--home", self.tmp, "list"])
        self.assertEqual(code, 0)
        self.assertIn("ID", out)

    def test_unknown_command_exits_2(self):
        code, out, err = self._run(["--home", self.tmp, "badcommand"])
        self.assertEqual(code, 2)

    def test_since_missing_arg_exits_2(self):
        code, out, err = self._run(["--home", self.tmp, "since"])
        self.assertEqual(code, 2)

    def test_since_bad_arg_exits_2(self):
        code, out, err = self._run(["--home", self.tmp, "since", "notadate"])
        self.assertEqual(code, 2)

    def test_show_missing_arg_exits_2(self):
        code, out, err = self._run(["--home", self.tmp, "show"])
        self.assertEqual(code, 2)

    def test_show_not_found_exits_2(self):
        code, out, err = self._run(["--home", self.tmp, "show", "nosuchid"])
        self.assertEqual(code, 2)

    def test_json_output(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        sid = "test-json-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        code, out, err = self._run(["--home", self.tmp, "today", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIsInstance(data, list)

    def test_html_output(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        sid = "test-html-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        html_path = os.path.join(self.tmp, "digest.html")
        code, out, err = self._run(["--home", self.tmp, "today", "--html", html_path])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(html_path))
        with open(html_path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("<!doctype html", content)
        self.assertIn("agentlog", content)
        # No external URLs in the HTML
        self.assertNotIn("cdn.jsdelivr", content)
        self.assertNotIn("fonts.googleapis", content)
        self.assertNotIn("unpkg.com", content)

    def test_since_valid_date(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        sid = "test-since-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        import datetime as dt
        yesterday_str = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        code, out, err = self._run(["--home", self.tmp, "since", yesterday_str])
        self.assertEqual(code, 0)

    def test_markdown_to_stdout(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        sid = "test-md-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        code, out, err = self._run(["--home", self.tmp, "today", "--md"])
        self.assertEqual(code, 0)
        self.assertIn("# agentlog", out)

    def test_no_sessions_in_range(self):
        from datetime import datetime, timezone
        # Create a session from a week ago
        past = datetime(2020, 1, 1, 10, 0, tzinfo=timezone.utc)
        ts = past.strftime("%Y-%m-%dT%H:%M:%SZ")
        sid = "test-old-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        code, out, err = self._run(["--home", self.tmp, "today"])
        self.assertEqual(code, 0)
        self.assertIn("no sessions found", out)

    def test_show_by_prefix(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        # Use a session id that starts with 'testshow'
        sid = "testshow1-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        code, out, err = self._run(["--home", self.tmp, "show", "testshow"])
        self.assertEqual(code, 0)
        self.assertIn("session", out.lower())

    def test_list_json_output(self):
        """agentlog list --json must produce valid JSON, not a table."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        sid = "listjson0-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        code, out, err = self._run(["--home", self.tmp, "list", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) >= 1)

    def test_show_json_output(self):
        """agentlog show ID --json must produce valid JSON, not plain text."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        sid = "showjson0-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        code, out, err = self._run(["--home", self.tmp, "show", "showjson0", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], sid)

    def test_list_html_errors(self):
        """agentlog list --html must exit 2 with an error, not silently discard."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        sid = "listhtml0-0000-0000-0000-000000000001"
        recs = [claude_user(sid, ts, cwd="/tmp/proj")]
        _setup_claude_project(self.tmp, [recs])
        import os
        html_path = os.path.join(self.tmp, "out.html")
        code, out, err = self._run(["--home", self.tmp, "list", "--html", html_path])
        self.assertEqual(code, 2)
        self.assertIn("not supported", err)
        self.assertFalse(os.path.exists(html_path))

    def test_show_multiple_matches_warns(self):
        """show with a prefix that matches multiple sessions must warn on stderr."""
        import os
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        proj = os.path.join(self.tmp, ".claude", "projects", "-home-test")
        os.makedirs(proj, exist_ok=True)
        # Two sessions sharing the 'ambig000' prefix
        for i, sid in enumerate([
            "ambig000-aaaa-0000-0000-000000000001",
            "ambig000-bbbb-0000-0000-000000000002",
        ]):
            _write_jsonl(
                os.path.join(proj, f"sess{i}.jsonl"),
                [claude_user(sid, ts, cwd="/tmp/proj")],
            )
        code, out, err = self._run(["--home", self.tmp, "show", "ambig000"])
        self.assertEqual(code, 0)  # still exits 0, but warns
        self.assertIn("ambig000-aaaa", err)
        self.assertIn("ambig000-bbbb", err)

    def test_list_default_limit(self):
        """agentlog list shows at most 50 rows by default and prints a truncation note."""
        import os
        from datetime import datetime, timezone, timedelta
        proj = os.path.join(self.tmp, ".claude", "projects", "-home-test")
        os.makedirs(proj, exist_ok=True)
        # Write 55 sessions
        base = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
        for i in range(55):
            ts = (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            sid = f"limit{i:04d}-0000-0000-0000-000000000001"
            _write_jsonl(
                os.path.join(proj, f"sess{i}.jsonl"),
                [claude_user(sid, ts, cwd="/tmp/proj")],
            )
        code, out, err = self._run(["--home", self.tmp, "list"])
        self.assertEqual(code, 0)
        rows = [l for l in out.split("\n") if l.strip() and not l.startswith(("-", "I", "."))]
        # Should show at most 50 data rows
        self.assertLessEqual(len(rows), 50)
        self.assertIn("more", out)

    def test_list_all_flag(self):
        """agentlog list --all shows all sessions without truncation."""
        import os
        from datetime import datetime, timezone, timedelta
        proj = os.path.join(self.tmp, ".claude", "projects", "-home-test")
        os.makedirs(proj, exist_ok=True)
        base = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
        for i in range(55):
            ts = (base + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            sid = f"alltest{i:02d}-0000-0000-0000-000000000001"
            _write_jsonl(
                os.path.join(proj, f"sess{i}.jsonl"),
                [claude_user(sid, ts, cwd="/tmp/proj")],
            )
        code, out, err = self._run(["--home", self.tmp, "list", "--all"])
        self.assertEqual(code, 0)
        # Should NOT contain a truncation note
        self.assertNotIn("more", out)
        rows = [l for l in out.split("\n") if l.strip() and not l.startswith(("-", "I"))]
        self.assertGreaterEqual(len(rows), 55)


class TestWindowOverlap(unittest.TestCase):
    """A session that spans the window must appear in it, counted fairly."""

    def _spanning(self):
        from datetime import datetime, timezone
        return {
            "id": "long",
            "start": datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc),
            "end": datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc),
            "files_read": ["r1", "r2"],
            "files_written": ["w1", "w2"],
            "commands": ["c1", "c2"],
            "user_turns": 2,
            "errors": 2,
            "events": [
                (datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc), "read", "r1"),
                (datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc), "write", "w1"),
                (datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc), "cmd", "c1"),
                (datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc), "turn", ""),
                (datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc), "error", ""),
                (datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc), "read", "r2"),
                (datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc), "write", "w2"),
                (datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc), "cmd", "c2"),
                (datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc), "turn", ""),
                (datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc), "error", ""),
            ],
        }

    def test_session_started_before_window_is_included(self):
        from datetime import datetime, timezone
        since = datetime(2026, 7, 22, tzinfo=timezone.utc)
        until = datetime(2026, 7, 23, tzinfo=timezone.utc)
        result = _filter_sessions([self._spanning()], since=since, until=until)
        self.assertEqual(len(result), 1, "long-running session vanished from the window")

    def test_window_seconds_is_the_overlap_not_the_lifetime(self):
        # This used to assert the full 24h — the width of the window itself.
        # That was the overnight bug: everything inside this fixture's window
        # happened at one instant, 10:00, and reporting a day of activity for
        # it is how one command at 09:16 headlined as `9h 16m active`.  The
        # test's point stands and is asserted below: not the lifetime.  Its
        # number was the old approximation, and the honest bound is the first
        # and last event that actually landed inside.
        from datetime import datetime, timezone
        since = datetime(2026, 7, 22, tzinfo=timezone.utc)
        until = datetime(2026, 7, 23, tzinfo=timezone.utc)
        s = _filter_sessions([self._spanning()], since=since, until=until)[0]
        self.assertEqual(s["window_s"], 0.0)
        self.assertLess(s["window_s"], 3 * 24 * 3600, "the lifetime came back")

    def test_counts_are_clipped_to_the_window(self):
        from datetime import datetime, timezone
        since = datetime(2026, 7, 22, tzinfo=timezone.utc)
        until = datetime(2026, 7, 23, tzinfo=timezone.utc)
        s = _filter_sessions([self._spanning()], since=since, until=until)[0]
        self.assertEqual(s["files_read"], ["r2"])
        self.assertEqual(s["files_written"], ["w2"])
        self.assertEqual(s["commands"], ["c2"])
        self.assertEqual(s["user_turns"], 1)
        self.assertEqual(s["errors"], 1)

    def test_original_session_is_not_mutated(self):
        from datetime import datetime, timezone
        original = self._spanning()
        _filter_sessions([original],
                         since=datetime(2026, 7, 22, tzinfo=timezone.utc),
                         until=datetime(2026, 7, 23, tzinfo=timezone.utc))
        self.assertEqual(original["user_turns"], 2)
        self.assertEqual(original["files_written"], ["w1", "w2"])

    def test_fully_contained_session_is_not_clipped(self):
        from datetime import datetime, timezone
        s = dict(self._spanning())
        s["start"] = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
        s["end"] = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
        out = _filter_sessions([s],
                               since=datetime(2026, 7, 22, tzinfo=timezone.utc),
                               until=datetime(2026, 7, 23, tzinfo=timezone.utc))[0]
        self.assertNotIn("window_s", out)
        self.assertEqual(out["user_turns"], 2)

    def test_session_entirely_before_window_excluded(self):
        from datetime import datetime, timezone
        out = _filter_sessions([self._spanning()],
                               since=datetime(2026, 7, 24, tzinfo=timezone.utc))
        self.assertEqual(out, [])

    def test_session_without_events_keeps_lifetime_counts(self):
        from datetime import datetime, timezone
        s = self._spanning()
        s["events"] = []
        out = _filter_sessions([s],
                               since=datetime(2026, 7, 22, tzinfo=timezone.utc),
                               until=datetime(2026, 7, 23, tzinfo=timezone.utc))[0]
        self.assertEqual(out["user_turns"], 2)


class TestDigestCLI(unittest.TestCase):
    """The default view, its flags, and end-to-end failure attribution."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)
        sys.stdout = self._old_stdout
        sys.stderr = self._old_stderr

    def _run(self, argv):
        import io
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        code = main(argv)
        out = sys.stdout.getvalue()
        sys.stdout = self._old_stdout
        sys.stderr = self._old_stderr
        return code, out

    def _ts(self, minutes_ago=5):
        """A moment `minutes_ago` back that is still today.

        See fixtures.a_now_that_keeps: "five minutes ago" and "today" are the
        same thing except between 00:00 and 00:05.
        """
        from datetime import timedelta, timezone

        from tests.fixtures import a_now_that_keeps
        now = a_now_that_keeps(minutes_ago) - timedelta(minutes=minutes_ago)
        return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _claude_session(self, sid, cwd, tools=None, error_for=None):
        from tests.fixtures import claude_assistant, claude_user_with_error
        ts = self._ts()
        recs = [claude_user(sid, ts, cwd=cwd)]
        if tools:
            recs.append(claude_assistant(sid, ts, tools=tools))
        if error_for:
            recs.append(claude_user_with_error(sid, ts, cwd, error_for))
        return recs

    def test_default_is_the_project_digest(self):
        sid = "dg-000001-0000-0000-0000-000000000001"
        _setup_claude_project(self.tmp, [self._claude_session(sid, "/home/test/alpha")])
        code, out = self._run(["--home", self.tmp, "today"])
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)
        self.assertIn("active across", out)
        self.assertIn("more: agentlog list", out)

    def test_sessions_flag_restores_the_per_session_view(self):
        sid = "dg-000002-0000-0000-0000-000000000001"
        _setup_claude_project(self.tmp, [self._claude_session(sid, "/home/test/alpha")])
        code, out = self._run(["--home", self.tmp, "today", "--sessions"])
        self.assertEqual(code, 0)
        self.assertNotIn("active across", out)
        self.assertIn("dg-00000", out)

    def test_project_flag_filters_by_name(self):
        a = "dg-000003-0000-0000-0000-000000000001"
        b = "dg-000004-0000-0000-0000-000000000001"
        _setup_claude_project(
            self.tmp,
            [
                self._claude_session(a, "/home/test/alpha"),
                self._claude_session(b, "/home/test/beta"),
            ],
        )
        code, out = self._run(["--home", self.tmp, "today", "--project", "alpha"])
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)
        self.assertNotIn("beta", out)

    def test_project_flag_matches_the_path_too(self):
        sid = "dg-000005-0000-0000-0000-000000000001"
        _setup_claude_project(self.tmp, [self._claude_session(sid, "/home/test/alpha")])
        code, out = self._run(["--home", self.tmp, "today", "--project", "/home/test"])
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)

    def test_project_flag_with_no_match_is_not_an_error(self):
        sid = "dg-000006-0000-0000-0000-000000000001"
        _setup_claude_project(self.tmp, [self._claude_session(sid, "/home/test/alpha")])
        code, out = self._run(["--home", self.tmp, "today", "--project", "nope"])
        self.assertEqual(code, 0)
        self.assertIn("no sessions found", out)
        self.assertIn("nope", out)

    def test_claude_failure_names_the_failing_command(self):
        sid = "dg-000007-0000-0000-0000-000000000001"
        recs = self._claude_session(
            sid,
            "/home/test/alpha",
            tools=[tool_bash("make release", tool_id="tb1")],
            error_for="tb1",
        )
        _setup_claude_project(self.tmp, [recs])
        code, out = self._run(["--home", self.tmp, "today"])
        self.assertEqual(code, 0)
        self.assertIn("failed   make release", out)

    def test_claude_failure_on_an_edit_names_the_file(self):
        from tests.fixtures import tool_edit
        sid = "dg-000008-0000-0000-0000-000000000001"
        recs = self._claude_session(
            sid,
            "/home/test/alpha",
            tools=[tool_edit("/home/test/alpha/app.py", tool_id="te1")],
            error_for="te1",
        )
        _setup_claude_project(self.tmp, [recs])
        code, out = self._run(["--home", self.tmp, "today"])
        self.assertIn("failed   edit app.py", out)

    def test_codex_failure_names_the_failing_command(self):
        from tests.fixtures import (
            codex_function_call,
            codex_session_meta,
            codex_user_message,
            make_codex_dir,
        )
        ts = self._ts()
        sid = "019fc4b9-0000-7000-8000-000000000001"
        sessions_dir = make_codex_dir(self.tmp)
        recs = [
            codex_session_meta(sid, "/home/test/gamma", ts),
            codex_user_message(ts),
            codex_function_call("exec_command", {"cmd": "cargo build"}, ts, call_id="c1"),
            {
                "timestamp": ts,
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": {"metadata": {"exit_code": 101}},
                },
            },
        ]
        _write_jsonl(os.path.join(sessions_dir, f"rollout-{sid}.jsonl"), recs)
        code, out = self._run(["--home", self.tmp, "today"])
        self.assertEqual(code, 0)
        self.assertIn("failed   cargo build", out)

    def test_a_zero_exit_is_not_a_failure(self):
        from tests.fixtures import (
            codex_function_call,
            codex_session_meta,
            codex_user_message,
            make_codex_dir,
        )
        ts = self._ts()
        sid = "019fc4b9-0000-7000-8000-000000000002"
        sessions_dir = make_codex_dir(self.tmp)
        recs = [
            codex_session_meta(sid, "/home/test/gamma", ts),
            codex_user_message(ts),
            codex_function_call("exec_command", {"cmd": "cargo build"}, ts, call_id="c1"),
            {
                "timestamp": ts,
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": {"metadata": {"exit_code": 0}},
                },
            },
        ]
        _write_jsonl(os.path.join(sessions_dir, f"rollout-{sid}.jsonl"), recs)
        code, out = self._run(["--home", self.tmp, "today"])
        self.assertNotIn("failed", out)

    def test_json_output_carries_the_failed_commands(self):
        sid = "dg-000009-0000-0000-0000-000000000001"
        recs = self._claude_session(
            sid,
            "/home/test/alpha",
            tools=[tool_bash("make release", tool_id="tb1")],
            error_for="tb1",
        )
        _setup_claude_project(self.tmp, [recs])
        code, out = self._run(["--home", self.tmp, "today", "--json"])
        data = json.loads(out)
        self.assertEqual(data[0]["failed_cmds"], ["make release"])
