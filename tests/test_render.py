"""Tests for agentlog.render — formatting output from session dicts."""

import json
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentlog.render import (
    _fmt_duration,
    render_json,
    render_list,
    render_markdown,
    render_show,
    render_text,
    summary_line,
)


def _make_session(**overrides) -> dict:
    """Return a minimal but valid session dict."""
    base = {
        "id": "abc12345-0000-0000-0000-000000000000",
        "source": "claude",
        "project": "/home/test/myproject",
        "project_name": "myproject",
        "start": datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc),
        "end": datetime(2026, 7, 16, 11, 30, 0, tzinfo=timezone.utc),
        "duration_s": 5400.0,
        "models": ["claude-test"],
        "user_turns": 5,
        "files_read": ["/home/test/myproject/src/app.py"],
        "files_written": ["/home/test/myproject/src/app.py"],
        "commands": ["python3 -m pytest", "git status"],
        "errors": 0,
        "tokens_in": 5000,
        "tokens_out": 1500,
        "ai_title": "fix the auth bug",
        "version": "2.1.0",
        "skipped_lines": 0,
    }
    base.update(overrides)
    return base


class TestFmtDuration(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(_fmt_duration(45), "45s")

    def test_minutes(self):
        self.assertEqual(_fmt_duration(125), "2m 05s")

    def test_hours(self):
        self.assertEqual(_fmt_duration(3720), "1h 02m")

    def test_none(self):
        self.assertEqual(_fmt_duration(None), "?")

    def test_zero(self):
        self.assertEqual(_fmt_duration(0), "0s")


class TestSummaryLine(unittest.TestCase):
    def test_empty(self):
        result = summary_line([])
        self.assertIn("0 sessions", result)

    def test_single_session(self):
        sess = _make_session(duration_s=3600)
        result = summary_line([sess])
        self.assertIn("1 session", result)
        # singular form
        self.assertNotIn("1 sessions", result)

    def test_multiple_sessions(self):
        sessions = [_make_session(duration_s=1800), _make_session(duration_s=900)]
        result = summary_line(sessions)
        self.assertIn("2 sessions", result)

    def test_errors_shown(self):
        sess = _make_session(errors=3)
        result = summary_line([sess])
        self.assertIn("error", result)


class TestRenderText(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(render_text([]), "")

    def test_contains_project_name(self):
        sess = _make_session()
        result = render_text([sess])
        self.assertIn("myproject", result)

    def test_contains_command(self):
        sess = _make_session(commands=["pytest"])
        result = render_text([sess])
        self.assertIn("pytest", result)

    def test_verbose_shows_skipped(self):
        sess = _make_session(skipped_lines=7)
        result = render_text([sess], verbose=True)
        self.assertIn("7", result)

    def test_no_verbose_hides_zero_skipped(self):
        sess = _make_session(skipped_lines=0)
        result = render_text([sess], verbose=False)
        self.assertNotIn("skipped", result)

    def test_file_truncation(self):
        """More than 6 files should show a '... and N more' line."""
        many_files = [f"/tmp/file{i}.py" for i in range(20)]
        sess = _make_session(files_read=many_files, files_written=[])
        result = render_text([sess])
        self.assertIn("more", result)


class TestRenderList(unittest.TestCase):
    def test_empty(self):
        result = render_list([])
        self.assertIn("no sessions", result)

    def test_header_present(self):
        sessions = [_make_session()]
        result = render_list(sessions)
        self.assertIn("PROJECT", result)
        self.assertIn("WHEN", result)

    def test_session_id_truncated(self):
        sess = _make_session()
        result = render_list([sess])
        # First 8 chars of id should appear
        self.assertIn("abc12345", result)


class TestRenderShow(unittest.TestCase):
    def test_contains_all_key_fields(self):
        sess = _make_session()
        result = render_show(sess)
        self.assertIn("session", result)
        self.assertIn("project", result)
        self.assertIn("duration", result)
        self.assertIn("errors", result)

    def test_files_listed(self):
        sess = _make_session(
            files_read=["/tmp/a.py", "/tmp/b.py"],
            files_written=["/tmp/c.py"],
        )
        result = render_show(sess)
        self.assertIn("/tmp/a.py", result)
        self.assertIn("/tmp/c.py", result)

    def test_commands_listed(self):
        sess = _make_session(commands=["make build"])
        result = render_show(sess)
        self.assertIn("make build", result)


class TestRenderMarkdown(unittest.TestCase):
    def test_has_heading(self):
        result = render_markdown([_make_session()])
        self.assertIn("# agentlog", result)

    def test_has_session_project(self):
        sess = _make_session()
        result = render_markdown([sess])
        self.assertIn("myproject", result)


class TestRenderJson(unittest.TestCase):
    def test_valid_json(self):
        sessions = [_make_session()]
        result = render_json(sessions)
        data = json.loads(result)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["project_name"], "myproject")

    def test_datetimes_serialized(self):
        sess = _make_session()
        result = render_json([sess])
        data = json.loads(result)
        self.assertIsInstance(data[0]["start"], str)

    def test_empty_list(self):
        result = render_json([])
        self.assertEqual(json.loads(result), [])

    def test_none_timestamps(self):
        sess = _make_session(start=None, end=None)
        result = render_json([sess])
        data = json.loads(result)
        self.assertIsNone(data[0]["start"])
