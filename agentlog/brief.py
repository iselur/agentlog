"""The day, reported the way a teammate reports it at standup.

The digest answers "what happened": files, commands, errors, the prompt you
typed.  That is an activity log, and an activity log is not a report.  Nobody
answers "what did you get done today?" by reading out their shell history, and
nobody wants their own question read back to them either -- they already know
what they asked for; what they do not know is whether it is finished.

So this view reports each project against the goal declared for it with
``agentlog goal``: what was wanted and why, what actually happened, what is
still open, and what looks worth doing next.  Every goal carries one of four
marks -- done, in progress, failed, not started -- and what is blocked on the
reader themselves is pulled out into its own "Waiting on you" section.  Work
with no declared goal is still reported, just never judged -- a verdict needs
something to be a verdict *against*.

Two kinds of work go into the page, and the split between them is the whole
design:

**Counting is done here, in code.**  Sessions, tokens, hours, projects,
commits, pushes, releases, what failed and stayed failed, what compaction cost.
Every number printed on the page is computed from the transcripts by the
functions below, and no number is ever taken from the model.  A report whose
figures were guessed is worse than no report, because it reads exactly the
same.

**The prose is written by a model.**  "The cause is named but the fix never
landed" is a judgement, and there is no arithmetic for it.  The model is given
the facts and each project's declared goal, and it answers one paragraph per
project plus a status word -- and the status word is only trusted as far as
the evidence goes:

- ``done`` is demoted to ``in progress`` unless the transcripts hold a
  receipt -- a commit, a push, a merge, a release, a passing suite.  A
  model's opinion that something is finished is not evidence that it is.
- whether a project *has* a goal is read from the goal store, never from the
  model, so a project with no goal gets the undecided mark whatever the model
  claims, and a project with one is always shown what it was.  ``not
  started`` -- a goal on the books whose directory no session visited -- is
  read the same way, from the store and the logs alone.
- a sentence that states a tally this page computes for itself is dropped
  rather than printed, because a made-up figure in prose sits an inch from a
  real one and reads the same.

If no model can be reached the report still prints -- the prose goes missing,
the goals and the facts do not.  See ``asking_a_model.NoModel``.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import clock
from .asked import pick_ask
from .asking_a_model import NoModel
from .asking_a_model import ask as ask_a_model
from .render import (_busiest_hour, _period_phrase, active_seconds,
                     compaction_note, group_by_project, shortened)
from .terminal import block as safe_for_terminal
from .which_file import as_shown

WIDTH = 80

#: How much of the day's evidence one project is allowed to contribute to the
#: prompt.  A brief is built from a day that can hold thousands of commands,
#: and the model needs the shape of the work rather than all of it.
_PER_PROJECT = 14

#: Prompts are read by the model to work out what the work was *for*, and are
#: never printed.  This is the line that used to be the digest's `asked` row,
#: and taking it off the page is the point of this view.
_ASKS_PER_PROJECT = 2

#: How much of a declared goal rides in the prompt.  The declaration is capped
#: at 2000 characters already; this is the second, tighter door, because the
#: prompt carries every project's goal at once.
_GOAL_IN_PROMPT = 400


# ---------------------------------------------------------------------------
# Outcomes -- the things a session finished, rather than the things it did
# ---------------------------------------------------------------------------
#
# A transcript records activity, and activity is a poor witness: a thousand
# commands can leave nothing behind, and one can ship a release.  What survives
# a session is a commit, a push, a tag, a published package, a passing suite.
# Those are the events worth reporting, and unlike a count they are checkable.
#
# The patterns below are deliberately narrow.  A command that is *nearly* a
# release is not a release, and a timeline that includes near-misses is a
# timeline nobody can trust.  Anything unmatched is simply not an outcome; it
# is still counted among the commands, where a count belongs.

#: Where a program name has to sit for it to be a program that ran: the start
#: of the line, after a shell separator, or after one of the words that wrap a
#: command.  Optionally behind a path, because a virtualenv's build tool is
#: spelled `/home/you/.venv/bin/pyproject-build`.
#:
#: Without this, ``grep -n 'git commit' notes.md`` is a commit and
#: ``rg pytest`` is a test run: the words appear, in a command, and matching on
#: the words alone cannot tell the difference between running something and
#: talking about it.  A report that invents outcomes is worse than one that
#: misses them, so the match is anchored rather than widened.
_RUNS = (r"(?:^\s*|[\n;&|()]+\s*|\$\(\s*|`\s*"
         r"|\b(?:sudo|nohup|time|env|xargs|command)\s+)(?:\S*/)?")


def _when_run(pattern: str) -> "re.Pattern[str]":
    return re.compile(_RUNS + "(?:" + pattern + ")")


_OUTCOMES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("committed", _when_run(r"git\s+(?:-C\s+\S+\s+)?commit\b")),
    ("pushed", _when_run(r"git\s+(?:-C\s+\S+\s+)?push\b")),
    ("tagged", _when_run(r"git\s+(?:-C\s+\S+\s+)?tag\s+\S")),
    ("merged", _when_run(r"git\s+merge\b|gh\s+pr\s+merge\b")),
    ("opened a pull request", _when_run(r"gh\s+pr\s+create\b")),
    ("published", _when_run(
        r"twine\s+upload\b|npm\s+publish\b|cargo\s+publish\b|"
        r"gh\s+release\s+create\b")),
    ("built", _when_run(
        r"pyproject-build\b|python3?\s+-m\s+build\b|docker\s+build\b|"
        r"npm\s+run\s+build\b|make\s+build\b")),
    ("ran the tests", _when_run(
        r"pytest\b|python3?\s+-m\s+unittest\b|npm\s+(?:run\s+)?test\b|"
        r"cargo\s+test\b|go\s+test\b")),
    ("installed it", _when_run(
        r"pipx?\s+install\b|pipx\s+(?:re)?install\b|npm\s+i(?:nstall)?\b")),
)

#: The subject of a commit, when one was written on the command line.  This is
#: an engineer saying what they just finished, in their own words, already on
#: disk -- the single most useful sentence a transcript contains.
_COMMIT_SUBJECT = re.compile(
    r"""commit\b[^\n]*?-m\s*(['"])(?P<subject>.+?)\1""", re.DOTALL)


def _first_line(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return " ".join(line.split())


def outcomes_of(session: Dict) -> List[str]:
    """What this session finished, as short phrases, in the order they happened.

    Commands only.  A file written is not an outcome -- a session that edits
    forty files and commits none has finished nothing, and saying otherwise is
    the flattery that makes a report useless.
    """
    out: List[str] = []
    for cmd in session.get("commands") or []:
        # Read as written, newlines and all.  Flattening first would join a
        # commit body onto its subject line, and the subject is the sentence
        # worth printing; the patterns are whitespace-tolerant already.
        text = str(cmd)
        for label, pattern in _OUTCOMES:
            if not pattern.search(text):
                continue
            if label == "committed":
                found = _COMMIT_SUBJECT.search(text)
                subject = _first_line(found.group("subject")) if found else ""
                out.append("committed: " + subject if subject else "committed")
            else:
                out.append(label)
            break
    return out


def _stuck(session: Dict, limit: int = 3) -> List[str]:
    """Failures worth reporting: the last thing tried, not every attempt.

    A command that failed and was then run again successfully is an engineer
    working, not a problem, and a report that lists both wastes the reader on
    the one that no longer matters.  What is kept is the tail of the failures,
    which is the closest a transcript comes to "still broken when I stopped".
    """
    failures = [_first_line(str(f)) for f in (session.get("failed_cmds") or [])]
    seen = []
    for failure in reversed(failures):
        if failure and failure not in seen:
            seen.append(failure)
        if len(seen) >= limit:
            break
    return seen


# ---------------------------------------------------------------------------
# Facts -- the half of the page a model never touches
# ---------------------------------------------------------------------------


class Facts(object):
    """Everything countable about one project's day.

    A plain object rather than a dict because every field is read by name in
    two places, and a typo in a dict key is a silently missing number on a
    report -- which is the one failure this view cannot afford.
    """

    def __init__(self, name: str, sessions: List[Dict]):
        self.name = name
        self.sessions = sessions
        self.seconds = active_seconds(sessions)
        self.tokens_in = sum(s.get("tokens_in") or 0 for s in sessions)
        self.tokens_out = sum(s.get("tokens_out") or 0 for s in sessions)
        self.files = sorted({f for s in sessions
                             for f in (s.get("files_written") or [])})
        self.commands = sum(len(s.get("commands") or []) for s in sessions)
        self.errors = sum(s.get("errors") or 0 for s in sessions)
        self.outcomes = [o for s in sessions for o in outcomes_of(s)]
        self.stuck = [f for s in sessions for f in _stuck(s)]
        self.recaps = [text for s in sessions
                       for _at, text in (s.get("recaps") or [])]
        self.asks = [a for s in sessions
                     for a in ((s.get("asks") or [])[:_ASKS_PER_PROJECT])]
        # The directories the sessions ran in, kept so a goal -- which is
        # declared in a directory, not for a display name -- can find its way
        # to the project it belongs to.
        self.paths = sorted({str(s.get("project") or s.get("project_name")
                                 or "") for s in sessions} - {""})

    def counted(self) -> str:
        """The one line of figures that hangs under a project."""
        parts = ["{} session{}".format(len(self.sessions),
                                       "" if len(self.sessions) == 1 else "s"),
                 clock.duration(self.seconds)]
        if self.tokens_in or self.tokens_out:
            parts.append("{} tokens".format(
                _compact_number(self.tokens_in + self.tokens_out)))
        if self.files:
            parts.append("{} file{} edited".format(
                len(self.files), "" if len(self.files) == 1 else "s"))
        if self.errors:
            parts.append("{} error{}".format(
                self.errors, "" if self.errors == 1 else "s"))
        return " · ".join(parts)


def _compact_number(n: int) -> str:
    """`1.2M`, `84k`, `912`.

    A brief is read at a glance and `1,238,004` is not glanceable; the digest
    prints exact figures and this one prints readable ones, which is the
    difference between a report and a ledger.
    """
    if n >= 1_000_000:
        return "{:.1f}M".format(n / 1_000_000).replace(".0M", "M")
    if n >= 1_000:
        return "{:.0f}k".format(n / 1_000)
    return str(n)


def facts_by_project(sessions: List[Dict]) -> "Dict[str, Facts]":
    """One :class:`Facts` per project, keyed by the name shown in the digest.

    Two directories can share a display name -- a checkout and its worktree, or
    the same repository cloned twice -- and the model refers to a project by
    that name and nothing else.  So they are rolled together here rather than
    one of them quietly replacing the other in the dict, which would drop a
    project's whole day on the floor while the page went on looking complete.
    """
    merged: "Dict[str, List[Dict]]" = {}
    for group in group_by_project(sessions):
        name = group.get("name") or "(unknown)"
        merged.setdefault(name, []).extend(group.get("sessions") or [])
    return {name: Facts(name, members) for name, members in merged.items()}


def _goal_for(facts: Facts, goals: "Dict[str, dict]") -> Optional[dict]:
    """The declared goal this project's work was steered by, if any.

    Goals are keyed by the real path they were declared in; a project here is
    one or more directories rolled up under a display name.  Where more than
    one of them declared a goal, the newest declaration wins -- same rule as
    the store itself.
    """
    best: Optional[dict] = None
    for path in facts.paths:
        try:
            record = goals.get(os.path.realpath(path))
        except ValueError:
            record = None
        if record and (best is None
                       or (record.get("set_at") or 0)
                       > (best.get("set_at") or 0)):
            best = record
    return best


# ---------------------------------------------------------------------------
# The question put to a model
# ---------------------------------------------------------------------------

_FORMAT = """\
Answer with nothing but blocks of lines in this format, one block per project:

PROJECT: <a project name from the evidence, exactly as spelled>
STATUS: <done | in progress | failed | none>
SAID: <one sentence of the report>
SAID: <the next sentence; repeat SAID as needed, at most six per project>
WAITING: <what needs the person themselves, one line -- only if something does>

Rules:
- Report like a teammate at standup, in plain prose addressed to the person
  the work was for: what they wanted, what actually happened, what is still
  open, then what you would do next.
- Where a goal is declared, open with what they wanted and why, taken from
  the declaration itself (a goal may give its reason after "Why:").  Never
  invent a reason the declaration does not state.
- STATUS is done only when the goal's own definition of done is met and the
  evidence holds the receipts -- a commit, a merge, a push, a release, a
  passing suite.  in progress when some of it landed and a gap remains: say
  the gap.  failed when the attempt ended broken: say how it ended.  none
  for a project with no declared goal.
- WAITING is only for what is blocked on the person -- a decision, an
  approval, access, an answer to a question the work ended on.  A next step
  an agent could take is not WAITING.  Leave the line out when nothing is.
- A prediction is not a result.  State what shipped as fact; state what you
  expect to follow as your guess, in so many words.  A next step is a
  suggestion and is worded as one.
- Write no counts of sessions, tokens, projects, files, commands, errors,
  hours or minutes.  They are added afterwards from the transcripts and
  yours would be ignored.
- Skip a project with no goal and nothing finished; those are rolled into
  one line afterwards.  A goalless project whose work still mattered gets
  STATUS: none and a sentence or two on what happened.
- Plain language, no jargon, no markdown, no preamble, no sign-off."""


def _evidence(facts: "Dict[str, Facts]",
              goals: "Dict[str, dict]") -> str:
    """The day, written down small enough to ask about."""
    lines = []
    for name, f in facts.items():
        lines.append("## project: {}".format(name))
        record = _goal_for(f, goals)
        if record:
            lines.append("  declared goal: " + shortened(
                " ".join(str(record.get("goal")).split()), _GOAL_IN_PROMPT))
        if f.asks:
            lines.append("  was asked for: "
                         + " | ".join(shortened(a, 160) for a in f.asks))
        if f.outcomes:
            lines.append("  finished: "
                         + "; ".join(f.outcomes[:_PER_PROJECT]))
        if f.recaps:
            lines.append("  the agent's own notes: "
                         + " | ".join(shortened(r, 300) for r in f.recaps[:4]))
        if f.files:
            lines.append("  edited: " + ", ".join(
                as_shown(p) for p in f.files[:_PER_PROJECT]))
        if f.stuck:
            lines.append("  still failing at the end: "
                         + "; ".join(shortened(s, 120) for s in f.stuck[:4]))
        if not (f.outcomes or f.files or f.stuck):
            lines.append("  nothing was written or committed here")
    return "\n".join(lines)


def the_question(facts: "Dict[str, Facts]", period_label: str,
                 goals: "Optional[Dict[str, dict]]" = None) -> str:
    """The whole prompt, so a test can read it without a model running."""
    return (
        "You are writing a short status report for the person whose work this "
        "was. They know what they asked for; they want to know what came of "
        "it. Some projects declare a goal -- what the work is for and what "
        "done looks like; judge those projects against their goal and "
        "nothing else.\n\n"
        "Here is the evidence from their agent transcripts for {}.\n\n"
        "{}\n\n{}\n".format(period_label, _evidence(facts, goals or {}),
                            _FORMAT))


# ---------------------------------------------------------------------------
# The answer, read back
# ---------------------------------------------------------------------------


#: The words this page computes for itself.  A model sentence that puts a
#: number in front of one of them is stating a tally, and a tally in prose sits
#: an inch from the real one and looks exactly as authoritative -- so the
#: sentence is dropped rather than printed beside a figure that contradicts it.
#:
#: Deliberately only these words -- the figures the footer and the tally lines
#: print.  "Released 0.3.0", "merged with 214 tests green" and "2 commits
#: landed" are numbers a model read off the evidence, not counts this page
#: computes, and a receipt with a figure in it is exactly the kind of sentence
#: the report exists to carry.
#: The gap words are word-shaped on purpose: "5; the session ended" is a
#: number and a unit in the same sentence, not a tally of sessions, and
#: letting the gap cross punctuation was eating exactly that kind of line.
_A_TALLY = re.compile(
    r"\b\d(?:[\d,.]*\d)?\s*(?:[\w'-]+\s+){0,2}"
    r"(?:session|token|project|file|error|command|"
    r"hour|minute)s?\b", re.I)


def _states_a_tally(text: str) -> bool:
    return bool(_A_TALLY.search(text))


#: The status words a model may claim, normalized to the ones the page
#: prints.  Anything else reads as no claim.  "partly" and "ongoing" are
#: accepted because a model told "in progress" will reach for its synonyms.
_STATUSES = {"done": "done", "in progress": "in progress",
             "ongoing": "in progress", "partly": "in progress",
             "failed": "failed", "none": "none"}


class Report(object):
    """One project's paragraph: the status the model claims, and what it said.

    The claim is what it is -- a claim.  Whether it survives onto the page is
    decided in :func:`_judged`, against the receipts, not here.
    """

    def __init__(self, project: str):
        self.project = project
        self.status = ""
        self.said: List[str] = []
        self.waiting: List[str] = []


def read_the_answer(text: str, known: Sequence[str]) -> List[Report]:
    """Turn a model's reply into reports, ignoring anything else it said.

    Lenient on purpose.  A CLI that wraps its answer in a sentence of its own,
    or numbers the blocks, or uses a dash, should not cost a person their
    report; every line that is not one of the three keywords is dropped.

    Strict in exactly two places.  A PROJECT name that does not match one we
    counted drops its whole block, so a made-up project can never carry
    made-up claims onto the page.  And a sentence that states a tally this
    page computes for itself is dropped whole: the prompt asks for no such
    numbers, and a model that writes one anyway has written the one thing on
    this page nobody checked.
    """
    reports: List[Report] = []
    by_name: "Dict[str, Report]" = {}
    lookup = {name.lower(): name for name in known}
    current: Optional[Report] = None
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*0123456789. ").strip()
        head, _, rest = line.partition(":")
        key, value = head.strip().upper(), rest.strip()
        if key == "PROJECT":
            match = lookup.get(value.lower())
            if not match:
                current = None
                continue
            # Two blocks for one project are one report: the page shows each
            # project once, so a model that split its answer is merged rather
            # than printed twice.
            current = by_name.get(match)
            if current is None:
                current = Report(match)
                by_name[match] = current
                reports.append(current)
        elif current is None:
            continue
        elif key == "STATUS":
            claimed = _STATUSES.get(value.rstrip(" .,").lower())
            if claimed:
                current.status = claimed
        elif key == "SAID" and value and not _states_a_tally(value):
            current.said.append(safe_for_terminal(value))
        elif key == "WAITING" and value and not _states_a_tally(value):
            current.waiting.append(safe_for_terminal(value))
    return [r for r in reports if r.said or r.waiting]


def _judged(claimed: str, has_goal: bool, has_receipts: bool) -> str:
    """The status that reaches the page, gated by what the code knows.

    Two facts here are the code's, not the model's: whether a goal was
    declared (read from the goal store) and whether the transcripts hold a
    receipt (a commit, a push, a merge, a release, a suite run).  A model may
    only judge where there is a goal to judge against, and may only say done
    where something checkable survived the session.  Everything else is the
    undecided mark, which is a shape, not a verdict.
    """
    if not has_goal:
        return ""
    if claimed == "done" and not has_receipts:
        return "in progress"
    if claimed in ("done", "in progress", "failed"):
        return claimed
    return ""


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

_FLAG = {"done": "✔ done", "in progress": "◐ in progress",
         "failed": "✘ failed", "not started": "○ not started", "": "·"}


def _wrapped(text: str, first: str, after: str) -> List[str]:
    """`text` under a label, wrapped to the page rather than cut.

    A report line is a sentence and cutting it at 80 cells loses the half that
    says what was done.  The digest cuts because its rows are a table; this is
    prose, so it wraps.
    """
    room = WIDTH - len(after)
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > room:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    if not lines:
        return []
    return [first + lines[0]] + [after + rest for rest in lines[1:]]


def _headline(sessions: List[Dict], period_label: str,
              facts: "Dict[str, Facts]", goals_in_play: int) -> str:
    parts = [clock.duration(active_seconds(sessions)) + " of agent time"]
    if goals_in_play:
        parts.append("{} goal{} in play".format(
            goals_in_play, "" if goals_in_play == 1 else "s"))
    else:
        parts.append("{} session{}".format(
            len(sessions), "" if len(sessions) == 1 else "s"))
        parts.append("{} project{}".format(
            len(facts), "" if len(facts) == 1 else "s"))
    return "{} · {}".format(_period_phrase(period_label), " · ".join(parts))


def _block_header(status: str, name: str, goal: Optional[dict]) -> str:
    """`  ✔ done — name — "the goal"`, or `  · name — no goal declared.`

    The goal is quoted, never paraphrased, and gives way first when the line
    is long: one whole name and a shortened quotation beat fragments of both.
    """
    flag = _FLAG.get(status, "·")
    if goal is None:
        return safe_for_terminal(
            "  {} {} — no goal declared.".format(flag, name))
    # The undecided mark is one glyph and reads better sitting directly on
    # the name; the worded flags need the dash to keep flag and name apart.
    prefix = ("  {} {} — ".format(flag, name) if flag == "·"
              else "  {} — {} — ".format(flag, name))
    room = max(8, WIDTH - len(prefix) - 2)
    quote = shortened(_first_line(str(goal.get("goal"))), room)
    return safe_for_terminal('{}"{}"'.format(prefix, quote))


def _untouched_goals(goals: "Dict[str, dict]",
                     facts: "Dict[str, Facts]") -> List[dict]:
    """Goals on the books that no session visited this period.

    Read from the goal store, never from the model: a declared goal whose
    directory shows up in none of the period's transcripts was not started,
    and that is a fact about the store and the logs, not a judgement.  Newest
    declaration first, because the goal most recently set and then not picked
    up is the one most worth being reminded of.
    """
    covered = set()
    for f in facts.values():
        for path in f.paths:
            try:
                covered.add(os.path.realpath(path))
            except ValueError:
                covered.add(path)
    out = [record for path, record in goals.items() if path not in covered]
    out.sort(key=lambda r: -(r.get("set_at") or 0))
    return out


def _footer(sessions: List[Dict], facts: "Dict[str, Facts]") -> List[str]:
    """The plain figures, after the prose and a rule, all computed here."""
    lines = ["  " + "─" * (WIDTH - 2)]
    by_source: "Dict[str, int]" = {}
    for s in sessions:
        src = s.get("source") or "?"
        by_source[src] = by_source.get(src, 0) + 1
    row = ["{} session{}".format(len(sessions),
                                 "" if len(sessions) == 1 else "s")]
    if len(by_source) > 1:
        row.append(", ".join("{} {}".format(n, src)
                             for src, n in sorted(by_source.items())))
    busiest = _busiest_hour(sessions)
    if busiest:
        row.append("busiest " + busiest)
    lines.append("  " + " · ".join(row))
    files = len({f for fx in facts.values() for f in fx.files})
    commands = sum(fx.commands for fx in facts.values())
    errors = sum(fx.errors for fx in facts.values())
    tokens = sum(fx.tokens_in + fx.tokens_out for fx in facts.values())
    row = []
    if files:
        row.append("{} file{} edited".format(files,
                                             "" if files == 1 else "s"))
    if commands:
        row.append("{} command{}".format(commands,
                                         "" if commands == 1 else "s"))
    if errors:
        row.append("{} error{}".format(errors, "" if errors == 1 else "s"))
    if tokens:
        row.append("{} tokens".format(_compact_number(tokens)))
    if row:
        lines.append("  " + " · ".join(row))
    cost = compaction_note(sessions)
    if cost:
        lines.append("  " + cost)
    return lines


def _rest_line(rest: List[Facts]) -> List[str]:
    """The projects nobody reported on, rolled into one honest line.

    A fleet's day is mostly short sessions -- reviewer gates, small fixes --
    and a report that reprimanded each one for having no goal would be twenty
    lines of nagging.  One line says what they amounted to and moves on.
    """
    count = sum(len(f.sessions) for f in rest)
    spent = sum(f.seconds for f in rest)
    where = (rest[0].name if len(rest) == 1
             else "{} projects".format(len(rest)))
    text = ("Plus {} session{} {} {}, {} total — no goals declared there."
            .format(count, "" if count == 1 else "s",
                    "in" if len(rest) == 1 else "across", where,
                    clock.duration(spent)))
    return _wrapped(text, "  ", "  ")


def render_brief(sessions: List[Dict], period_label: str,
                 ask: Optional[Callable[[str], str]] = None,
                 goals: "Optional[Dict[str, dict]]" = None) -> str:
    """The report, as text.

    ``ask`` is the seam.  It takes the prompt and returns what the model said;
    the default reaches the ``claude`` command through
    :mod:`agentlog.asking_a_model`, and the tests pass a function that returns
    a fixed string, so every line of this module is exercised without a model
    and without a network.

    ``goals`` is what :func:`agentlog.goal.everything_declared` read from the
    goal store -- real paths to declaration records.  The caller reads the
    store so this module never touches the filesystem, which is also what
    keeps the tests hermetic.
    """
    if not sessions:
        return "no sessions found for: {}".format(period_label)

    goals = goals or {}
    facts = facts_by_project(sessions)
    declared = {name: _goal_for(f, goals) for name, f in facts.items()}
    untouched = _untouched_goals(goals, facts)
    in_play = (sum(1 for record in declared.values() if record)
               + len(untouched))
    lines = [_headline(sessions, period_label, facts, in_play), ""]

    ask = ask or ask_a_model
    try:
        answer = ask(the_question(facts, period_label, goals))
        reports = {r.project: r for r in read_the_answer(answer, list(facts))}
        trouble = ""
    except NoModel as why:
        reports, trouble = {}, str(why)

    waiting: List[Tuple[str, str]] = []
    if reports or (not trouble and in_play):
        # Projects with a goal first, busiest first; then the goalless ones
        # somebody still reported on.  A goal-holding project the model went
        # quiet about is not allowed to vanish -- its goal and its figures
        # print anyway, prose or no prose.
        def _ordered(names: List[str]) -> List[str]:
            return sorted(names, key=lambda n: -facts[n].seconds)

        with_goal = _ordered([n for n in facts if declared[n]])
        goalless = _ordered([n for n in facts
                             if not declared[n] and n in reports])
        for name in with_goal + goalless:
            f, record = facts[name], declared[name]
            report = reports.get(name)
            status = _judged(report.status if report else "",
                             record is not None, bool(f.outcomes))
            lines.append(_block_header(status, name, record))
            if report and report.said:
                lines.extend(_wrapped(" ".join(report.said),
                                      "      ", "      "))
            lines.append("      " + shortened(f.counted(), WIDTH - 6))
            lines.append("")
            if report:
                waiting.extend((name, w) for w in report.waiting)
        rest = [facts[n] for n in facts
                if n not in with_goal and n not in goalless]
        if rest:
            lines.extend(_rest_line(rest))
            lines.append("")
    else:
        lines.extend(_the_facts_alone(facts, declared, trouble))

    # Declared and then never picked up: a fact about the store and the logs,
    # so it prints with or without a model.
    for record in untouched:
        cwd = str(record.get("cwd") or "")
        name = os.path.basename(cwd.rstrip("/")) or cwd or "?"
        lines.append(_block_header("not started", name, record))
        lines.append("")

    # What is blocked on the reader, pulled out of the paragraphs and put
    # where a skimming eye lands.  Only when a model reported: this section
    # is inference, and silence from no-model is not "nothing needs you".
    if not trouble and reports:
        lines.append("  Waiting on you")
        if waiting:
            for name, what in waiting:
                lines.extend(_wrapped("{} — {}".format(name, what),
                                      "      ", "      "))
        else:
            lines.append("      nothing, as far as the transcripts show.")
        lines.append("")

    lines.extend(_footer(sessions, facts))
    return "\n".join(lines).rstrip() + "\n"


def _the_facts_alone(facts: "Dict[str, Facts]",
                     declared: "Dict[str, Optional[dict]]",
                     trouble: str) -> List[str]:
    """What prints when no model answered.

    The report degrades rather than disappearing.  A person who wanted to know
    what happened today still finds out -- the goals, the receipts, the
    figures; what they lose is the prose tying it together, and they are told
    that is what they lost and why.
    """
    lines = []
    if trouble:
        lines.append("(no summary: {})".format(trouble.splitlines()[0]))
        lines.append("")
    for name, f in sorted(facts.items(),
                          key=lambda kv: kv[1].seconds, reverse=True):
        lines.append(_block_header("", name, declared.get(name)))
        lines.append("      " + shortened(f.counted(), WIDTH - 6))
        if f.outcomes:
            lines.extend(_wrapped("; ".join(f.outcomes[:6]),
                                  "      done: ", "      "))
        if f.stuck:
            lines.extend(_wrapped("; ".join(f.stuck[:3]),
                                  "      still failing: ", "      "))
        goal = pick_ask(f.asks)
        if goal and not f.outcomes and not declared.get(name):
            lines.extend(_wrapped(shortened(goal, 200),
                                  "      asked for: ", "      "))
        lines.append("")
    return lines
