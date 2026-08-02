"""Tests for agentlog.parser — covering normal operation and edge cases."""

import json
import os
import sys
import tempfile
import unittest

# Ensure the package is importable when running from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentlog.parser import (
    _decode_claude_path,
    _dedup,
    _ts,
    find_sessions,
    parse_claude_session,
    parse_codex_session,
)
from tests.fixtures import (
    claude_assistant,
    claude_user,
    claude_user_with_error,
    codex_function_call,
    codex_session_meta,
    codex_token_count,
    codex_user_message,
    make_claude_project,
    make_codex_dir,
    tool_bash,
    tool_edit,
    tool_read,
    tool_write,
)


def _write_jsonl(path: str, records: list) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


class TestTsHelper(unittest.TestCase):
    def test_utc_z(self):
        dt = _ts("2026-07-16T17:23:23.427Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.hour, 17)

    def test_offset(self):
        dt = _ts("2026-07-16T10:00:00+05:00")
        self.assertIsNotNone(dt)

    def test_empty(self):
        self.assertIsNone(_ts(""))
        self.assertIsNone(_ts(None))

    def test_garbage(self):
        self.assertIsNone(_ts("not-a-date"))


class TestDedup(unittest.TestCase):
    def test_preserves_order(self):
        result = _dedup(["b", "a", "b", "c", "a"])
        self.assertEqual(result, ["b", "a", "c"])

    def test_empty(self):
        self.assertEqual(_dedup([]), [])


class TestDecodeClaudePath(unittest.TestCase):
    def test_basic(self):
        # -home-val-orchestrator -> home/val/orchestrator (leading / dropped by encoding)
        # We just check it starts with the expected prefix
        result = _decode_claude_path("/home/val/.claude/projects/-home-val-orchestrator/session.jsonl")
        self.assertIn("home", result)
        self.assertIn("val", result)


class TestParseClaudeSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def _session_file(self, records: list, name: str = "test-session.jsonl") -> str:
        proj = os.path.join(self.tmp, ".claude", "projects", "-home-test")
        os.makedirs(proj, exist_ok=True)
        path = os.path.join(proj, name)
        _write_jsonl(path, records)
        return path

    def test_basic_session(self):
        sid = "abc12345-0000-0000-0000-000000000000"
        records = [
            claude_user(sid, "2026-07-16T10:00:00Z", cwd="/home/test/proj"),
            claude_assistant(
                sid,
                "2026-07-16T10:01:00Z",
                tools=[tool_read("/home/test/proj/src/app.py", "t1")],
            ),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["project"], "/home/test/proj")
        self.assertEqual(sess["user_turns"], 1)
        self.assertIn("/home/test/proj/src/app.py", sess["files_read"])
        self.assertNotIn("/home/test/proj/src/app.py", sess["files_written"])

    def test_write_and_edit_go_to_files_written(self):
        sid = "aaa-0000"
        records = [
            claude_user(sid, "2026-07-16T10:00:00Z"),
            claude_assistant(
                sid,
                "2026-07-16T10:01:00Z",
                tools=[
                    tool_write("/tmp/foo.py", "tw1"),
                    tool_edit("/tmp/bar.py", "te1"),
                ],
            ),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertIn("/tmp/foo.py", sess["files_written"])
        self.assertIn("/tmp/bar.py", sess["files_written"])

    def test_bash_command_extracted(self):
        sid = "bbb-0001"
        records = [
            claude_user(sid, "2026-07-16T10:00:00Z"),
            claude_assistant(
                sid,
                "2026-07-16T10:01:00Z",
                tools=[tool_bash("python3 -m pytest", "tb1")],
            ),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertIn("python3 -m pytest", sess["commands"])

    def test_tool_dedup_same_id(self):
        """Same tool_use id appearing in two records should not be double-counted."""
        sid = "ccc-0002"
        records = [
            claude_user(sid, "2026-07-16T10:00:00Z"),
            # Same message id and tool id — simulates streaming split records
            claude_assistant(sid, "2026-07-16T10:01:00Z",
                             msg_id="msg_dup",
                             tools=[tool_read("/tmp/a.py", "tid1")]),
            claude_assistant(sid, "2026-07-16T10:01:01Z",
                             msg_id="msg_dup",
                             tools=[tool_read("/tmp/a.py", "tid1")]),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertEqual(sess["files_read"].count("/tmp/a.py"), 1)

    def test_token_dedup_same_msg_id(self):
        """Tokens from the same message_id should be counted only once."""
        sid = "ddd-0003"
        records = [
            claude_user(sid, "2026-07-16T10:00:00Z"),
            claude_assistant(sid, "2026-07-16T10:01:00Z",
                             msg_id="msg_tok", tokens_in=200, tokens_out=100),
            claude_assistant(sid, "2026-07-16T10:01:01Z",
                             msg_id="msg_tok", tokens_in=200, tokens_out=100),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertEqual(sess["tokens_in"], 200)
        self.assertEqual(sess["tokens_out"], 100)

    def test_error_in_tool_result(self):
        sid = "eee-0004"
        records = [
            claude_user(sid, "2026-07-16T10:00:00Z", cwd="/home/test/proj"),
            claude_assistant(sid, "2026-07-16T10:01:00Z"),
            claude_user_with_error(sid, "2026-07-16T10:01:30Z",
                                   cwd="/home/test/proj", tool_use_id="te1"),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertEqual(sess["errors"], 1)

    def test_empty_file_returns_none(self):
        path = self._session_file([])
        sess = parse_claude_session(path)
        self.assertIsNone(sess)

    def test_metadata_only_file_returns_none(self):
        """A file with only agent-setting/mode records should return None."""
        records = [
            {"type": "agent-setting", "agentSetting": "claude"},
            {"type": "mode", "mode": "normal"},
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertIsNone(sess)

    def test_malformed_lines_skipped(self):
        path = self._session_file([])
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("NOT JSON\n")
            fh.write("{\"type\": \"user\", \"timestamp\": \"2026-07-16T10:00:00Z\", "
                     "\"sessionId\": \"x\", \"cwd\": \"/tmp\", "
                     "\"message\": {\"role\": \"user\", \"content\": \"hi\"}}\n")
            fh.write("ALSO BAD\n")
        sess = parse_claude_session(path)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["skipped_lines"], 2)

    def test_duration_computed(self):
        sid = "fff-0005"
        records = [
            claude_user(sid, "2026-07-16T10:00:00Z"),
            claude_assistant(sid, "2026-07-16T10:05:00Z"),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertEqual(sess["duration_s"], 300.0)

    def test_models_collected(self):
        sid = "ggg-0006"
        records = [
            claude_user(sid, "2026-07-16T10:00:00Z"),
            claude_assistant(sid, "2026-07-16T10:01:00Z", model="claude-a", msg_id="m1"),
            claude_assistant(sid, "2026-07-16T10:02:00Z", model="claude-b", msg_id="m2"),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertIn("claude-a", sess["models"])
        self.assertIn("claude-b", sess["models"])

    def test_ai_title_captured(self):
        sid = "hhh-0007"
        records = [
            claude_user(sid, "2026-07-16T10:00:00Z"),
            {"type": "ai-title", "aiTitle": "refactor auth module", "sessionId": sid},
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertEqual(sess["ai_title"], "refactor auth module")

    def test_missing_file_returns_none(self):
        sess = parse_claude_session("/nonexistent/path/session.jsonl")
        self.assertIsNone(sess)

    def test_commands_deduped(self):
        sid = "iii-0008"
        records = [
            claude_user(sid, "2026-07-16T10:00:00Z"),
            claude_assistant(sid, "2026-07-16T10:01:00Z",
                             msg_id="m1", tools=[tool_bash("ls", "b1")]),
            claude_assistant(sid, "2026-07-16T10:02:00Z",
                             msg_id="m2", tools=[tool_bash("ls", "b2")]),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertEqual(sess["commands"].count("ls"), 1)


class TestParseCodexSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def _session_file(self, records: list, name: str = "rollout-2026-08-02T10-00-00-019fc000-0000-7000-0000-000000000000.jsonl") -> str:
        sess_dir = os.path.join(self.tmp, ".codex", "sessions", "2026", "08", "02")
        os.makedirs(sess_dir, exist_ok=True)
        path = os.path.join(sess_dir, name)
        _write_jsonl(path, records)
        return path

    def test_basic_codex_session(self):
        sid = "019fc000-0000-7000-0000-000000000001"
        records = [
            codex_session_meta(sid, "/home/test/proj", "2026-08-02T10:00:00Z"),
            codex_user_message("2026-08-02T10:00:01Z"),
            codex_function_call("exec_command", {"cmd": "ls -la"}, "2026-08-02T10:00:02Z"),
        ]
        path = self._session_file(records)
        sess = parse_codex_session(path)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["project"], "/home/test/proj")
        self.assertEqual(sess["source"], "codex")
        self.assertIn("ls -la", sess["commands"])

    def test_codex_tokens(self):
        sid = "019fc000-0000-7000-0000-000000000002"
        records = [
            codex_session_meta(sid, "/home/test", "2026-08-02T10:00:00Z"),
            codex_user_message("2026-08-02T10:00:01Z"),
            codex_token_count("2026-08-02T10:00:02Z", inp=1000, out=200),
        ]
        path = self._session_file(records)
        sess = parse_codex_session(path)
        self.assertEqual(sess["tokens_in"], 1000)
        self.assertEqual(sess["tokens_out"], 200)

    def test_codex_empty_returns_none(self):
        path = self._session_file([])
        sess = parse_codex_session(path)
        self.assertIsNone(sess)

    def test_codex_malformed_lines_skipped(self):
        path = self._session_file([])
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("GARBAGE\n")
            fh.write(json.dumps(codex_session_meta(
                "sid1", "/tmp", "2026-08-02T10:00:00Z")) + "\n")
            fh.write(json.dumps(codex_user_message("2026-08-02T10:00:01Z")) + "\n")
        sess = parse_codex_session(path)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["skipped_lines"], 1)


class TestFindSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def test_no_logs_returns_empty(self):
        sessions, sources = find_sessions(self.tmp)
        self.assertEqual(sessions, [])
        self.assertEqual(sources, [])

    def test_finds_claude_sessions(self):
        sid = "find-test-0000-0000-0000-000000000001"
        records = [claude_user(sid, "2026-07-16T10:00:00Z", cwd="/tmp/proj")]
        make_claude_project(self.tmp, "-home-test-proj", [records])
        sessions, sources = find_sessions(self.tmp)
        self.assertTrue(len(sessions) >= 1)
        self.assertIn("Claude Code", sources)

    def test_sessions_sorted_newest_first(self):
        proj_dir = os.path.join(self.tmp, ".claude", "projects", "-home-test")
        os.makedirs(proj_dir, exist_ok=True)
        for ts, name in [
            ("2026-07-16T08:00:00Z", "early.jsonl"),
            ("2026-07-16T18:00:00Z", "late.jsonl"),
        ]:
            sid = f"session-{name[:4]}"
            records = [claude_user(sid, ts, cwd="/tmp")]
            _write_jsonl(os.path.join(proj_dir, name), records)
        sessions, _ = find_sessions(self.tmp)
        valid = [s for s in sessions if s["start"] is not None]
        self.assertTrue(valid[0]["start"] > valid[-1]["start"])

    def test_symlink_not_double_counted(self):
        """A symlink pointing to an already-parsed file must not produce a second session."""
        proj_dir = os.path.join(self.tmp, ".claude", "projects", "-home-test")
        os.makedirs(proj_dir, exist_ok=True)
        sid = "symtest-0000-0000-0000-000000000001"
        records = [claude_user(sid, "2026-08-02T10:00:00Z", cwd="/tmp/proj")]
        real = os.path.join(proj_dir, "real.jsonl")
        _write_jsonl(real, records)
        link = os.path.join(proj_dir, "alias.jsonl")
        os.symlink(real, link)
        sessions, _ = find_sessions(self.tmp)
        # Only one session, despite two files on disk
        self.assertEqual(len(sessions), 1)

    def test_duplicate_session_id_deduplicated(self):
        """Two files with the same session_id (Codex parallel workers) appear as one session."""
        codex_dir = os.path.join(self.tmp, ".codex", "sessions", "2026", "08", "02")
        os.makedirs(codex_dir, exist_ok=True)
        shared_sid = "019fc000-aaaa-7000-0000-000000000099"

        # Worker A: 1 user turn
        _write_jsonl(
            os.path.join(codex_dir, "rollout-2026-08-02T10-00-00-019fc000-aaaa-7000-0000-000000000099.jsonl"),
            [
                codex_session_meta(shared_sid, "/tmp/relay", "2026-08-02T10:00:00Z"),
                codex_user_message("2026-08-02T10:00:01Z"),
            ],
        )
        # Worker B: 2 user turns — should be kept as the richer entry
        _write_jsonl(
            os.path.join(codex_dir, "rollout-2026-08-02T10-00-01-019fc000-aaaa-7000-0000-000000000099.jsonl"),
            [
                codex_session_meta(shared_sid, "/tmp/relay", "2026-08-02T10:00:00Z"),
                codex_user_message("2026-08-02T10:00:01Z"),
                codex_user_message("2026-08-02T10:00:02Z"),
            ],
        )
        sessions, _ = find_sessions(self.tmp)
        # Must be exactly one session
        self.assertEqual(len(sessions), 1)
        # Must be the richer one (2 turns)
        self.assertEqual(sessions[0]["user_turns"], 2)


class TestCacheTokens(unittest.TestCase):
    """Regression tests for HIGH #2: Claude cache field undercount."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def _session_file(self, records: list) -> str:
        proj = os.path.join(self.tmp, ".claude", "projects", "-home-test")
        os.makedirs(proj, exist_ok=True)
        path = os.path.join(proj, "cache-session.jsonl")
        _write_jsonl(path, records)
        return path

    def test_cache_creation_tokens_included(self):
        """cache_creation_input_tokens must be added to tokens_in."""
        sid = "cache-test-0000-0000-0000-000000000001"
        records = [
            claude_user(sid, "2026-08-02T10:00:00Z"),
            claude_assistant(
                sid, "2026-08-02T10:01:00Z",
                msg_id="m1",
                tokens_in=2,
                cache_creation_tokens=6000,
                cache_read_tokens=0,
                tokens_out=100,
            ),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        # tokens_in must include the cache creation field
        self.assertEqual(sess["tokens_in"], 6002)
        self.assertEqual(sess["tokens_out"], 100)

    def test_cache_read_tokens_included(self):
        """cache_read_input_tokens must be added to tokens_in."""
        sid = "cache-test-0000-0000-0000-000000000002"
        records = [
            claude_user(sid, "2026-08-02T10:00:00Z"),
            claude_assistant(
                sid, "2026-08-02T10:01:00Z",
                msg_id="m2",
                tokens_in=1,
                cache_creation_tokens=0,
                cache_read_tokens=20000,
                tokens_out=50,
            ),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertEqual(sess["tokens_in"], 20001)

    def test_all_three_cache_fields_summed(self):
        """All three input token fields are summed for a single message."""
        sid = "cache-test-0000-0000-0000-000000000003"
        records = [
            claude_user(sid, "2026-08-02T10:00:00Z"),
            claude_assistant(
                sid, "2026-08-02T10:01:00Z",
                msg_id="m3",
                tokens_in=5,
                cache_creation_tokens=1000,
                cache_read_tokens=2000,
                tokens_out=75,
            ),
        ]
        path = self._session_file(records)
        sess = parse_claude_session(path)
        self.assertEqual(sess["tokens_in"], 3005)


class TestCodexTokenInflation(unittest.TestCase):
    """Regression tests for HIGH #1: Codex cumulative token snapshot inflation."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def _session_file(self, records: list) -> str:
        sess_dir = os.path.join(self.tmp, ".codex", "sessions", "2026", "08", "02")
        os.makedirs(sess_dir, exist_ok=True)
        path = os.path.join(sess_dir, "rollout-2026-08-02T10-00-00-019fd000-0000-7000-0000-000000000001.jsonl")
        _write_jsonl(path, records)
        return path

    def test_multiturn_uses_final_snapshot_not_sum(self):
        """Multiple token_count records are cumulative; only the last value must be used."""
        sid = "019fd000-0000-7000-0000-000000000001"
        # Simulate 3 turns where each snapshot is cumulative:
        # turn 1: 13000, turn 2: 15000, turn 3: 25000
        # A broken implementation sums: 13000+15000+25000 = 53000
        # The correct answer is 25000 (the final snapshot)
        records = [
            codex_session_meta(sid, "/tmp/proj", "2026-08-02T10:00:00Z"),
            codex_user_message("2026-08-02T10:00:01Z"),
            codex_token_count("2026-08-02T10:00:02Z", inp=13000, out=100),
            codex_user_message("2026-08-02T10:01:00Z"),
            codex_token_count("2026-08-02T10:01:01Z", inp=15000, out=150),
            codex_user_message("2026-08-02T10:02:00Z"),
            codex_token_count("2026-08-02T10:02:01Z", inp=25000, out=200),
        ]
        path = self._session_file(records)
        sess = parse_codex_session(path)
        # Must equal the final snapshot, NOT the sum of all snapshots
        self.assertEqual(sess["tokens_in"], 25000)
        self.assertEqual(sess["tokens_out"], 200)
        # Confirm it is NOT the inflated sum
        self.assertNotEqual(sess["tokens_in"], 53000)
