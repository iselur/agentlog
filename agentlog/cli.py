"""agentlog command-line interface.

Commands
--------
  agentlog                       # same as: agentlog today
  agentlog today | yesterday | week
  agentlog since DATE            # ISO date, or offset like 3d / 12h
  agentlog show SESSION_ID       # one session in full detail
  agentlog list                  # all sessions, compact table

Output flags (may be combined with any time command)
  --html FILE                    # write self-contained HTML digest
  --md [FILE]                    # Markdown (to FILE or stdout)
  --json                         # machine-readable JSON

Other flags
  --content                      # include message text excerpts (off by default)
  --verbose                      # show skipped-line counts and debug hints
  --home DIR                     # override home directory (useful for tests)

Exit codes
  0   normal
  2   usage or argument error

The tool never writes to or uploads the session logs.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import __version__
from .parser import find_sessions
from .render import render_json, render_list, render_markdown, render_show, render_text
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
        unit = value[-1]
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "w": timedelta(weeks=n)}[unit]
        return datetime.now(timezone.utc) - delta

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

def _filter_sessions(
    sessions: List[Dict],
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> List[Dict]:
    out = []
    for s in sessions:
        ts = s["start"]
        if ts is None:
            continue
        if since is not None and ts < since:
            continue
        if until is not None and ts >= until:
            continue
        out.append(s)
    return out


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
    p.add_argument("--content", action="store_true", help="include message text excerpts")
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

def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    home_dir = args.home or os.environ.get("AGENTLOG_HOME") or None

    # ---- 'list' command ----
    if args.command == "list":
        sessions, sources = find_sessions(home_dir)
        if not sessions:
            _no_sessions_msg(home_dir)
            return 0
        print(render_list(sessions))
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
        print(render_show(matches[0], content=args.content))
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
            print(f"no sessions found for: {when}")
            if args.verbose:
                print(f"  searched {len(sessions)} total sessions")
        else:
            print(render_text(filtered, verbose=args.verbose))

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
