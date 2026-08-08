# Brief: make agentlog answer "what did you build today?"

Shipped as `agentlog --brief` in 0.4.0. This is the record of what was decided
and why, including the two proposals that were thrown out along the way.

## The problem, stated as the user states it

> "If I would ask a group of engineers what they have built today, I definitely
> would not receive just the technical terms. I would receive a clear answer."

> "This is what the goal we had. This is what we've done. This is what is
> remaining. This is what went wrong."

> "I don't want to quote what task I ask to do. I want it rather to say, hey.
> Today, I work on three things, one, two, three. This is what I've done. One,
> two, three. … Same way as an engineer would report to product owner."

Today's digest, for the window where agentlog 0.3.0 was actually shipped:

```
  r102-bench   41m 18s   11 files edited · 235 commands · 17 errors
      asked    "lets get back to the ideas we discussed earlier…"
      edited   …/agentlog/render.py, …/agentlog/parser.py, test_privacy_claims…
      failed   read bc8uovkr3.txt  (2x)
```

What actually happened in that window: **agentlog 0.3.0 and stillworks 0.2.1
were released** — a new module, a rewritten privacy promise, 3,132 tests green,
two repos pushed. None of that is on the page. The page is a keystroke counter.

## The diagnosis

agentlog reads one source — the agent's own transcript — and a transcript only
knows *activity*. Every field on the page is a count of things the agent did.
Nothing on the page is a thing the agent **finished**.

A count is also not an answer. Eleven sessions across four directories were one
piece of work, and no amount of arithmetic over the transcript will say so.
Grouping them and naming the group is a judgement.

## Two proposals that were thrown out

**Read git.** The first version of this brief proposed reading `git log` for the
window and printing commit subjects as the "done" rows, with `git status` as the
"left" rows. Sol refused it, and was right: *"Git can enrich that timeline; it
must not define it."* Most of a day's work is not committed — a release that was
built, tested, and published leaves one commit and four hours of evidence. A
project that is not a repo would have no "done" row at all, which reads as
having done nothing.

**Never call a model.** The house promise was stdlib-only, no network, no model
calls, and the brief originally treated that as fixed — agentlog would *quote*,
never *paraphrase*. The user overrode it explicitly: *"I don't care if it would
require model calls or not. It's totally fine."* Naming the day's work is a
judgement, and refusing to make one is why the old page was a counter.

## What shipped

A page in the shape a product owner asked for: the day's headline, then the
things worked on, each with what got done, what didn't, and where.

```
today · 3h 02m · 24 sessions · 15 projects · 98M tokens

Four things:

  1. R102 benchmark kill-test across configs
     done      Fixes for the harness command paths and model names were
               committed, pushed and merged.
     not done  Two configs still hit container bugs, and the fix for them is on
               a repeat worker attempt awaiting merge and a full re-run.
     r102-bench, val, relay · 12 sessions · 2h 49m · 82.6M tokens · 45 files
```

### The split: counting here, naming there

**Counting is done in code.** Every figure on the page — the headline and the
tally under each theme — is computed from the sessions the model attached to
that theme.

**Grouping and naming is done by a model.** It is told in the prompt not to
write figures at all, and a sentence that states one anyway is dropped rather
than printed, because a made-up figure sits an inch from a real one and reads
the same. Project names it invents are dropped before they can carry a tally.

So a model that miscounts changes the wording of the page and never its
arithmetic. That is the whole design.

### Outcome events, not activity

The evidence handed to the model is not a command log. It is the set of things
that *finished*: committed, pushed, tagged, merged, opened a pull request,
published, built, ran the tests, installed it. Each is recognised only in
command position — `grep -n 'git commit' notes.md` is not a commit — and a
commit contributes its subject line, never its body.

### The compaction line, promoted

`compacted 155x in 3 sessions · 6h 17m spent on it, 15,391,856 tokens dropped`
now sits under the report rather than in small print. Six hours of a working
day spent re-reading context is a finding, not a footnote.

### Noise folded

Six `relay-review-<hash>` sandboxes running one identical machine-written prompt
used to be six of eight visible rows. The model groups them into one theme, and
the tally line sheds whole names — `relay-review-0, 6 others` — so the figures
always survive the width.

## The promise that changed

`--brief` hands the day's evidence — project names, the prompts you typed, shell
commands, file paths, the agent's own recaps — to the `claude` command already
installed on your machine. That evidence leaves the machine.

This is confined by test, not by intention:

- `agentlog/asking_a_model.py` is the only module in the package allowed to run
  another program at all (`tests/test_privacy_claims.py`).
- Across the whole family wheel, it is the only module that may both start a
  program and name an agent (`stillworks/tests/test_family_claims.py`).
- Every other mode is asserted to send nothing, with a fake model whose stdin is
  captured and checked.
- `--brief` cannot be combined with `--html`, `--md`, `--json`, `--sessions`,
  `list` or `show`: a document you keep must not quietly become one that was
  written by a model.
- With no `claude` on the machine the page still prints, from the facts alone,
  and says what is missing.

## Still open

- A fast single-file mode (`--file <path>`), so a `PreCompact` hook can produce
  a handover inside its ~60s timeout. Scanning the whole home takes ~3 minutes.
- `--per-day` over a longer window.
