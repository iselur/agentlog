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
agentlog on DAY                 one whole day: 2026-07-31, or 3d for three
                                days ago
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
                  (time commands only: today, yesterday, week, since, on)
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
| user turns | `type == "user"` records that are a person typing — not tool results, not subagent prompts (see below) |
| files read | `Read` tool-use calls (`input.file_path`) |
| files written | `Write`, `Edit`, `MultiEdit` tool-use calls (`input.file_path`) and `NotebookEdit` (`input.notebook_path`); Codex `patch_apply_end` records, plus `*** Update File:` lines inside older `apply_patch` envelopes |
| commands | `Bash` tool-use calls (`input.command`); Codex `custom_tool_call` script snippets, plus older `exec_command` and `apply_patch` calls |
| errors | `tool_result` records with `is_error: true`; Codex command output with a non-zero exit code, a patch that would not apply, and an `mcp_tool_call_end` whose `result` is an `Err` |
| the failing command | the tool-use call the failed result points back at (`tool_use_id` / `call_id`) |
| recap | `system` records with subtype `away_summary` — the short plain-English note a background session writes at the end of a turn, minus its trailing pointer at the settings screen |
| context | `system` records with subtype `compact_boundary` — how many times the session ran out of room and summarised itself, how long that took (`compactMetadata.durationMs`), and how much was thrown away (`preTokens - postTokens`, see below) |
| tokens | `message.usage.input_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` in `assistant` records; Codex uses the final `total_token_usage` snapshot, falling back to summing the per-turn `last_token_usage` blocks in a log too old to carry it |

**A turn is a time you said something.** Claude Code writes a `type: "user"`
record for four different things, and only one of them is a person: a tool
result fed back into the loop is the agent's own machinery, a record marked
`isSidechain: true` is a prompt the agent wrote for a subagent, and a record
marked `isMeta: true` is Claude Code putting text into the conversation on its
own account — the caveat that precedes a slash command's output, the body of a
skill being loaded, a message relayed from another session, a nudge to
continue, the placeholder standing in for a pasted image. Counting all four
reported 38318 turns across 896 real session logs where 2314 were typed, and
one session read 3637 for a day with 211. That kind of error is worth more
care than most, because a reader cannot catch it: an under-count can be checked
by adding up the sources, but there is nothing to check an over-count against —
it just reads as a long day. The subagent's *work* still counts; a `pytest -x`
it ran is a command that ran, and so does everything that happened around an
injected record. Only the claim that you spoke is dropped. A record with
neither field — older logs — is counted, since dropping real turns would be the
opposite mistake, and only an explicit `true` counts as either.

**Compaction is where long sessions go.**  When a session runs out of room,
Claude Code summarises the conversation so far and throws the rest away.  It
costs real wall-clock and it is not free of consequence, but nothing in the log
a person reads says it happened, so a session that spent hours re-reading its
own summary looks exactly like one that was merely slow.  `agentlog show` now
prints a `context` line when there was one:

```
context  compacted 98x — 3h 59m spent, 9,944,222 tokens dropped
```

Across the 896 logs this was developed against: 313 compactions in 49 sessions,
twelve hours of wall-clock, a median of 2m17s each, and a median of 13% of the
context surviving.  Manual `/compact` runs are counted separately from
automatic ones — one is a person deciding, the other is the session hitting a
wall, and a number that mixed them would overstate how often it hit the wall.

The subtraction matters.  The record also carries `cumulativeDroppedTokens`,
which is a **running total** — it equals the running sum of `preTokens -
postTokens` on every real record — so adding that field up across a session
counts the first compaction once for every compaction after it.  A session with
three of them would report roughly three times what was lost, and the only
thing wrong with the number is that it is too big, which is not something a
reader can check.  agentlog uses `pre - post` per compaction and lets the total
fall out of the sum.

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

MCP tool calls are reported in their own record, and only a failed one is shown.
A successful MCP call is not turned into a command — it is not a shell command,
and the command list means one thing — so a session that spent its time in MCP
tools will look quiet.  Its failures will not: before v0.2.3 they were in a
record nothing read, and four sessions on the logs this was found with reported
`0 errors` while an MCP server they had asked for was not running.

The read/written split is specific to Claude Code.  Codex has no structured
file-write field — it edits by handing a patch envelope to a patch tool — so
its written files come from the `patch_apply_end` record, which names them
absolutely and is also the only place a patch that *failed* is admitted.  A
patch that did not apply is counted as an error, never as a write.

Some builds never send that record: they hand the envelope to a
`custom_tool_call` — sometimes bare, sometimes wrapped in a JavaScript string
literal with the newlines escaped — and report nothing afterwards.  A session
that emitted no `patch_apply_end` at all therefore falls back to the
`*** Update File:` / `*** Add File:` / `*** Delete File:` lines in the envelope
itself.  The fallback is decided per session, not per call: if the session sent
even one end record, that build does report its own patches and the envelopes
are ignored, because the end record knows which patches failed and the envelope
does not.  Listing an edit that never reached the disk is the worse error of the
two — nothing else in the report contradicts it.  Relative paths are resolved
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

**Time nobody was working is not active time.**  A session is bursts of work
with nothing in between, so a stretch of silence longer than **five minutes** is
not counted.  Measuring instead from a session's first record to its last —
which is what this used to do — billed lunch, the commute and the whole night
as work: on the logs this was written against it came to **14×** the time Claude
Code itself records for the turns in those sessions, and five minutes is the
threshold that matches them (0.93 of the recorded time in aggregate, a median of
1.10 per session).  Being slightly under is the better way to be wrong for a
number somebody might quote.

Each session block therefore prints both — `3m 00s active, 6h 01m open` — and
`--json` gives you `active_s` beside `duration_s`, because "how long was this
session open" is a real and separate question.

The headline figure for a period is the **union** of every session's working
stretches clipped to that period, not their sum — agents run in parallel, and
summing them produced "111h in a 24h day".  It answers "how much of the day had
an agent working" rather than "how many agent-hours were spent".

**A session that spans the window is counted only for its share of it.**  A
session running from Tuesday to Friday appears in Wednesday's digest, but only
the files, commands, turns and errors timestamped inside Wednesday are counted,
and the duration shown is what it worked on Wednesday — not the span from
midnight.  Leave a session open overnight, come back and run one command at
09:16, and clipping to the *edge* of the day reported `9h 16m active` beside
`1 command`: every hour spent asleep counted as work.

A session that did nothing at all inside the window is counted as nothing, even
though it still appears there.  Only a session whose records carry no usable
timestamps falls back to its lifetime total — that is a session we cannot see
inside, which is a different thing from one we can see slept.  Confusing the two
made four separate days each report exactly `24h 00m`, and made a week come out
shorter than the days inside it added up to.

**Tokens are clipped the same way, against the period you asked for.**  A
week-long session used to report its whole week's spend into every day it
touched — on one real session, `88.3M` printed on the line directly below a
correctly clipped `1 command`, against the `14.2M` actually spent that day.  A
day now counts the turns that spent their tokens inside it, so seven days add up
to their week exactly.  Note the window here is the one you asked for, not the
one tightened onto the session's first and last tool call: a reply that costs a
thousand tokens and calls no tool is still spending, and anything spent after the
day's last tool call would otherwise vanish.  Sessions whose logs carry no
per-turn record of what was spent still report their lifetime total, for the same
reason a session with no timestamps does.

**Consecutive days add up.**  A day starts at local midnight and ends *before*
the next one, so anything stamped exactly on the stroke belongs to the day it
opens and is reported by `today`, not by `yesterday`.  Run the two commands back
to back and each thing that happened is counted once between them.

`on DAY` names any one of those days: `agentlog on 2026-07-31`, or `on 3d` for
three days ago.  `since` cannot answer this — `since 2026-07-31` means "from
Friday until now", never "Friday" — so before this the only two days you could
ask about were today and yesterday.  The two commands take the same argument
with one deliberate difference: `since 0d` is a window from now until now and is
refused as a typo, while `on 0d` is today.  A length is refused rather than
rounded (`12h` and `2w` name a duration, not a day) and says which command wants
one.

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
times — are collapsed into one row with a `(3x)` marker.  A failure the parser
could find no name for is still counted in `errors` but has no row to print, so
the count can exceed the list.  Until v0.2.3 that was most of them: a Codex
patch call carries no command, so every failed patch was nameless.  They are now
labelled with the files they touched.  `--sessions`,
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

**Conversation text is never shown.**  agentlog extracts metadata: file paths,
shell commands, durations, model names, and token counts.  What you typed and
what the agent replied is not extracted or displayed regardless of any flag.
The one piece of prose it does show is the agent's own recap of a background
turn (`away_summary`), which is described under Privacy below.

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

**A Claude Code record is counted once, in the file that had it first.**  Claude
Code writes the same records into two files in two ordinary situations: `claude
--resume` opens a new session id and copies the earlier transcript into it
verbatim before appending anything new, and a copied or moved project directory
leaves the same log under two names, neither a symlink.  Each record carries its
own uuid, so a uuid already counted is skipped.  Files are read oldest first, by
mtime, which means the sitting where the work actually happened is the one that
reports it — a resume shows the work done in the resume, and the earlier sitting
keeps its own.  Timestamps are skipped along with the counts, so a resume does
not inherit the earlier sitting's start time and look like a session that had
been running since the morning.

This is the opposite treatment from Codex above, and deliberately so: Codex's
several files are parallel workers whose separate work genuinely adds up, while
Claude's are copies of one worker's.  Merging is only safe once the records are
known to be distinct.

Until this was fixed, on the developer's own 269 Claude sessions the totals were
inflated by 163 commands, 14 written files, 20 errors, 101 turns and 31.1M input
tokens.  No session was lost — a file that is nothing but replay contributes no
counts and is not reported as unusable either, since none of its content is
missing from the report.

---

## Privacy

agentlog is strictly local.  No network code.  Nothing is uploaded or sent.

It shows metadata: file paths, shell commands, durations, and model names.
Conversation text is never extracted or displayed — not what you typed, not
what the agent replied.

There is one exception, and it is the reason this paragraph is longer than it
used to be.  A background session ends each turn by writing itself a short
recap — *"You asked what's in the ledger: it tracks 104 requests, all done
except R102"* — as a `system` record with subtype `away_summary`.  agentlog
shows those.  They are not conversation text: nothing you typed and nothing the
agent said is quoted, and Claude Code had already put the same sentence on your
screen.  But they are *about* the conversation, and a recap describes what a
session was for far better than a list of paths can.  If that is a line you
would not want in something you share, it is in `agentlog show`, `--md`,
`--json` and the HTML digest, and the note at the foot of the HTML says so.

The HTML digest may contain file paths, shell commands, and those recaps.
Review it before sharing it with others.

That promise has to hold for the parts of a session file that are not the
conversation, and two of those carry message text where nobody looks for it: a
`queue-operation` record holds the whole of a prompt you typed while the agent
was busy, and a `frame-link` record holds a question of yours turned into a
heading. There are 4983 of the first and 104 of the second in this machine's
logs. agentlog has no branch for either, and `tests/test_privacy_claims.py`
keeps them in its fixture — checked against the HTML digest too, since that one
leaves the machine — so the day somebody writes a branch, the tests are what
they meet first. A queued prompt is also not counted as a turn: more than half
are never sent (2494 enqueued against 1121 dequeued here), and the ones that
are get written again as a normal record when they go.

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

Each of those four claims is a test rather than a promise, in
`tests/test_family_claims.py`: every import resolves to the standard library or
to this package, nothing that can open a socket is imported, no environment
variable that looks like a credential is read, and no model SDK or provider
hostname appears anywhere. A claim repeated in five READMEs and checked in none
of them would read as five agreements when it was one assertion.

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
