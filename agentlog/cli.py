"""agentlog command-line interface.

Commands
--------
  agentlog                       # same as: agentlog today
  agentlog today | yesterday | week
  agentlog since DATE            # ISO date, or offset like 3d / 12h
  agentlog show SESSION_ID       # one session in full detail
  agentlog list                  # recent sessions, compact table (default 50)
  agentlog list --all            # all sessions

View flags (time commands)
  --sessions                     # per-session view instead of the digest
  --project NAME                 # only projects matching NAME

Output flags (may be combined with any time command)
  --html FILE                    # write self-contained HTML digest
  --md [FILE]                    # Markdown (to FILE or stdout)
  --json                         # machine-readable JSON

Other flags
  --all                          # list: show all sessions (no row limit)
  --limit N                      # list: show at most N sessions (default 50)
  --verbose                      # show skipped-line counts and debug hints
  --home DIR                     # override home directory (useful for tests)

Exit codes
  0   normal
  2   usage or argument error

The tool never writes to or uploads the session logs.
"""

from __future__ import annotations

import argparse
import codecs
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import __version__
from .parser import find_sessions
from .render import (
    render_digest,
    render_json,
    render_list,
    render_markdown,
    render_show,
    render_text,
)
from .html import render_html


# ---------------------------------------------------------------------------
# Date / time helpers
# ---------------------------------------------------------------------------

_LOCAL = datetime.now().astimezone().tzinfo


def _today_local() -> date:
    return datetime.now(_LOCAL).date()


def _parse_since(value: str) -> Optional[datetime]:
    """Parse a --since / 'since DATE' argument.

    Accepts:
      ISO date:  2026-07-15
      Offset:    3d, 12h, 2w
    Returns an aware datetime or None on failure.
    """
    value = value.strip().lower()

    # Offset form
    if value and value[-1] in "dhw":
        try:
            n = int(value[:-1])
        except ValueError:
            return None
        if n <= 0:
            # 'since 0d' is an empty window and 'since -3d' is the future;
            # neither is what anybody meant to type.
            return None
        unit = value[-1]
        try:
            delta = {"d": timedelta(days=n), "h": timedelta(hours=n),
                     "w": timedelta(weeks=n)}[unit]
            return datetime.now(timezone.utc) - delta
        except (OverflowError, OSError):
            # timedelta gives out long before int does.
            return None

    # ISO date
    try:
        d = date.fromisoformat(value)
        return datetime(d.year, d.month, d.day, tzinfo=_LOCAL)
    except ValueError:
        return None


def _since_for_period(period: str) -> Optional[datetime]:
    """Return the start-of-window datetime for a named period."""
    today = _today_local()
    if period == "today":
        d = today
    elif period == "yesterday":
        d = today - timedelta(days=1)
    elif period == "week":
        d = today - timedelta(days=6)
    else:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=_LOCAL)


def _until_for_period(period: str) -> Optional[datetime]:
    """Return the exclusive end-of-window datetime for 'yesterday', None otherwise."""
    if period == "yesterday":
        today = _today_local()
        return datetime(today.year, today.month, today.day, tzinfo=_LOCAL)
    return None


# ---------------------------------------------------------------------------
# Session filtering
# ---------------------------------------------------------------------------

def _clip_counts(s: Dict, start: datetime, end: datetime) -> None:
    """Recount files, commands, turns and errors from events inside the window.

    A session that ran for two weeks would otherwise contribute all of its
    edits to every single day's digest.  Sessions parsed before events were
    recorded (or with untimestamped records) keep their lifetime totals.
    """
    events = s.get("events") or []
    if not events:
        return

    seen: Dict[str, set] = {"read": set(), "write": set(), "cmd": set()}
    reads: List[str] = []
    writes: List[str] = []
    cmds: List[str] = []
    write_counts: Dict[str, int] = {}
    failed: List[str] = []
    turns = 0
    errors = 0
    for ts, kind, value in events:
        if ts is None or ts < start or ts > end:
            continue
        if kind == "turn":
            turns += 1
        elif kind == "error":
            errors += 1
            failed.append(value)
        else:
            if kind == "write":
                write_counts[value] = write_counts.get(value, 0) + 1
            if kind in seen and value not in seen[kind]:
                seen[kind].add(value)
                {"read": reads, "write": writes, "cmd": cmds}[kind].append(value)

    s["files_read"] = reads
    s["files_written"] = writes
    s["commands"] = cmds
    s["write_counts"] = write_counts
    s["failed_cmds"] = failed
    s["user_turns"] = turns
    s["errors"] = errors


def _filter_sessions(
    sessions: List[Dict],
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> List[Dict]:
    """Keep sessions that *overlap* the window, not just those that start in it.

    A session that began yesterday and is still running belongs in ``today``;
    filtering on the start timestamp alone made long-running sessions vanish.
    When a session extends past either edge of the window, a copy is returned
    carrying ``window_s`` — the seconds it spent inside the window — so totals
    reflect the period asked for rather than the session's whole lifetime.
    """
    out = []
    for s in sessions:
        start = s["start"]
        if start is None:
            continue
        end = s["end"] or start
        if since is not None and end < since:
            continue
        if until is not None and start >= until:
            continue

        edge = until or datetime.now(timezone.utc)
        clipped_start = max(start, since) if since is not None else start
        clipped_end = max(min(end, edge), clipped_start)
        s = dict(s)
        s["win_start"] = clipped_start
        s["win_end"] = clipped_end
        if clipped_start > start or clipped_end < end:
            s["window_s"] = (clipped_end - clipped_start).total_seconds()
            _clip_counts(s, clipped_start, clipped_end)
        out.append(s)
    return out


def _filter_project(sessions: List[Dict], needle: str) -> List[Dict]:
    """Keep sessions whose project name or path contains ``needle``."""
    low = needle.lower()
    return [
        s
        for s in sessions
        if low in (s.get("project_name") or "").lower()
        or low in (s.get("project") or "").lower()
    ]


# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------

# Commands that take a second word.  Everything else takes none, and a stray
# word after them is a typo the person deserves to be told about.
_COMMANDS_WITH_ARG = ("since", "show")


def _log_dirs(home_dir: Optional[str]) -> List[str]:
    home = home_dir or os.environ.get("AGENTLOG_HOME") or os.path.expanduser("~")
    return [
        os.path.realpath(os.path.join(home, ".claude", "projects")),
        os.path.realpath(os.path.join(home, ".codex", "sessions")),
    ]


def _refuses_to_write(target: str, home_dir: Optional[str]) -> Optional[str]:
    """Why this path must not be written to, or None if it is fine.

    agentlog's one promise is that it never writes to the session logs.  A
    digest written over ``~/.claude/projects/.../session.jsonl`` destroys the
    only copy of a day's work, and a single mistyped path is all it takes.
    """
    if not target or target == "-":
        return None
    real = os.path.realpath(target)
    for root in _log_dirs(home_dir):
        if real == root or real.startswith(root + os.sep):
            return ("refusing to write inside the session log directory\n"
                    "  {}\n"
                    "  agentlog never writes to the logs it reads. "
                    "Choose a path outside them.".format(root))
    if real.endswith(".jsonl"):
        return ("refusing to write over {}\n"
                "  that is a session log, not an output file.".format(target))
    return None


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentlog",
        description="What did your coding agent actually do today?",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  agentlog\n"
            "  agentlog yesterday\n"
            "  agentlog since 3d\n"
            "  agentlog show 0224e6b8\n"
            "  agentlog list\n"
            "  agentlog today --html digest.html\n"
            "  agentlog week --json\n"
        ),
    )
    p.add_argument("--version", action="version", version=f"agentlog {__version__}")
    p.add_argument(
        "command",
        nargs="?",
        default="today",
        metavar="COMMAND",
        help="today | yesterday | week | since DATE | show ID | list (default: today)",
    )
    p.add_argument(
        "arg",
        nargs="?",
        default=None,
        metavar="ARG",
        help="argument for 'since' (e.g. 3d, 12h, 2026-07-15) or 'show' (session ID prefix)",
    )
    p.add_argument("--html", metavar="FILE", help="write self-contained HTML to FILE")
    p.add_argument(
        "--md",
        metavar="FILE",
        nargs="?",
        const="-",
        help="write Markdown to FILE (or stdout if FILE omitted)",
    )
    p.add_argument("--json", action="store_true", help="print JSON to stdout")
    p.add_argument(
        "--sessions",
        action="store_true",
        help="list every session instead of the per-project digest",
    )
    p.add_argument(
        "--project",
        metavar="NAME",
        help="only include projects whose name or path contains NAME",
    )
    p.add_argument("--all", action="store_true", help="list: show all sessions (no row limit)")
    p.add_argument("--limit", type=int, default=50, metavar="N", help="list: max rows to show (default 50)")
    p.add_argument("--verbose", action="store_true", help="show parsing diagnostics")
    p.add_argument(
        "--home",
        metavar="DIR",
        help="override home directory (default: ~); sets where logs are sought",
    )
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _as_typed(text):
    """An argument in the form it was typed, not the form the locale allowed.

    Python decodes ``sys.argv`` with the filesystem encoding, and on a machine
    with no locale that encoding is ASCII — so ``--project 設定`` arrives as a
    run of surrogates and matches nothing.  A filter that silently matches
    nothing is the worst way for this to fail: it reads as a quiet day rather
    than as an error.  ``os.fsencode`` gives the bytes back untouched, and the
    shell that sent them was speaking UTF-8.
    """
    if text is None or text.isascii():
        return text                     # the overwhelmingly common case
    try:
        return os.fsencode(text).decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def _write_utf8_if_the_locale_said_nothing() -> None:
    """Write UTF-8 when the machine claims it can only take ASCII.

    A container with no locale set — a Dockerfile without ``ENV LANG``, cron,
    most of CI — leaves Python believing stdout is ASCII, and then a single em
    dash of our own raises ``UnicodeEncodeError`` halfway through the digest:
    a traceback and half a report, over a character no one chose.

    An ASCII claim is not a claim about the terminal, though.  It is the
    absence of one, and the terminal on the other end is virtually always
    UTF-8.  So we write UTF-8 and keep ``surrogateescape``, which hands back
    unchanged the bytes of any path this machine could not decode — that is
    what makes a name it cannot spell come out spelled right anyway.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if codecs.lookup(stream.encoding or "").name == "ascii":
                stream.reconfigure(encoding="utf-8", errors="surrogateescape")
        except (AttributeError, LookupError, OSError, ValueError):
            pass                        # not a real stream, or already written to


def main(argv=None) -> int:
    _write_utf8_if_the_locale_said_nothing()
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.project = _as_typed(args.project)

    home_dir = args.home or os.environ.get("AGENTLOG_HOME") or None

    # A word after a command that takes none is a typo, not a no-op.
    if args.arg is not None and args.command not in _COMMANDS_WITH_ARG:
        print(
            "agentlog: '{}' accepts no extra argument (got '{}')\n"
            "  try: agentlog {} | agentlog since {} | agentlog show ID".format(
                args.command, args.arg, args.command, args.arg),
            file=sys.stderr,
        )
        return 2

    if args.limit < 1:
        print(
            "agentlog: --limit must be 1 or more (got {})\n"
            "  use --all to show every session".format(args.limit),
            file=sys.stderr,
        )
        return 2

    for flag, target in (("--html", args.html), ("--md", args.md)):
        if target:
            reason = _refuses_to_write(target, home_dir)
            if reason:
                print("agentlog: {} {}".format(flag, reason), file=sys.stderr)
                return 2

    # ---- 'list' command ----
    if args.command == "list":
        sessions, sources = find_sessions(home_dir)
        if not sessions:
            _no_sessions_msg(home_dir)
            return 0
        if args.html or args.md is not None:
            print(
                "agentlog: --html and --md are not supported for 'list'; "
                "use a time command (today, week, since ...) instead",
                file=sys.stderr,
            )
            return 2
        # The row limit is a property of the answer, not of how it is printed:
        # --json used to quietly return everything.
        limit = None if getattr(args, "all", False) else args.limit
        truncated = sessions if limit is None else sessions[:limit]
        if args.json:
            print(render_json(truncated))
            return 0
        print(render_list(truncated))
        if limit is not None and len(sessions) > limit:
            print(f"... and {len(sessions) - limit} more  (use --all to see everything)")
        return 0

    # ---- 'show SESSION_ID' command ----
    if args.command == "show":
        if not args.arg:
            print("agentlog: 'show' requires a session ID", file=sys.stderr)
            return 2
        sessions, sources = find_sessions(home_dir)
        prefix = args.arg.lower()
        matches = [s for s in sessions if s["id"].lower().startswith(prefix)]
        if not matches:
            print(f"agentlog: no session found matching '{args.arg}'", file=sys.stderr)
            return 2
        if len(matches) > 1:
            print(
                f"agentlog: {len(matches)} sessions match '{args.arg}'; "
                "showing the first. Use more characters to disambiguate:",
                file=sys.stderr,
            )
            for m in matches:
                print(f"  {m['id']}", file=sys.stderr)
        if args.html or args.md is not None:
            print(
                "agentlog: --html and --md are not supported for 'show'; "
                "use a time command (today, week, since ...) instead",
                file=sys.stderr,
            )
            return 2
        if args.json:
            print(render_json([matches[0]]))
            return 0
        print(render_show(matches[0]))
        return 0

    # ---- time-range commands ----
    if args.command == "since":
        if not args.arg:
            print("agentlog: 'since' requires a date or offset (e.g. since 3d)", file=sys.stderr)
            return 2
        since_dt = _parse_since(args.arg)
        if since_dt is None:
            print(
                f"agentlog: could not parse '{args.arg}' — "
                "use an ISO date (2026-07-01) or an offset (3d, 12h, 2w)",
                file=sys.stderr,
            )
            return 2
        until_dt = None
        period_label = f"since {args.arg}"

    elif args.command in ("today", "yesterday", "week"):
        since_dt = _since_for_period(args.command)
        until_dt = _until_for_period(args.command)
        period_label = args.command

    else:
        print(
            f"agentlog: unknown command '{args.command}'\n"
            "  try: agentlog today | yesterday | week | since DATE | show ID | list",
            file=sys.stderr,
        )
        return 2

    # Load and filter
    sessions, sources = find_sessions(home_dir)
    if not sessions and not sources:
        _no_sessions_msg(home_dir)
        return 0

    filtered = _filter_sessions(sessions, since=since_dt, until=until_dt)
    if args.project:
        filtered = _filter_project(filtered, args.project)

    # ---- HTML output ----
    if args.html:
        html_str = render_html(filtered, sources, period_label)
        try:
            with open(args.html, "w", encoding="utf-8") as fh:
                fh.write(html_str)
            print(f"wrote {args.html}")
        except OSError as exc:
            print(f"agentlog: could not write HTML: {exc}", file=sys.stderr)
            return 2

    # ---- Markdown output ----
    if args.md is not None:
        md_str = render_markdown(filtered)
        if args.md == "-":
            print(md_str)
        else:
            try:
                with open(args.md, "w", encoding="utf-8") as fh:
                    fh.write(md_str)
                print(f"wrote {args.md}")
            except OSError as exc:
                print(f"agentlog: could not write Markdown: {exc}", file=sys.stderr)
                return 2

    # ---- JSON output ----
    if args.json:
        print(render_json(filtered))
        return 0

    # ---- Default: plain text ----
    if not args.html and args.md is None:
        if not filtered:
            when = period_label
            # Naming the filter matters: an empty result with a --project flag
            # usually means the name was misspelled, not that nothing happened.
            if args.project:
                when += f" · project matching '{args.project}'"
            print(f"no sessions found for: {when}")
            if args.verbose:
                print(f"  searched {len(sessions)} total sessions")
        elif args.sessions:
            print(render_text(filtered, verbose=args.verbose))
        else:
            print(render_digest(filtered, period_label, verbose=args.verbose))

    return 0


def _no_sessions_msg(home_dir: Optional[str]) -> None:
    home = home_dir or os.path.expanduser("~")
    print(
        "No agent session logs found.\n\n"
        "agentlog looks for:\n"
        f"  Claude Code:  {os.path.join(home, '.claude', 'projects', '**', '*.jsonl')}\n"
        f"  Codex:        {os.path.join(home, '.codex', 'sessions', '**', '*.jsonl')}\n\n"
        "Start a session with Claude Code (claude) or Codex (codex) and run agentlog again."
    )


if __name__ == "__main__":
    sys.exit(main())
