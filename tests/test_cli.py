"""Tests for agentlog.cli — argument parsing, filtering, and exit codes."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentlog.cli import _parse_since, _filter_sessions, main
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


class TestParseSince(unittest.TestCase):
    def test_iso_date(self):
        dt = _parse_since("2026-07-15")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 7)
        self.assertEqual(dt.day, 15)

    def test_days_offset(self):
        dt = _parse_since("3d")
        self.assertIsNotNone(dt)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        diff = now - dt
        self.assertAlmostEqual(diff.total_seconds() / 86400, 3, delta=0.1)

    def test_hours_offset(self):
        dt = _parse_since("12h")
        self.assertIsNotNone(dt)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        diff = now - dt
        self.assertAlmostEqual(diff.total_seconds() / 3600, 12, delta=0.1)

    def test_weeks_offset(self):
        dt = _parse_since("2w")
        self.assertIsNotNone(dt)

    def test_invalid_returns_none(self):
        self.assertIsNone(_parse_since("yesterday"))
        self.assertIsNone(_parse_since("garbage"))
        self.assertIsNone(_parse_since("3x"))


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
