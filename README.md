# agentlog

What did your coding agent actually do today?

agentlog reads your local Claude Code and Codex session logs and answers that in a screen: which projects it worked on, which files it edited, what failed. All offline, no network, no API key.

Everything is organised by project, because that is the first thing you want to know. Sessions, IDs and token counts are still there — one flag away — but they are not the headline.

`--html` writes the same digest as a self-contained file you can drop in a chat or share with a teammate. It works offline, requires no server, and contains no external assets.

---

## 30-second quickstart

```sh
pip install 'stillworks[all]'   # all five agent tools, including this one
pip install agentlog-tool       # or just this one (the command is `agentlog`)

agentlog today

# Or run from a checkout, no install needed — it is stdlib only:
cd /path/to/agentlog && python3 -m agentlog today
```

(The PyPI name is `agentlog-tool` because `agent-log` was already taken. The
command, the module, and the repo are all just `agentlog`.)

**Real output (2026-08-03, this machine):**

```
22h 45m active across 4 projects · today, Mon 3 Aug

  r102-bench          22h 43m   25 files · 143 commands · 4 errors
      edited   parser.py, render.py, cli.py
      failed   cd /home/val/r102-bench; echo "total:"; du -sh . 2>/dev/…
               edit parser.py
  val                 22h 42m   17 files · 122 commands · 8 errors
      edited   .../.orchestrator/HANDOFF.md, .../codex-orchestrator/AGENTS.md
      failed   cd /home/val/relay && ls .orchestrator/ && echo "=== git…
  relay                2h 10m   no edits or commands recorded
  codex-orchestrator   5m 07s   no edits or commands recorded

  19 sessions · 6 claude, 13 codex · busiest 22:00–23:00
  projects overlap — agents ran in parallel, so their times sum past the total
  more: agentlog list · agentlog show ID · agentlog --sessions
```

Busiest project first; the files are the ones written most often, and `failed`
names the command behind each error rather than just counting them.

Generate an HTML digest you can share:

```sh
agentlog today --html today.html
# then open today.html in a browser — no server required
```

---

## Commands

```
agentlog                        same as: agentlog today
agentlog today | yesterday | week
agentlog since DATE             ISO date (2026-07-15) or offset (3d, 12h, 2w)
agentlog show SESSION_ID        one session in full detail
agentlog list                   50 most-recent sessions as a compact table
agentlog list --all             all sessions (no row limit)
agentlog list --limit N         show at most N sessions

agentlog list (first 3 rows):

ID        PROJECT                   WHEN              DUR       SRC
--------  ------------------------  ----------------  --------  ------
019fc4b9  relay                     2026-08-02 23:05  6m 18s    codex
019fc4a7  relay                     2026-08-02 22:45  6m 41s    codex
019fc4a1  relay                     2026-08-02 22:39  4m 29s    codex
```

View flags:

```
--sessions        the old per-session view: one block per session, with IDs,
                  models, turn counts and token totals
--project NAME    only projects whose name or path contains NAME
```

Output flags:

```
--html FILE       write a self-contained HTML digest to FILE
                  (time commands only: today, yesterday, week, since)
--md [FILE]       Markdown to FILE, or stdout if FILE is omitted
                  (time commands only)
--json            JSON to stdout; works with all commands including list and show
--verbose         show parsing diagnostics (skipped-line counts)
--home DIR        override home directory; used by tests and CI
```

The `AGENTLOG_HOME` environment variable is equivalent to `--home`.

Exit codes: 0 normal, 2 usage or argument error, 130 stopped by ctrl-c,
141 the reader hung up (`agentlog today | head`, or `| less` quit with
`q`). The last two are deliberately not 0: a digest that was cut off
short reported nothing about your day, and `agentlog today > digest.md
&& mail-it` should not mail half of one.

---

## What it extracts and how

agentlog reads JSONL files in `~/.claude/projects/**/*.jsonl` (Claude Code)
and `~/.codex/sessions/**/*.jsonl` (Codex).  It never writes to those files
or uploads anything.

For each session it derives:

| Shown | Derived from |
|-------|-------------|
| project | `cwd` field in first `user` record |
| start / end / duration | first and last `timestamp` fields seen |
| models | `message.model` in `assistant` records |
| user turns | count of `type == "user"` records |
| files read | `Read` tool-use calls (`input.file_path`) |
| files written | `Write`, `Edit`, `MultiEdit` tool-use calls (`input.file_path`); Codex `patch_apply_end` records, plus `*** Update File:` lines inside older `apply_patch` envelopes |
| commands | `Bash` tool-use calls (`input.command`); Codex `custom_tool_call` script snippets, plus older `exec_command` and `apply_patch` calls |
| errors | `tool_result` records with `is_error: true`; Codex command output with a non-zero exit code |
| the failing command | the tool-use call the failed result points back at (`tool_use_id` / `call_id`) |
| tokens | `message.usage.input_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` in `assistant` records; Codex uses the final cumulative `last_token_usage` snapshot |

Tool-use IDs are deduplicated so streaming-split records are not double-counted.
Malformed lines are skipped silently; their count appears under `--verbose`.

Codex has sent its work in two different shapes.  Older sessions announce each
command as a `function_call` named `exec_command`, with the command in a
structured field.  Current builds send a `custom_tool_call` instead: the record
carries a snippet of JavaScript — `tools.exec_command({cmd:"pytest -x", ...})`,
often several inside one `Promise.all` — and the command has to be read back out
of the source.  Both are parsed.  Until v0.2.3 only the first was, which on the
machine this was found on made 65.6% of the recorded Codex work invisible and
left 74% of Codex sessions looking like the agent had done nothing; for the
current month it was 98%.  Nothing failed — the sessions were listed, with no
commands and no files under them, which is exactly what a session of pure
conversation looks like.

The read/written split is specific to Claude Code.  Codex has no structured
file-write field — it edits by handing a patch envelope to a patch tool — so
its written files come from the `patch_apply_end` record, which names them
absolutely and is also the only place a patch that *failed* is admitted.  A
patch that did not apply is counted as an error, never as a write.  Older
sessions with no such record fall back to the `*** Update File:` / `*** Add
File:` / `*** Delete File:` lines in the command text.  Relative paths are resolved
against the call's working directory, so one file is not counted twice under two
spellings.  Codex files it only *reads* are not distinguishable from any other
shell command, and are not reported.

---

## Why this tool

You spent the day with Claude Code or Codex.  What actually happened?

- Which files did it touch?
- How many commands did it run?
- Which sessions ran long?
- Where did things break?

That information is in your JSONL session logs, but reading raw JSONL is not
practical.  agentlog parses it and gives you a summary you can read in seconds.

The HTML output (`--html`) is meant to be shared: a single offline file
containing the activity metadata of one or more sessions, useful for stand-ups,
reviews, or just keeping your own notes.

**Why not just ask my AI to summarize the logs?**
That works, but it involves sending your session logs to a model API.  agentlog
stays entirely local: it reads log structure, not content, and nothing leaves
your machine.

---

## Prior art (and what is different)

Many tools read Claude Code JSONL logs.  agentlog occupies a specific gap.

**[ccusage](https://github.com/ccusage/ccusage)** (ccusage.com)
Token and cost tracking for Claude Code, Codex, and 15+ other agent CLIs.
Daily/weekly/monthly summaries, per-project filtering, JSON output, MCP server.
It reads the same files agentlog reads.  Session data includes aggregate tool-call
counts but surfaces them as numbers, not as enumerated file and command lists.
agentlog is complementary: ccusage answers "what did it cost?" agentlog answers
"what did it do?"

**[claude-code-log](https://github.com/daaain/claude-code-log)**
Python CLI that converts Claude Code JSONL transcripts to self-contained HTML
or Markdown.  Excellent for reading full conversation content.  Works per-file
or per-project.  agentlog differs in focus: it shows metadata (files, commands,
durations) rather than conversation content, and aggregates across multiple
sessions in a time range.

**[claude-code-trace](https://github.com/delexw/claude-code-trace)**
JSONL session viewer shipped as a native desktop GUI, web app, and TUI.  Shows
conversations, tool calls, and token counts per session with live tailing.
No standalone HTML export and no cross-session time-range digest.

**[Claudoscope](https://claudoscope.com)**
Native macOS menu bar app.  Session browser, cost/token stats, generated-files
view, full transcript, real-time secret scanning.  macOS only, no CLI mode,
no HTML export, not scriptable.

**[CASS — coding_agent_session_search](https://github.com/Dicklesworthstone/coding_agent_session_search)**
Unified TUI and CLI for indexing and searching session history across 11+ agent
providers using BM25 and semantic embeddings.  SQLite-backed.  A search tool,
not a digest generator.

**[vibe-log-cli](https://github.com/vibe-log/vibe-log-cli)**
Daily activity summary for Claude Code and Codex sessions.  Analysis is routed
through ACP — it uses your local Claude Code or Codex instance to produce the
summary rather than parsing JSONL structure directly.  Requires a running agent.

**[agentlogs](https://github.com/agentlogs/agentlogs)** (agentlogs.ai)
Cloud-based team observability: captures and uploads session transcripts.
Requires login and network upload.

**[agent-sessions](https://github.com/jazzyalex/agent-sessions)**
Local-first macOS app for browsing, searching, and resuming sessions across many
providers.  macOS only, no CLI, no HTML export.

**[claude-session-analyzer](https://github.com/lucemia/claude-session-analyzer)**
Quantitative behavioral analysis: thinking depth, Read/Edit ratio, rework
indicators.  Aimed at workflow optimization, not readable activity digests.

**Where agentlog fits:**
`agentlog list` and `agentlog show` are the scriptable, terminal-native way to
browse sessions without launching a GUI or browser.  `agentlog --html` produces
a self-contained offline file for sharing — the existing GUI tools are
session-by-session viewers, not cross-session digest generators.

---

## Honest limits (v0.2)

**Schema drift.**  Claude Code and Codex change their log formats without
notice.  Fields that agentlog reads today may move or disappear.  Parsing is
defensive and will not crash, but some sessions may show empty file or command
lists if the format changes.  That has already happened once, and is the worst
failure this tool has: an empty list is indistinguishable from a quiet session,
so a whole format going unread looks like the agent was idle rather than like a
bug.  Both known Codex shapes are parsed side by side rather than one replacing
the other, and `--verbose` names files that could not be read at all.

**A log file it cannot read is named, not skipped.**  A file whose permissions
changed, or one truncated mid-write into bytes that no longer parse, cannot
contribute a session — and until v0.2.3 it contributed nothing to the report
either, including any mention that it existed.  One good file beside two broken
ones reported "1 session", in `today`, in `list` and in `--json` alike, which is
the wrong answer in the direction that looks fine.  Every view now ends with

    note: 2 log files were not counted — 1 could not be read, 1 had no readable records
          (run with --verbose to see which)

and `--verbose` names the paths.  Under `--json` and `--md -` the note goes to
stderr, so stdout stays the bare array or the bare document.  The exit code
stays 0: agentlog reports, it does not gate.  An empty file is deliberately not
one of these — a session that has just started has nothing in it yet, and
nothing has been lost.

**Project identification is best-effort.**  The project is taken from the `cwd`
field of the first `user` record in a session.  If a session starts before a
`user` record is written, the project falls back to a guess derived from the
directory name, which is ambiguous when paths contain dashes.

**Wall duration is elapsed time, not effort.**  A session's duration is (last
timestamp – first timestamp) in its file; the logs contain no reliable
elapsed-time field, so idle time between tool calls is included.  The headline
figure for a period is the **union** of all session intervals clipped to that
period, not their sum — agents run in parallel, and summing them produced
"111h in a 24h day".  It therefore answers "how much of the day had an agent
working" rather than "how many agent-hours were spent".

**A session that spans the window is counted only for its share of it.**  A
session running from Tuesday to Friday appears in Wednesday's digest, but only
the files, commands, turns and errors timestamped inside Wednesday are counted,
and the duration shown runs from the first thing it did on Wednesday to the
last — not from midnight.  Leave a session open overnight, come back and run
one command at 09:16, and clipping to the *edge* of the day reported `9h 16m
active` beside `1 command`: every hour spent asleep counted as work.  Sessions
whose records carry no usable timestamps fall back to their lifetime totals.

**Two clocks are involved, and the log's wins.**  The timestamps come from
whichever machine wrote the log, which may be ahead of the one reading it — an
NTP step, a resumed VM, a synced home directory.  A named day runs to midnight,
so events dated a few minutes into the future are still part of `today`; only
`yesterday` and an explicit end actually clip.  `agentlog` never treats the
moment you ran it as the end of a window you did not ask to end.

**Codex file tracking is partial.**  Written files come from `patch_apply_end`
records, falling back to patch envelopes in the command text, which together
cover Codex's normal edit path.  A file
changed some other way — `sed -i`, a heredoc, a script the agent wrote and then
ran — is not detected, and files Codex only reads are never reported.  So a
Codex project's file list is a floor, not a complete account.

**The digest is a summary, and summaries drop things.**  Per project it shows
the three most-written files and the three most frequent distinct failures, and
it lists at most eight projects before collapsing the rest into a count.
Failures that differ only below their first line — the same heredoc run three
times — are collapsed into one row with a `(3x)` marker.  `--sessions`,
`agentlog show ID` and `--json` give the unabridged version.

**One item is one row.**  Everything on screen came out of a log file written
by the agent being audited, so a command or path is flattened to a single line
before it is printed.  Otherwise a command containing a newline printed as
several rows, each looking exactly like a real command that ran — `commands
(1):` above three `$` lines — and agents write multi-line heredocs all day.
The row counts in the headers are the check, and they are only true if this
holds.  In `agentlog show`, a line longer than 400 characters is cut with a
marker saying how much was dropped; `--json` always has the whole thing.

**Tokens are not verified.**  Token counts come from usage fields in the logs.
They may differ from what your billing provider records.

**Message text is never shown.**  agentlog extracts metadata only: file paths,
shell commands, durations, model names, and token counts.  Conversation content
is not extracted or displayed regardless of any flag.

**No test coverage against the developer's real logs.**  The test suite uses
synthetic fixtures.  It cannot guarantee correct parsing of every schema variant
in the wild.

**Codex parallel workers are merged into one session.**  When Codex runs worker
agents, all of them share one session_id and each writes its own file.  They are
one session, so they are shown as one row, with the commands and files unioned
and the turns, errors and tokens added up.  Times therefore span the whole fan
-out rather than any single worker, and a per-worker breakdown is not available.

Until v0.2.3 the extra files were discarded and only the richest one kept.  On
the logs this was found with, that hid 299 of 616 commands in the 21 sessions
that had more than one file, and 38 of the 42 discarded files contained commands
the kept one did not.

---

## Privacy

agentlog is strictly local.  No network code.  Nothing is uploaded or sent.

It shows metadata only: file paths, shell commands, durations, and model names.
Message text is never extracted or displayed.

The HTML digest may contain file paths and shell commands from your sessions.
Review it before sharing it with others.

---


## Install

```sh
# From source (no install — works immediately):
python3 -m agentlog today

# Install for the current user:
pip install --user .

# Or in a virtualenv:
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/agentlog today
```

Requires Python 3.9 or later.  Zero runtime dependencies.

---

## Running the tests

```sh
python3 -m unittest discover -s tests -v
```

The tests use synthetic JSONL fixtures in a temporary directory.  No real home
directory is touched.  Pass `--home DIR` or set `AGENTLOG_HOME=DIR` to redirect
agentlog to a different home in any context.

---

## Part of a small family

Five tools for working with coding agents, same house style: zero
dependencies, MIT, no API key, nothing leaves your machine. None of them
call a model — that is the point, since the thing being checked already is
one.

- [stillworks](https://github.com/iselur/stillworks) — record what your code does now, catch when it changes later
- [agentdiff](https://github.com/iselur/agentdiff) — see what the agent actually changed, before you merge
- [agentlog](https://github.com/iselur/agentlog) — what did your coding agent actually do today?  ← you are here
- [agentwatch](https://github.com/iselur/agentwatch) — tail what your agent is doing, right now
- [unedit](https://github.com/iselur/unedit) — a safety net for letting an agent loose on your files

One install gets all five, and `stillworks tools` says which ones you have:

```sh
pip install 'stillworks[all]'
stillworks tools
```

## License

MIT.  Copyright (c) 2026 stillworks contributors.
