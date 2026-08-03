# agentlog

What did your coding agent actually do today?

agentlog reads your local Claude Code and Codex session logs and turns them into a readable digest: which projects were touched, which files were opened or edited, which shell commands ran, how long each session took, where things broke. All offline, no network, no API key.

The primary deliverable is `--html`: a self-contained HTML file you can drop in a chat or share with a teammate. It works offline, requires no server, and contains no external assets.

---

## 30-second quickstart

```sh
pip install agentlog-tool     # the command is `agentlog`
agentlog today

# Or run from a checkout, no install needed — it is stdlib only:
cd /path/to/agentlog && python3 -m agentlog today
```

(The PyPI name is `agentlog-tool` because `agent-log` was already taken. The
command, the module, and the repo are all just `agentlog`.)

**Real output (2026-08-02, this machine):**

```
29 sessions · 17h 09m · 5 projects · 18 files edited · 452 commands · 14 errors

  019fc4b9  relay  [codex]
    2026-08-02 23:05 – 23:12  (6m 18s)  1 turns
    tokens — in: 151,757  out: 1,224

  019fc4a7  relay  [codex]
    2026-08-02 22:45 – 22:52  (6m 41s)  1 turns
    tokens — in: 168,085  out: 2,713

  4ef1361b  val  [claude]  "orchestrator migration to codex"
    2026-08-02 13:07 – 23:18  (10h 10m)  669 turns
    model: claude-fable-5, claude-opus-5
    files:
      /home/val/orchestrator/CLAUDE.md (r)
      ... and 24 more
    commands (433):
      $ ls -la /home/val/orchestrator/ && which codex && codex --version 2>/dev/...
      $ ... and 428 more
    tokens — in: 50,603,331  out: 374,633
    errors: 14
```

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

Exit codes: 0 normal, 2 usage or argument error.

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
| files written | `Write`, `Edit`, `MultiEdit` tool-use calls (`input.file_path`) |
| commands | `Bash` tool-use calls (`input.command`); Codex `exec_command` |
| errors | `tool_result` records with `is_error: true` |
| tokens | `message.usage.input_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` in `assistant` records; Codex uses the final cumulative `last_token_usage` snapshot |

Tool-use IDs are deduplicated so streaming-split records are not double-counted.
Malformed lines are skipped silently; their count appears under `--verbose`.

The `files read` / `files written` split is specific to Claude Code.  Codex
routes all file access through shell commands (`exec_command`), so its sessions
report commands only.

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

## Honest limits (v0.1)

**Schema drift.**  Claude Code and Codex change their log formats without
notice.  Fields that agentlog reads today may move or disappear.  Parsing is
defensive and will not crash, but some sessions may show empty file or command
lists if the format changes.

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
and the duration shown is the part that fell inside the window.  Sessions whose
records carry no usable timestamps fall back to their lifetime totals.

**Codex file tracking is limited.**  Codex routes all file access through shell
commands (`exec_command`).  agentlog reports those commands verbatim; it does
not parse them to extract file paths.  The `files read` / `files written`
columns are always empty for Codex sessions.

**Tokens are not verified.**  Token counts come from usage fields in the logs.
They may differ from what your billing provider records.

**Message text is never shown.**  agentlog extracts metadata only: file paths,
shell commands, durations, model names, and token counts.  Conversation content
is not extracted or displayed regardless of any flag.

**No test coverage against the developer's real logs.**  The test suite uses
synthetic fixtures.  It cannot guarantee correct parsing of every schema variant
in the wild.

**Codex session deduplication keeps one file per session ID.**  When Codex runs
parallel worker agents, all workers share the same session_id.  agentlog keeps
the file with the most user turns and discards the rest.  Activity recorded only
in the discarded workers (commands, errors) is not surfaced.

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

Four tools for working with coding agents, same house style: zero dependencies,
MIT, no API key, nothing leaves your machine. None of them call a model — that is
the point, since the thing being checked already is one.

- [stillworks](https://github.com/iselur/stillworks) — record what your code does now, catch when it changes later
- [agentdiff](https://github.com/iselur/agentdiff) — see what the agent actually changed, before you merge
- [agentlog](https://github.com/iselur/agentlog) — what did your coding agent actually do today?  ← you are here
- [unedit](https://github.com/iselur/unedit) — a safety net for letting an agent loose on your files

## License

MIT.  Copyright (c) 2026 stillworks contributors.
