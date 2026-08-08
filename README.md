# agentlog

What did your coding agent actually do today?

agentlog reads your local Claude Code and Codex session logs and answers that in a screen: which projects it worked on, which files it edited, what failed. All offline, no network, no API key.

Everything is organised by project, because that is the first thing you want to know. Sessions, IDs and token counts are still there — one flag away — but they are not the headline.

`--html` writes the same digest as a self-contained file you can drop in a chat or share with a teammate. It works offline, requires no server, and contains no external assets.

---

## 30-second quickstart

```sh
pip install stillworks   # one install, all five agent tools, including this one

agentlog today

# Or run from a checkout, no install needed — it is stdlib only:
cd /path/to/agentlog && python3 -m agentlog today
```

(Since stillworks 0.2.0 the whole family ships in one wheel. The command, the
module, and the repo are all just `agentlog`; the old standalone PyPI name
`agentlog-tool` is the 0.1.x era and gets no further releases.)

**Real output (`agentlog on 2026-08-03`, this machine):**

```
3h 21m active across 6 projects · on 2026-08-03

  r102-bench             2h 44m   44 files edited · 350 commands · 13 errors
      asked    "simplify the harness research artifact signifxantky, its a weird
               mess of lots of unhelpful tech data. summarize the findings…"
      edited   …/unedit/store.py, …/agentlog/parser.py, ~/agentlog/README.md
      failed   Artifact
               cd $CLAUDE_JOB_DIR/tmp && timeout 1800 python3 matrix.py 2>&1 | …
               cd …/tmp && rm -rf ro && mkdir -p ro && cd ro && PYTHONPATH=~/… …
  relay                  1h 30m   13 files edited · 320 commands
      asked    "Round 3 of the review of a promotion from `ready-for-main` to
               `main` (PR #240) in the Relay orchestrator repo. You reviewed…"
      edited   relay-harness-map.h…, …/hosting.json, SkeletonPreview.tsx…
  val                    1h 23m   18 files edited · 295 commands · 8 errors
      asked    "I want to switch orchestrator to codex. How we are going to go
               about it? My claude subscription will end and I wont be able to…"
      edited   …/HANDOFF.md, …/AGENTS.md, …/BOOTSTRAP.md
      failed   cd relay && echo "=== .gitignore ==="; cat -n .gitignore; echo "…
               cd relay && ls .orchestrator/ && echo "=== gitignore handoff ===…
               cd relay && wc -l .orchestrator/HANDOFF.md && echo "=== head ===…
  codex-orchestrator     3m 13s   15 commands · 2 errors
      asked    "Review this diff as a senior engineer: correctness, security,
               simplicity, maintainability. WHAT IT IS. Two things, one PR, in…"
      failed   set +e …
  relay-review-wwx5ix7y  1m 49s   20 commands
      asked    "You are a code reviewer acting as a hard, fail-closed gate.
               Review ONE worker change against ONE spec. Return a verdict on…"
  relay-review-1lj4i4i1     55s   4 commands
      asked    "You are a code reviewer acting as a hard, fail-closed gate.
               Review ONE worker change against ONE spec. Return a verdict on…"

  22 sessions · 6 claude, 16 codex · busiest 22:00–23:00
  projects overlap — agents ran in parallel, so their times sum past the total
  compacted 203x in 5 sessions · 8h 12m spent on it, 20,572,030 tokens dropped
  more: agentlog list · agentlog show ID · agentlog --sessions
```

Busiest project first. `asked` is the prompt you typed that names the work — the
one row that says what the session was *for*; the files are the ones written
most often, and `failed` names the command behind each error rather than just
counting them.

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
agentlog since WHEN             10m, 2h, 3d, 1w, or a date like 2026-08-03
agentlog on DAY                 one whole day: 2026-07-31, or 3d for three
                                days ago
agentlog show SESSION_ID        one session in full detail
agentlog list                   50 most-recent sessions as a compact table
agentlog list --all             all sessions (no row limit)
agentlog list --limit N         show at most N sessions
agentlog handover               run by an agent hook, not by you — see
                                "The note a session leaves itself"

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
--brief           a written report instead of a log: what you worked on, what
                  is done, what is not.  This one asks a model, so it sends
                  the day off this machine — see Privacy
--project NAME    only projects whose name or path contains NAME
--file PATH       read only this transcript, all of it (the time command does
                  not apply)
```

`--file` is for the caller that already knows which file it wants.  Reading one
transcript takes about two seconds where reading a whole home takes minutes,
which is the difference between fitting inside an agent hook's timeout and not.
The time command is ignored on purpose: a session you name by path is reported
whole, including the part of it that happened yesterday.  Which agent wrote the
file is worked out by reading it, not from where it sits or what it is called,
so a transcript copied somewhere else — or truncated so its opening records are
gone — still reads.

`--brief` is the answer to "what did you get done today?", which is a different
question from "what happened today?":

```
today, Sat 8 Aug · 2h 00m · 2 sessions · 2 projects · 1.1M tokens

Two things:

  1. Ship the digest rewrite
     done      The release went out and both repositories are pushed with the
               whole suite green.
     not done  It is not on PyPI yet, so installing still gets the old one.
     agentlog, stillworks · 2 sessions · 2h 00m · 1.1M tokens · 2 files edited
```

The headings and the two sentences are written by a model.  Every figure is
not: the tally under a theme is computed from the sessions the model put in
that theme, so a model that miscounts changes the wording and never the
arithmetic, and a project it invents is dropped before it can carry a number.
With no model installed the page still prints — the tallies, what finished and
what was still failing — and says which part is missing.

`AGENTLOG_MODEL_CMD` names the command to ask, if it should not be `claude`.
It is run with `-p` and given the prompt on standard input.

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

## The note a session leaves itself

A long conversation gets compacted: the transcript is replaced by a summary so
the work can carry on, and what the agent knew about the last four hours
becomes whatever the summary kept.  The transcript is still on disk and still
complete, so the facts are not gone — only the agent's hold on them is.

`agentlog handover` reads the transcript in the moment before compaction, writes
down what the session had actually done, and hands it back when the session
resumes.  Two hooks in `~/.claude/settings.json`, the same line twice:

```json
{
  "hooks": {
    "PreCompact": [
      {"matcher": "auto",   "hooks": [{"type": "command", "command": "agentlog handover || true"}]},
      {"matcher": "manual", "hooks": [{"type": "command", "command": "agentlog handover || true"}]}
    ],
    "SessionStart": [
      {"matcher": "compact", "hooks": [{"type": "command", "command": "agentlog handover || true"}]}
    ]
  }
}
```

Which of the two jobs to do is read off the event name in the payload, so there
is no flag to get the wrong way round.  The `|| true` is not superstition: a
`PreCompact` hook that exits non-zero blocks the compaction it was watching, and
the one way this command can exit non-zero is by being an older `agentlog` that
has never heard of `handover`.  One idiom and an upgrade half-done can no longer
stop your session.  What comes back is the same digest the
plain command prints — where the work was, how long, which files were edited,
which commands kept failing — under a line saying where it came from.

Three deliberate choices:

- **No model.** Compaction already writes a summary; a second account of the
  same conversation would drift the same way.  What a compacted session cannot
  reconstruct is the plain record, and that is all this hands over.
- **Once.** The note is deleted as it is handed over.  Left behind it would be
  injected again at the next compaction, stating two-hour-old facts in the
  present tense.
- **Never in the way.** Every failure exits 0 and explains itself on stderr.  A
  `PreCompact` hook that exits non-zero blocks the compaction it was watching,
  so the agent stops and the reason is the note-taker.

It is quick enough to sit in a hook's timeout: about two seconds on a
thirty-hour session, against minutes for a whole-home scan.

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
| files read | `Read` tool-use calls (`input.file_path`); for Codex, the paths handed to a reading command in a `custom_tool_call` snippet or an older `exec_command` — Codex has no read tool, so a read is a `cat` or a `sed -n` and the command text is the only record of it |
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
context  compacted 98x — 3h 59m spent on it, 9,944,222 tokens dropped
```

The digest says it too, because `show` needs a session id and a session id
needs you to already suspect which session to look at:

```
compacted 127x in 6 sessions · 4h 54m spent on it, 13,239,126 tokens dropped
```

The number of sessions is in that line on purpose.  Twelve compactions in one
session is a session that should have been split; twelve across twelve sessions
is an ordinary week, and the count alone cannot tell them apart.

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

**A Codex read is a guess made from a command, and it under-reports on
purpose.**  Claude Code reads a file by calling a tool named `Read`, so the path
is a field.  Codex has no read tool: it reads by running `sed -n '1,200p'
notes.md`, and the command text is the only record.  Every Codex session
therefore reported *no files read* until v0.2.5 — not an error, just a zero that
looked like a fact.

They are read out of the command now, by a rule built to miss rather than to
invent: a path is counted only when the verb opens everything it is handed
(`cat`, `head`, `tail`, `sed`, `wc`, `md5sum` and a dozen more).  Nothing that
searches is counted at all — `rg pattern src/` puts a pattern, a glob and a
directory in the position a path goes, and the text cannot say which is which,
so `grep` and `rg` reads are missed on purpose.  A file named in a digest that
was never opened costs more than one that is missing.

Measured against the 1,217 Codex sessions on the machine this was written on:
3,021 of 8,322 commands name a read, 944 sessions gain one, and of 4,472 claimed
paths 87.5% are a file that still exists — the rest are the temporary files a
session makes and deletes.  One was a directory.

**A log file it cannot read is named, not skipped.**  A file whose permissions
changed, or one truncated mid-write into bytes that no longer parse, cannot
contribute a session — and until v0.2.3 it contributed nothing to the report
either, including any mention that it existed.  One good file beside two broken
ones reported "1 session", in `today`, in `list` and in `--json` alike, which is
the wrong answer in the direction that looks fine.  Every view now ends with

    note: 2 session logs are not shown — 1 could not be read, 1 had no readable records
          (run with --verbose to see which)

and `--verbose` names the paths — every one of them, not a sample, because a
report is re-runnable and somebody who asked which files has asked for the list.
It is the same sentence `agentwatch` prints about the same logs: one wording in
both commands, which arrive in one install.  Under `--json` and `--md -` the
note goes to stderr, so stdout stays the bare array or the bare document.  The exit code
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
ask about were today and yesterday.  `on` takes a date or a number of days, and
that is the whole of the overlap with `since`: `10m`, `12h` and `2w` name a
duration rather than a day, so `on` refuses them rather than rounding, and says
which command wants one.  `0d` is the one place the two part company on purpose
— `since 0d` is a window from now until now and is refused as a typo, while
`on 0d` is today.

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

**What the agent said is never shown; what you asked for is.**  agentlog
extracts metadata — file paths, shell commands, durations, model names, token
counts — plus the prompt you typed that names the work, because a digest that
cannot say what a session was *for* is a list of filenames.  Nothing the agent
replied, nothing it thought, and nothing a command printed is extracted or
displayed by any flag.  This is described in full under Privacy below.

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

agentlog reads files and prints.  No network code.  Nothing is uploaded or sent.

**One command is the exception, and this is it: `--brief`.**  It asks a model to
name what the day's work was, because grouping eleven sessions into "getting the
release out" is a judgement and there is no arithmetic for it.  To do that it
hands the day's evidence — project names, the prompts you typed, shell commands,
file paths, the agent's own recaps — to the `claude` command already installed on
your machine.  That evidence leaves the machine.  Nothing else here does, and
that is not a promise about intentions: `agentlog/asking_a_model.py` is the only
module in the package allowed to run another program at all, and
`tests/test_privacy_claims.py` fails if a second one ever does.  The flag's own
help says the same in one line, and no other mode may be combined with it.

The rest of this section describes every other command.

**Half of a conversation is shown, and it is your half.**  Every mode prints
the prompt you typed that names the work — `asked: "fix the parser and run the
suite"` — because a digest that lists 247 commands and cannot say what any of
them was for is answering a question nobody asks.  Somebody wrote down the goal
of the session at the top of it; there is no honest way to report the session
without it.

Not the whole of your half.  One prompt per session: the first that says what
is wanted rather than agreeing with something ("ok", "yes", "continue" are
skipped), cut to 400 characters, and cut again to whatever room the row has.

**The agent's half is never shown**, and neither is anything a command did:

| shown | not shown |
| --- | --- |
| the prompt that names the work | anything the agent replied |
| file paths read and written | anything the agent thought (`thinking`) |
| shell commands, and which failed | anything a command printed (`tool_result`) |
| durations, model names, token counts | the contents of a file it wrote |
| the agent's `away_summary` recaps | prompts you queued but never sent |

Two of those rows are less obvious than the rest, so they are worth naming.

A background session ends each turn by writing itself a short recap — *"You
asked what's in the ledger: it tracks 104 requests, all done except R102"* — as
a `system` record with subtype `away_summary`.  agentlog shows those.  They are
written by the agent about the conversation rather than in it, and Claude Code
had already put the same sentence on your screen.

And two parts of a session file carry message text where nobody looks for it: a
`queue-operation` record holds the whole of a prompt you typed while the agent
was busy, and a `frame-link` record holds a question of yours turned into a
heading. There are 4983 of the first and 104 of the second in this machine's
logs. agentlog reads neither — a prompt you queued and closed the terminal on
was never asked, and more than half are never sent (2494 enqueued against 1121
dequeued here); the ones that are get written again as an ordinary prompt when
they go, and that copy is the one agentlog reads.

`tests/test_privacy_claims.py` is where all of this is enforced rather than
promised: one marker planted in the prompt, which every output mode must show,
and another planted in the agent's replies, its thinking, a tool result, a
written file, a recap's neighbours, a `queue-operation` and a `frame-link`,
which no output mode may show — the HTML digest included, since that one leaves
the machine.

The HTML digest may therefore contain file paths, shell commands, recaps, and
what you typed to ask for the work.  Review it before sharing it with others;
the note at the foot of the page says the same thing.

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

`agentlog --version` prints the version.  Worth quoting in a bug report: this
tool reads session files written by somebody else's program, those formats
move, and "which agentlog" is the first question about a digest that came out
wrong.

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
pip install stillworks
stillworks tools
```

## License

MIT.  Copyright (c) 2026 stillworks contributors.
