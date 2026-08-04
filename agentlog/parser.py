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
files_written list[str]       — file paths from Write/Edit/MultiEdit calls,
                                and from Codex apply_patch envelopes
commands      list[str]       — shell commands from Bash / exec_command /
                                apply_patch calls
errors        int             — count of tool_result is_error records, plus
                                Codex commands that exited non-zero
failed_cmds   list[str]       — the commands those errors came from
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
import stat
from datetime import datetime, timezone
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _ts(raw) -> Optional[datetime]:
    """Parse an ISO 8601 string to an *aware* datetime.  None on failure.

    Always aware, never naive.  A log that dropped its ``Z`` would otherwise
    hand back a naive datetime, and the first comparison against an aware one
    raises TypeError halfway through the digest.  Assuming UTC is the honest
    reading: it is the offset the format is written in.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _text(value) -> str:
    """A field that ought to be a string, as a string.  Anything else is empty.

    Session logs are written by another program having a bad day; a ``cwd``
    that arrives as a number should cost the digest one blank field, not the
    whole run.
    """
    return value if isinstance(value, str) else ""


def _obj(value) -> Dict:
    """A field that ought to be an object, as an object."""
    return value if isinstance(value, dict) else {}


def _items(value) -> List:
    """A field that ought to be a list, as a list."""
    return value if isinstance(value, list) else []


def _count(value) -> int:
    """A token count, however the log spelled it.  Anything else is zero."""
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (ValueError, OverflowError):
            return 0
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return 0
    return 0


def _failed(value) -> bool:
    """Did a command exit non-zero?  Missing or unreadable counts as success.

    Guessing "failed" from a field nobody can parse would invent errors that
    never happened, which is worse than missing a real one.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return int(value) != 0
    if isinstance(value, str):
        try:
            return int(value.strip()) != 0
        except ValueError:
            return False
    return False


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
        "events": [],
        "start": None,
        "end": None,
        "duration_s": None,
        "models": [],
        "user_turns": 0,
        "files_read": [],
        "files_written": [],
        "commands": [],
        "errors": 0,
        "failed_cmds": [],
        "write_counts": {},
        "tokens_in": None,
        "tokens_out": None,
        "ai_title": None,
        "version": None,
        "skipped_lines": 0,
    }


def _read_lines(path: str) -> tuple[List[str], int]:
    """Read lines from a JSONL file.  Returns (lines, read_error_count).

    Only regular files are opened.  A FIFO or a socket that happens to be named
    ``*.jsonl`` blocks *at open* until somebody writes to it, and a digest tool
    that hangs forever on a stray pipe is worse than one that crashes — there is
    nothing on screen to explain the wait.
    """
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            return [], 1
    except OSError:
        return [], 1
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
    msg = _obj(assistant_obj.get("message"))
    for item in _items(msg.get("content")):
        if not isinstance(item, dict):
            continue
        if item.get("type") != "tool_use":
            continue
        yield (
            _text(item.get("id")),
            _text(item.get("name")),
            _obj(item.get("input")),
        )


def parse_claude_session(path: str) -> Optional[Dict]:
    """Parse one Claude Code JSONL file.  Returns a session dict or None."""
    session_id = os.path.splitext(os.path.basename(path))[0]
    lines, read_err = _read_lines(path)

    s = _empty_session(session_id, "claude")
    s["skipped_lines"] = read_err

    seen_tool_ids: set = set()
    seen_msg_ids: set = set()
    # tool_use id -> a short label for what that call did, so a failure can be
    # reported as the command that failed rather than as an anonymous count.
    tool_labels: Dict[str, str] = {}
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
                s["project"] = _text(obj.get("cwd"))
            if not s["version"]:
                s["version"] = _text(obj.get("version")) or None
            # Prefer the sessionId embedded in the record over the filename
            if s["id"] == session_id and _text(obj.get("sessionId")):
                s["id"] = _text(obj["sessionId"])
            s["user_turns"] += 1
            # Count tool errors embedded in user content
            msg = _obj(obj.get("message"))
            for item in _items(msg.get("content")):
                if (
                    isinstance(item, dict)
                    and item.get("type") == "tool_result"
                    and item.get("is_error")
                ):
                    s["errors"] += 1
                    label = tool_labels.get(_text(item.get("tool_use_id")), "")
                    s["failed_cmds"].append(label)
                    s["events"].append((ts, "error", label))
            s["events"].append((ts, "turn", ""))

        elif record_type == "assistant":
            msg = _obj(obj.get("message"))
            msg_id = _text(msg.get("id"))

            # Token counts — deduplicate by message id.
            # Include cache_creation_input_tokens and cache_read_input_tokens:
            # Claude Code's prompt caching means input_tokens alone is almost
            # zero on most turns; the cache fields carry the real load.
            if msg_id and msg_id not in seen_msg_ids:
                seen_msg_ids.add(msg_id)
                usage = _obj(msg.get("usage"))
                tok_in += (
                    _count(usage.get("input_tokens"))
                    + _count(usage.get("cache_creation_input_tokens"))
                    + _count(usage.get("cache_read_input_tokens"))
                )
                tok_out += _count(usage.get("output_tokens"))

            model = _text(msg.get("model"))
            if model and model not in s["models"]:
                s["models"].append(model)

            # Tool calls — deduplicate by tool_use id
            for tool_id, name, inp in _claude_tool_items(obj):
                if tool_id and tool_id in seen_tool_ids:
                    continue
                if tool_id:
                    seen_tool_ids.add(tool_id)
                fp = _text(inp.get("file_path"))
                if name == "Read" and fp:
                    files_read.append(fp)
                    s["events"].append((ts, "read", fp))
                    tool_labels[tool_id] = f"read {os.path.basename(fp)}"
                elif name in _CLAUDE_WRITE_TOOLS and fp:
                    files_written.append(fp)
                    s["write_counts"][fp] = s["write_counts"].get(fp, 0) + 1
                    s["events"].append((ts, "write", fp))
                    tool_labels[tool_id] = f"edit {os.path.basename(fp)}"
                elif name == "Bash":
                    cmd = _text(inp.get("command"))
                    if cmd:
                        commands.append(cmd)
                        s["events"].append((ts, "cmd", cmd))
                        tool_labels[tool_id] = cmd
                elif name:
                    tool_labels[tool_id] = name

        elif record_type == "ai-title":
            s["ai_title"] = _text(obj.get("aiTitle")) or None

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

# Calls that represent work done on the machine.  Everything else Codex emits
# (update_plan, spawn_agent, wait, send_message) is coordination, not activity.
_CODEX_WORK_CALLS = {"exec_command", "apply_patch"}

_PATCH_MARKERS = ("*** Update File:", "*** Add File:", "*** Delete File:")


def _patched_files(text: str) -> List[str]:
    """File paths named in an apply_patch envelope.

    Codex has no structured file-write field: it edits by piping an envelope
    like ``*** Update File: src/app.py`` through the shell, so the only record
    of which file changed is the command text itself.  Scanning for the marker
    lines recovers it.  Paths are returned in the order they appear.
    """
    if not text or "*** " not in text:
        return []
    out: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        for marker in _PATCH_MARKERS:
            if line.startswith(marker):
                path = line[len(marker):].strip()
                # Envelopes embedded in quoted shell strings pick up a trailing
                # quote or backslash from the surrounding literal.
                path = path.strip("'\"").rstrip("\\").strip()
                if path:
                    out.append(path)
                break
    return out


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
    files_written: List[str] = []
    # call_id -> command, so a non-zero exit names the command that failed
    call_cmds: Dict[str, str] = {}

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
            s["id"] = (_text(payload.get("session_id"))
                       or _text(payload.get("id")) or session_id)
            s["project"] = _text(payload.get("cwd"))
            s["version"] = _text(payload.get("cli_version")) or None

        elif record_type == "turn_context":
            if not s["project"]:
                s["project"] = _text(payload.get("cwd"))

        elif record_type == "event_msg":
            pt = _text(payload.get("type"))
            if pt == "user_message":
                s["user_turns"] += 1
                s["events"].append((ts, "turn", ""))
            elif pt == "token_count":
                # last_token_usage is the session's *cumulative* total at this
                # point in the conversation — each snapshot is higher than the
                # previous.  Take the maximum seen so that the final (highest)
                # value is used, rather than summing all snapshots.
                info = _obj(payload.get("info"))
                last = _obj(info.get("last_token_usage"))
                ti = _count(last.get("input_tokens"))
                to = _count(last.get("output_tokens"))
                if ti > tok_in:
                    tok_in = ti
                if to > tok_out:
                    tok_out = to

        elif record_type == "response_item":
            pt = _text(payload.get("type"))
            if pt == "function_call" and payload.get("name") in _CODEX_WORK_CALLS:
                args_str = payload.get("arguments")
                if not isinstance(args_str, str):
                    args_str = "{}"
                try:
                    args = json.loads(args_str)
                except (json.JSONDecodeError, ValueError):
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                # exec_command carries `cmd`; apply_patch carries either a
                # `command` (a shell one-liner) or a `patch` envelope.
                cmd = args.get("cmd") or args.get("command") or ""
                patch = args.get("patch") or ""
                if not isinstance(cmd, str):
                    cmd = ""
                if not isinstance(patch, str):
                    patch = ""
                if cmd:
                    commands.append(cmd)
                    s["events"].append((ts, "cmd", cmd))
                    call_id = _text(payload.get("call_id"))
                    if call_id:
                        call_cmds[call_id] = cmd
                # Codex edits files by piping an apply_patch envelope through
                # the shell, so the written paths are inside the command text
                # rather than in a structured field.
                # Envelopes name files relative to the working directory as
                # often as absolutely; without this the same file shows up
                # twice under two spellings.
                root = _text(args.get("workdir")) or s["project"] or ""
                for path in _patched_files(patch or cmd):
                    if not os.path.isabs(path) and isinstance(root, str) and root:
                        path = os.path.normpath(os.path.join(root, path))
                    files_written.append(path)
                    s["write_counts"][path] = s["write_counts"].get(path, 0) + 1
                    s["events"].append((ts, "write", path))
            elif pt == "function_call_output":
                output = _obj(payload.get("output"))
                meta = _obj(output.get("metadata"))
                if _failed(meta.get("exit_code")):
                    s["errors"] += 1
                    label = call_cmds.get(_text(payload.get("call_id")), "")
                    s["failed_cmds"].append(label)
                    s["events"].append((ts, "error", label))

    if s["user_turns"] == 0 and s["start"] is None:
        return None

    s["project_name"] = os.path.basename(s["project"]) if s["project"] else session_id[:8]
    if s["start"] and s["end"]:
        s["duration_s"] = (s["end"] - s["start"]).total_seconds()
    s["commands"] = _dedup(commands)
    s["files_written"] = _dedup(files_written)
    if tok_in > 0:
        s["tokens_in"] = tok_in
    if tok_out > 0:
        s["tokens_out"] = tok_out
    return s


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

UNREADABLE = "could not be read"
NO_RECORDS = "had no readable records"


def _why_unusable(path: str, sess: Optional[Dict]) -> str:
    """Why this file will not appear in any report, or '' if it will.

    A session with no start time cannot fall inside any day window, so it is
    dropped by the time filter before anything is rendered — silently, and
    including the count of what it skipped.  This asks the file itself why,
    so the report can say so instead.

    Only ever asked about files that produced nothing, so the extra stat calls
    fall on the handful that are already broken.

    A zero-byte file is deliberately not one of these: a session that has just
    started is empty on disk, nothing has been lost, and warning about it would
    make the note fire on an ordinary morning.
    """
    if sess is not None and sess["start"] is not None:
        return ""
    try:
        st = os.stat(path)
    except OSError:
        return UNREADABLE
    if not stat.S_ISREG(st.st_mode):
        return UNREADABLE
    if st.st_size == 0:
        return ""
    try:
        with open(path, "rb") as fh:
            fh.read(1)
    except OSError:
        return UNREADABLE
    # It opened and it has bytes in it, so the bytes are the problem: truncated
    # mid-write, a different format, or a file that only happens to end .jsonl.
    return NO_RECORDS


def find_sessions(
    home_dir: Optional[str] = None,
) -> tuple[List[Dict], List[str], List[tuple]]:
    """Find all sessions from Claude Code and Codex.

    Returns ``(sessions, sources, unusable)``.  ``sources`` is a list of names
    of agents whose logs were found.  ``sessions`` is sorted newest-first.
    ``unusable`` is a list of ``(path, reason)`` for log files that exist and
    contributed nothing — the caller is expected to say so, because a report
    computed from fewer files than are on disk looks exactly like a complete
    one.  If neither log directory exists every list is empty.
    """
    if home_dir is None:
        home_dir = os.path.expanduser("~")

    claude_dir = os.path.join(home_dir, ".claude", "projects")
    codex_dir = os.path.join(home_dir, ".codex", "sessions")

    sessions: List[Dict] = []
    sources: List[str] = []
    unusable: List[tuple] = []

    # Track real (resolved) file paths to skip symlink duplicates.
    seen_real_paths: set = set()

    def _add(sess: Optional[Dict], path: str) -> None:
        # The duplicate check now happens before the None check, so a symlink
        # to an unreadable file is reported once rather than once per link.
        real = os.path.realpath(path)
        if real in seen_real_paths:
            return
        seen_real_paths.add(real)
        reason = _why_unusable(path, sess)
        if reason:
            unusable.append((path, reason))
        if sess is None:
            return
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
    unusable.sort()
    return sessions, sources, unusable
