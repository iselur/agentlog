"""Plain-text and JSON formatters for session digests."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "?"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def _fmt_time(dt: Optional[datetime]) -> str:
    if dt is None:
        return "?"
    local = dt.astimezone()
    return local.strftime("%H:%M")


def _fmt_datetime(dt: Optional[datetime]) -> str:
    if dt is None:
        return "?"
    local = dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M")


def _truncate(items: List[str], limit: int = 6, width: int = 60) -> List[str]:
    """Return up to ``limit`` items, each truncated to ``width`` chars."""
    out = []
    for item in items[:limit]:
        if len(item) > width:
            item = "..." + item[-(width - 3):]
        out.append(item)
    if len(items) > limit:
        out.append(f"  ... and {len(items) - limit} more")
    return out


def _shorten_cmd(cmd: str, width: int = 72) -> str:
    """Shorten a shell command for display."""
    cmd = cmd.replace("\n", " ").strip()
    if len(cmd) > width:
        return cmd[:width] + "..."
    return cmd


# ---------------------------------------------------------------------------
# Summary line
# ---------------------------------------------------------------------------

def summary_line(sessions: List[Dict]) -> str:
    """Return a one-line digest summary, e.g. '4 sessions · 3h 12m · 3 projects'."""
    if not sessions:
        return "0 sessions"

    total_s = sum(s["duration_s"] or 0 for s in sessions)
    projects = len({s["project"] for s in sessions if s["project"]})
    files_edited = sum(len(s["files_written"]) for s in sessions)
    cmds = sum(len(s["commands"]) for s in sessions)
    errors = sum(s["errors"] for s in sessions)

    parts = [
        f"{len(sessions)} session{'s' if len(sessions) != 1 else ''}",
        _fmt_duration(total_s),
    ]
    if projects:
        parts.append(f"{projects} project{'s' if projects != 1 else ''}")
    if files_edited:
        parts.append(f"{files_edited} file{'s' if files_edited != 1 else ''} edited")
    if cmds:
        parts.append(f"{cmds} command{'s' if cmds != 1 else ''}")
    if errors:
        parts.append(f"{errors} error{'s' if errors != 1 else ''}")

    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Terminal text formatter
# ---------------------------------------------------------------------------

def render_text(sessions: List[Dict], verbose: bool = False) -> str:
    """Render a list of sessions as plain-text suitable for the terminal."""
    if not sessions:
        return ""

    lines: List[str] = []
    lines.append(summary_line(sessions))
    lines.append("")

    for s in sessions:
        _render_session_text(s, lines, verbose=verbose)
        lines.append("")

    return "\n".join(lines).rstrip()


def _render_session_text(s: Dict, lines: List[str], verbose: bool = False) -> None:
    short_id = s["id"][:8] if s["id"] else "?"
    project = s["project_name"] or s["project"] or "?"
    source_tag = f"[{s['source']}]" if s.get("source") else ""

    # Header line
    time_range = ""
    if s["start"]:
        time_range = _fmt_datetime(s["start"])
        if s["end"] and s["end"] != s["start"]:
            time_range += " – " + _fmt_time(s["end"])
    duration = _fmt_duration(s["duration_s"])

    title = s.get("ai_title")
    header = f"  {short_id}  {project}  {source_tag}"
    if title:
        header += f'  "{title}"'
    lines.append(header)
    lines.append(f"    {time_range}  ({duration})  {s['user_turns']} turns")

    if s["models"]:
        lines.append(f"    model: {', '.join(s['models'])}")

    files_all = _dedup_merge(s["files_read"], s["files_written"])
    if files_all:
        label = "files"
        lines.append(f"    {label}:")
        for f in _truncate(files_all):
            tag = " (r)" if f in s["files_read"] and f not in s["files_written"] else ""
            lines.append(f"      {f}{tag}")

    if s["commands"]:
        lines.append(f"    commands ({len(s['commands'])}):")
        for cmd in _truncate(s["commands"], limit=5, width=80):
            lines.append(f"      $ {_shorten_cmd(cmd)}")

    tokens = _fmt_tokens(s)
    if tokens:
        lines.append(f"    {tokens}")

    if s["errors"]:
        lines.append(f"    errors: {s['errors']}")

    if verbose and s["skipped_lines"]:
        lines.append(f"    skipped lines: {s['skipped_lines']}")


def _dedup_merge(a: List[str], b: List[str]) -> List[str]:
    seen: set = set()
    out = []
    for x in a + b:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _fmt_tokens(s: Dict) -> str:
    parts = []
    if s.get("tokens_in") is not None:
        parts.append(f"in: {s['tokens_in']:,}")
    if s.get("tokens_out") is not None:
        parts.append(f"out: {s['tokens_out']:,}")
    if parts:
        return "tokens — " + "  ".join(parts)
    return ""


# ---------------------------------------------------------------------------
# List view (agentlog list)
# ---------------------------------------------------------------------------

def render_list(sessions: List[Dict]) -> str:
    """Render a compact table of all sessions."""
    if not sessions:
        return "no sessions found"

    rows = []
    for s in sessions:
        sid = s["id"][:8] if s["id"] else "?"
        project = (s["project_name"] or "?")[:24]
        when = _fmt_datetime(s["start"]) if s["start"] else "?"
        dur = _fmt_duration(s["duration_s"])
        src = s.get("source", "?")[:6]
        rows.append((sid, project, when, dur, src))

    # Column widths
    w = [8, 24, 16, 8, 6]
    header = "  ".join(col.ljust(w[i]) for i, col in enumerate(("ID", "PROJECT", "WHEN", "DUR", "SRC")))
    sep = "  ".join("-" * width for width in w)
    lines = [header, sep]
    for row in rows:
        lines.append("  ".join(cell.ljust(w[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Single-session detail (agentlog show SESSION_ID)
# ---------------------------------------------------------------------------

def render_show(s: Dict) -> str:
    """Render a single session in full detail."""
    lines: List[str] = []
    lines.append(f"session  {s['id']}")
    lines.append(f"source   {s.get('source', '?')}")
    lines.append(f"project  {s['project'] or '?'}")
    lines.append(f"start    {_fmt_datetime(s['start'])}")
    lines.append(f"end      {_fmt_datetime(s['end'])}")
    lines.append(f"duration {_fmt_duration(s['duration_s'])}")
    if s["models"]:
        lines.append(f"models   {', '.join(s['models'])}")
    if s.get("version"):
        lines.append(f"version  {s['version']}")
    lines.append(f"turns    {s['user_turns']}")
    lines.append(f"errors   {s['errors']}")
    tokens = _fmt_tokens(s)
    if tokens:
        lines.append(f"tokens   {tokens.replace('tokens — ', '')}")

    if s["files_read"]:
        lines.append("")
        lines.append(f"files read ({len(s['files_read'])}):")
        for f in s["files_read"]:
            lines.append(f"  {f}")

    if s["files_written"]:
        lines.append("")
        lines.append(f"files written ({len(s['files_written'])}):")
        for f in s["files_written"]:
            lines.append(f"  {f}")

    if s["commands"]:
        lines.append("")
        lines.append(f"commands ({len(s['commands'])}):")
        for cmd in s["commands"]:
            lines.append(f"  $ {cmd}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def render_markdown(sessions: List[Dict]) -> str:
    """Render sessions as a Markdown document."""
    lines: List[str] = []
    lines.append("# agentlog digest")
    lines.append("")
    lines.append(summary_line(sessions))
    lines.append("")

    for s in sessions:
        short_id = s["id"][:8] if s["id"] else "?"
        project = s["project_name"] or s["project"] or "?"
        lines.append(f"## {project}  `{short_id}`")
        lines.append("")

        when = _fmt_datetime(s["start"]) if s["start"] else "?"
        dur = _fmt_duration(s["duration_s"])
        lines.append(f"- **when**: {when}  ({dur})")
        lines.append(f"- **source**: {s.get('source', '?')}")
        if s["models"]:
            lines.append(f"- **model**: {', '.join(s['models'])}")
        lines.append(f"- **turns**: {s['user_turns']}  **errors**: {s['errors']}")
        tokens = _fmt_tokens(s)
        if tokens:
            lines.append(f"- **tokens**: {tokens.replace('tokens — ', '')}")
        lines.append("")

        files_all = _dedup_merge(s["files_read"], s["files_written"])
        if files_all:
            lines.append(f"**Files** ({len(files_all)}):")
            lines.append("```")
            for f in files_all[:20]:
                tag = " (read only)" if f in s["files_read"] and f not in s["files_written"] else ""
                lines.append(f"{f}{tag}")
            if len(files_all) > 20:
                lines.append(f"... and {len(files_all) - 20} more")
            lines.append("```")
            lines.append("")

        if s["commands"]:
            lines.append(f"**Commands** ({len(s['commands'])}):")
            lines.append("```sh")
            for cmd in s["commands"][:20]:
                lines.append(f"$ {_shorten_cmd(cmd)}")
            if len(s["commands"]) > 20:
                lines.append(f"... and {len(s['commands']) - 20} more")
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def _session_for_json(s: Dict) -> Dict:
    out = dict(s)
    if s["start"]:
        out["start"] = s["start"].isoformat()
    if s["end"]:
        out["end"] = s["end"].isoformat()
    return out


def render_json(sessions: List[Dict]) -> str:
    return json.dumps([_session_for_json(s) for s in sessions], indent=2, default=str)
