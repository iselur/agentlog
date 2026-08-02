"""Parse Claude Code and Codex JSONL session files.

Each public function returns a session dict (or None for files that are empty
or metadata-only).  Every field is treated as optional; malformed lines are
silently skipped and counted in ``skipped_lines``.

Session dict keys
-----------------
id            str   — session identifier (from filename or record)
source        str   — 'claude' or 'codex'
project       str   — absolute working directory (best guess)
project_name  str   — basename of project directory
start         datetime | None — first timestamp seen
end           datetime | None — last timestamp seen
duration_s    float | None    — (end - start).total_seconds(), or None
models        list[str]       — unique model names observed
user_turns    int             — number of user-turn records
files_read    list[str]       — file paths from Read tool calls
files_written list[str]       — file paths from Write/Edit/MultiEdit calls
commands      list[str]       — shell commands from Bash / exec_command calls
errors        int             — count of tool_result is_error records
tokens_in     int | None      — sum of input_tokens across assistant turns
tokens_out    int | None      — sum of output_tokens across assistant turns
ai_title      str | None      — auto-generated session title (Claude only)
version       str | None      — agent version string
skipped_lines int             — lines that could not be parsed
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _ts(raw: str) -> Optional[datetime]:
    """Parse ISO 8601 string to an aware datetime.  Returns None on failure."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _dedup(items: List[str]) -> List[str]:
    """Deduplicate a list while preserving first-seen order."""
    seen: set = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _empty_session(session_id: str, source: str) -> Dict:
    return {
        "id": session_id,
        "source": source,
        "project": "",
        "project_name": "",
        "start": None,
        "end": None,
        "duration_s": None,
        "models": [],
        "user_turns": 0,
        "files_read": [],
        "files_written": [],
        "commands": [],
        "errors": 0,
        "tokens_in": None,
        "tokens_out": None,
        "ai_title": None,
        "version": None,
        "skipped_lines": 0,
    }


def _read_lines(path: str) -> tuple[List[str], int]:
    """Read lines from a JSONL file.  Returns (lines, read_error_count)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readlines(), 0
    except OSError:
        return [], 1


# ---------------------------------------------------------------------------
# Claude Code parser
# ---------------------------------------------------------------------------

_CLAUDE_WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}


def _claude_tool_items(assistant_obj: Dict):
    """Yield (tool_id, tool_name, tool_input) for each tool_use in an assistant record."""
    msg = assistant_obj.get("message") or {}
    for item in msg.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "tool_use":
            continue
        yield (
            item.get("id", ""),
            item.get("name", ""),
            item.get("input") or {},
        )


def parse_claude_session(path: str) -> Optional[Dict]:
    """Parse one Claude Code JSONL file.  Returns a session dict or None."""
    session_id = os.path.splitext(os.path.basename(path))[0]
    lines, read_err = _read_lines(path)

    s = _empty_session(session_id, "claude")
    s["skipped_lines"] = read_err

    seen_tool_ids: set = set()
    seen_msg_ids: set = set()
    tok_in = 0
    tok_out = 0
    files_read: List[str] = []
    files_written: List[str] = []
    commands: List[str] = []

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            s["skipped_lines"] += 1
            continue
        if not isinstance(obj, dict):
            s["skipped_lines"] += 1
            continue

        record_type = obj.get("type", "")
        ts = _ts(obj.get("timestamp", ""))
        if ts:
            if s["start"] is None or ts < s["start"]:
                s["start"] = ts
            if s["end"] is None or ts > s["end"]:
                s["end"] = ts

        if record_type == "user":
            if not s["project"]:
                s["project"] = obj.get("cwd") or ""
            if not s["version"]:
                s["version"] = obj.get("version")
            # Prefer the sessionId embedded in the record over the filename
            if s["id"] == session_id and obj.get("sessionId"):
                s["id"] = obj["sessionId"]
            s["user_turns"] += 1
            # Count tool errors embedded in user content
            msg = obj.get("message") or {}
            for item in msg.get("content") or []:
                if (
                    isinstance(item, dict)
                    and item.get("type") == "tool_result"
                    and item.get("is_error")
                ):
                    s["errors"] += 1

        elif record_type == "assistant":
            msg = obj.get("message") or {}
            msg_id = msg.get("id", "")

            # Token counts — deduplicate by message id.
            # Include cache_creation_input_tokens and cache_read_input_tokens:
            # Claude Code's prompt caching means input_tokens alone is almost
            # zero on most turns; the cache fields carry the real load.
            if msg_id and msg_id not in seen_msg_ids:
                seen_msg_ids.add(msg_id)
                usage = msg.get("usage") or {}
                tok_in += (
                    (usage.get("input_tokens", 0) or 0)
                    + (usage.get("cache_creation_input_tokens", 0) or 0)
                    + (usage.get("cache_read_input_tokens", 0) or 0)
                )
                tok_out += usage.get("output_tokens", 0) or 0

            model = msg.get("model")
            if model and model not in s["models"]:
                s["models"].append(model)

            # Tool calls — deduplicate by tool_use id
            for tool_id, name, inp in _claude_tool_items(obj):
                if tool_id and tool_id in seen_tool_ids:
                    continue
                if tool_id:
                    seen_tool_ids.add(tool_id)
                fp = inp.get("file_path", "")
                if name == "Read" and fp:
                    files_read.append(fp)
                elif name in _CLAUDE_WRITE_TOOLS and fp:
                    files_written.append(fp)
                elif name == "Bash":
                    cmd = inp.get("command", "")
                    if cmd:
                        commands.append(cmd)

        elif record_type == "ai-title":
            s["ai_title"] = obj.get("aiTitle")

    # Require at least one user turn or timestamp to be a real session
    if s["user_turns"] == 0 and s["start"] is None:
        return None

    if not s["project"]:
        s["project"] = _decode_claude_path(path)
    s["project_name"] = os.path.basename(s["project"]) if s["project"] else session_id[:8]
    if s["start"] and s["end"]:
        s["duration_s"] = (s["end"] - s["start"]).total_seconds()
    s["files_read"] = _dedup(files_read)
    s["files_written"] = _dedup(files_written)
    s["commands"] = _dedup(commands)
    if tok_in > 0:
        s["tokens_in"] = tok_in
    if tok_out > 0:
        s["tokens_out"] = tok_out
    return s


def _decode_claude_path(jsonl_path: str) -> str:
    """Best-effort decode of a Claude Code project directory from its encoded path name.

    Claude Code encodes the project's absolute path as the parent directory name
    by replacing ``/`` with ``-``.  This is ambiguous when the path itself contains
    dashes; the result is a hint, not a guarantee.  The caller should prefer the
    ``cwd`` value found in ``user`` records over this fallback.
    """
    dir_name = os.path.basename(os.path.dirname(jsonl_path))
    # Leading '-' signals an absolute path
    if dir_name.startswith("-"):
        return dir_name[1:].replace("-", "/")
    return dir_name


# ---------------------------------------------------------------------------
# Codex parser
# ---------------------------------------------------------------------------

def parse_codex_session(path: str) -> Optional[Dict]:
    """Parse one Codex JSONL file.  Returns a session dict or None."""
    # Filename pattern: rollout-DATE-SESSION_ID.jsonl
    basename = os.path.splitext(os.path.basename(path))[0]
    # strip leading 'rollout-DATE-' prefix to get the UUID
    parts = basename.split("-")
    # UUID is the last 5 dash-separated parts
    session_id = "-".join(parts[-5:]) if len(parts) >= 5 else basename

    lines, read_err = _read_lines(path)
    s = _empty_session(session_id, "codex")
    s["skipped_lines"] = read_err

    tok_in = 0
    tok_out = 0
    commands: List[str] = []

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            s["skipped_lines"] += 1
            continue
        if not isinstance(obj, dict):
            s["skipped_lines"] += 1
            continue

        record_type = obj.get("type", "")
        ts = _ts(obj.get("timestamp", ""))
        if ts:
            if s["start"] is None or ts < s["start"]:
                s["start"] = ts
            if s["end"] is None or ts > s["end"]:
                s["end"] = ts

        payload = obj.get("payload") or {}
        if not isinstance(payload, dict):
            continue

        if record_type == "session_meta":
            s["id"] = payload.get("session_id") or payload.get("id") or session_id
            s["project"] = payload.get("cwd") or ""
            s["version"] = payload.get("cli_version")

        elif record_type == "turn_context":
            if not s["project"]:
                s["project"] = payload.get("cwd") or ""

        elif record_type == "event_msg":
            pt = payload.get("type", "")
            if pt == "user_message":
                s["user_turns"] += 1
            elif pt == "token_count":
                # last_token_usage is the session's *cumulative* total at this
                # point in the conversation — each snapshot is higher than the
                # previous.  Take the maximum seen so that the final (highest)
                # value is used, rather than summing all snapshots.
                info = payload.get("info") or {}
                last = info.get("last_token_usage") or {}
                ti = last.get("input_tokens", 0) or 0
                to = last.get("output_tokens", 0) or 0
                if ti > tok_in:
                    tok_in = ti
                if to > tok_out:
                    tok_out = to

        elif record_type == "response_item":
            pt = payload.get("type", "")
            if pt == "function_call" and payload.get("name") == "exec_command":
                args_str = payload.get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                except (json.JSONDecodeError, ValueError):
                    args = {}
                cmd = args.get("cmd", "")
                if cmd:
                    commands.append(cmd)
            elif pt == "function_call_output":
                output = payload.get("output") or {}
                if isinstance(output, dict):
                    meta = output.get("metadata") or {}
                    if isinstance(meta, dict) and meta.get("exit_code", 0) not in (0, None):
                        s["errors"] += 1

    if s["user_turns"] == 0 and s["start"] is None:
        return None

    s["project_name"] = os.path.basename(s["project"]) if s["project"] else session_id[:8]
    if s["start"] and s["end"]:
        s["duration_s"] = (s["end"] - s["start"]).total_seconds()
    s["commands"] = _dedup(commands)
    if tok_in > 0:
        s["tokens_in"] = tok_in
    if tok_out > 0:
        s["tokens_out"] = tok_out
    return s


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def find_sessions(home_dir: Optional[str] = None) -> tuple[List[Dict], List[str]]:
    """Find all sessions from Claude Code and Codex.

    Returns ``(sessions, sources)`` where ``sources`` is a list of names of
    agents whose logs were found.  ``sessions`` is sorted newest-first.
    If neither log directory exists the list is empty.
    """
    if home_dir is None:
        home_dir = os.path.expanduser("~")

    claude_dir = os.path.join(home_dir, ".claude", "projects")
    codex_dir = os.path.join(home_dir, ".codex", "sessions")

    sessions: List[Dict] = []
    sources: List[str] = []

    # Track real (resolved) file paths to skip symlink duplicates.
    seen_real_paths: set = set()

    def _add(sess: Optional[Dict], path: str) -> None:
        if sess is None:
            return
        real = os.path.realpath(path)
        if real in seen_real_paths:
            return
        seen_real_paths.add(real)
        sessions.append(sess)

    if os.path.isdir(claude_dir):
        sources.append("Claude Code")
        for path in glob.glob(os.path.join(claude_dir, "**", "*.jsonl"), recursive=True):
            _add(parse_claude_session(path), path)

    if os.path.isdir(codex_dir):
        sources.append("Codex")
        for path in glob.glob(os.path.join(codex_dir, "**", "*.jsonl"), recursive=True):
            _add(parse_codex_session(path), path)

    # Deduplicate by session ID: Codex parallel-worker files all carry the
    # same session_id in their session_meta record.  Keep the one session that
    # has the most user turns (richest data); fall back to longest duration.
    by_id: Dict[str, Dict] = {}
    for s in sessions:
        sid = s["id"]
        existing = by_id.get(sid)
        if existing is None:
            by_id[sid] = s
        else:
            # Prefer the entry with more turns, then longer duration
            s_turns = s["user_turns"]
            e_turns = existing["user_turns"]
            s_dur = s["duration_s"] or 0.0
            e_dur = existing["duration_s"] or 0.0
            if s_turns > e_turns or (s_turns == e_turns and s_dur > e_dur):
                by_id[sid] = s
    sessions = list(by_id.values())

    # Sort newest-first; sessions without a start time go to the end
    _epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    sessions.sort(key=lambda s: s["start"] or _epoch, reverse=True)
    return sessions, sources
