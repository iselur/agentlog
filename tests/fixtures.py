"""Shared test fixtures and helpers.

The tests use a temporary directory for session files.  No real home
directory is ever touched.  Set AGENTLOG_HOME or pass --home to override.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import List


def make_claude_project(
    tmp_dir: str,
    project_name: str,
    sessions: List[List[dict]],
) -> str:
    """Create a fake Claude Code project directory with JSONL session files.

    Returns the path to the project dir inside tmp_dir/.claude/projects/
    """
    proj_dir = os.path.join(tmp_dir, ".claude", "projects", project_name)
    os.makedirs(proj_dir, exist_ok=True)

    for i, records in enumerate(sessions):
        path = os.path.join(proj_dir, f"session-{i:04d}.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
    return proj_dir


def make_codex_dir(tmp_dir: str) -> str:
    """Create the ~/.codex/sessions hierarchy."""
    codex_dir = os.path.join(tmp_dir, ".codex", "sessions")
    os.makedirs(codex_dir, exist_ok=True)
    return codex_dir


def claude_user(
    session_id: str,
    timestamp: str,
    cwd: str = "/home/test/myproject",
    version: str = "2.1.0",
    text: str = "do the thing",
) -> dict:
    return {
        "type": "user",
        "sessionId": session_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "version": version,
        "message": {"role": "user", "content": text},
        "uuid": "uuid-user-1",
    }


def claude_assistant(
    session_id: str,
    timestamp: str,
    model: str = "claude-test",
    msg_id: str = "msg_001",
    tools: list = None,
    tokens_in: int = 100,
    tokens_out: int = 50,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> dict:
    content = []
    for t in (tools or []):
        content.append(t)
    usage: dict = {
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
    }
    if cache_creation_tokens:
        usage["cache_creation_input_tokens"] = cache_creation_tokens
    if cache_read_tokens:
        usage["cache_read_input_tokens"] = cache_read_tokens
    return {
        "type": "assistant",
        "sessionId": session_id,
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "model": model,
            "id": msg_id,
            "content": content,
            "usage": usage,
        },
    }


def tool_read(file_path: str, tool_id: str = "t1") -> dict:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": "Read",
        "input": {"file_path": file_path},
    }


def tool_write(file_path: str, tool_id: str = "t2") -> dict:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": "Write",
        "input": {"file_path": file_path, "content": "hello"},
    }


def tool_edit(file_path: str, tool_id: str = "t3") -> dict:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": "Edit",
        "input": {"file_path": file_path, "old_string": "a", "new_string": "b"},
    }


def tool_bash(command: str, tool_id: str = "t4") -> dict:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": "Bash",
        "input": {"command": command, "description": "run it"},
    }


def claude_user_with_error(session_id: str, timestamp: str, cwd: str, tool_use_id: str) -> dict:
    return {
        "type": "user",
        "sessionId": session_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "is_error": True,
                    "content": "command not found",
                }
            ],
        },
    }


def codex_session_meta(session_id: str, cwd: str, timestamp: str, version: str = "0.1.0") -> dict:
    return {
        "timestamp": timestamp,
        "type": "session_meta",
        "payload": {
            "session_id": session_id,
            "id": session_id,
            "timestamp": timestamp,
            "cwd": cwd,
            "cli_version": version,
        },
    }


def codex_user_message(timestamp: str, text: str = "do stuff") -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "user_message", "message": text},
    }


def codex_function_call(name: str, args: dict, timestamp: str, call_id: str = "fc1") -> dict:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "id": call_id,
            "name": name,
            "arguments": json.dumps(args),
            "call_id": call_id,
        },
    }


def codex_token_count(timestamp: str, inp: int = 100, out: int = 50) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": inp,
                    "output_tokens": out,
                }
            },
        },
    }
