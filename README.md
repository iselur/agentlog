# agentlog

What did your coding agent actually do today?

agentlog reads your local Claude Code and Codex session logs and turns them into a readable digest: which projects were touched, which files were opened or edited, which shell commands ran, how long each session took, where things broke. All offline, no network, no API key.

The primary deliverable is `--html`: a self-contained HTML file you can drop in a chat or share with a teammate. It works offline, requires no server, and contains no external assets.

---

## 30-second quickstart

```sh
# Run from source (no install needed):
cd /path/to/agentlog
python3 -m agentlog today

# Or install for the current user:
pip install --user .
agentlog today
```

**Real output (2026-08-02, this machine):**

```
87 sessions · 21h 07m · 6 projects · 37 files edited · 603 commands · 19 errors

  019fc4a1  relay  [codex]
    2026-08-02 22:39 – 22:39  (5s)  1 turns

  251407af  r102-bench  [claude]
    2026-08-02 22:31 – 22:38  (6m 59s)  7 turns
    model: claude-sonnet-4-6
    files:
      /home/val/agentdiff/agentdiff/__init__.py
      /home/val/agentdiff/agentdiff/git.py
    commands (4):
      $ ... -20 && test -d /home/val/agentdiff && echo "EXISTS" || echo "DOES NO...
      $ ls /home/val/stillworks/ && head -30 /home/val/stillworks/pyproject.toml
      $ ... and 2 more
    tokens — in: 8  out: 232

  4ef1361b  val  [claude]  "orchestrator migration to codex"
    2026-08-02 13:07 ��� 22:36  (9h 29m)  552 turns
    model: claude-fable-5, claude-opus-5
    files:
      /home/val/orchestrator/CLAUDE.md  (read)
      ... and 24 more
    commands (345):
      $ ls -la /home/val/orchestrator/ && which codex && codex --version 2>/dev/...
      $ ... and 340 more
    tokens — in: 944  out: 317,808
    errors: 11
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
agentlog list                   all sessions as a compact table

agentlog list (first 5 rows):

ID        PROJECT                   WHEN              DUR       SRC
--------  ------------------------  ----------------  --------  ------
019fc4a1  relay                     2026-08-02 22:39  13s       codex
251407af  r102-bench                2026-08-02 22:31  6m 59s    claude
251407af  r102-bench                2026-08-02 22:27  11m 32s   claude
```

Output flags (combine with any time command):

```
--html FILE       write a self-contained HTML digest to FILE
--md [FILE]       Markdown to FILE, or stdout if FILE is omitted
--json            JSON to stdout (machine-readable, for pipes)
--content         include message text excerpts (off by default)
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
| tokens | `message.usage.input_tokens` / `output_tokens` in `assistant` records |

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

**Wall duration is a lower bound.**  Duration is computed as (last timestamp –
first timestamp) in each session file.  The logs do not contain a reliable
elapsed-time field.  Idle time between tool calls is included.

**Codex file tracking is limited.**  Codex routes all file access through shell
commands (`exec_command`).  agentlog reports those commands verbatim; it does
not parse them to extract file paths.  The `files read` / `files written`
columns are always empty for Codex sessions.

**Tokens are not verified.**  Token counts come from usage fields in the logs.
They may differ from what your billing provider records.

**Content is not shown by default.**  Pass `--content` to include message
excerpts.  The HTML digest contains file paths and shell commands; review it
before sharing.

**No test coverage against the developer's real logs.**  The test suite uses
synthetic fixtures.  It cannot guarantee correct parsing of every schema variant
in the wild.

---

## Privacy

agentlog is strictly local.  No network code.  Nothing is uploaded or sent.

By default it shows metadata only: file paths, shell commands, durations, and
model names.  Message text is hidden unless you pass `--content`.

The HTML digest may contain file paths and shell commands from your sessions.
Review it before sharing it with others.

---

## Part of a small family

agentlog is part of a small family of zero-dependency tools for working with
coding agents.  See **[stillworks](https://github.com/iselur/stillworks)**:
behavior-lock for AI-edited and legacy code — record what your code does now,
catch when it changes later.

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

## License

MIT.  Copyright (c) 2026 stillworks contributors.
