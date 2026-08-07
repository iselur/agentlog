"""The two lines of output the README quotes, produced by the code that quotes them.

The README shows what compaction looks like:

    context  compacted 98x — 3h 59m spent on it, 9,944,222 tokens dropped
    compacted 127x in 6 sessions · 4h 54m spent on it, 13,239,126 tokens dropped

Both are real output, not illustrations — the first is one session, the second
is a week.  That is the reason they are worth showing and also the reason they
rot: the next change to the wording leaves them behind, and a README that quotes
output the tool no longer produces is worse than one that quotes none, because
the reader has no way to tell which of the two they are looking at.

So this reads the numbers out of the README and asks the renderer to produce
those lines from a session shaped to match.  Nothing here duplicates the format
string; if the format changes, the failure names the README line to fix.

Only the count, the duration and the dropped total are read back.  How they are
spread over the individual compactions is not in the line and does not need to
be: the line is a total, and a fixture that happened to split it differently
would still have to render the same.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog import render

README = os.path.join(_ROOT, "README.md")

# "3h 59m", "4m 34s", "45s" — whatever _fmt_duration writes, read back.
_DURATION = re.compile(r"(?:(\d+)h )?(?:(\d+)m )?(?:(\d+)s )?", re.ASCII)

_SHOW_LINE = re.compile(
    r"^context\s+compacted (\d+)x — (.+?) spent on it, ([\d,]+) tokens dropped$",
    re.MULTILINE)
_DIGEST_LINE = re.compile(
    r"^compacted (\d+)x in (\d+) sessions · (.+?) spent on it, ([\d,]+) tokens dropped$",
    re.MULTILINE)


def readme() -> str:
    with open(README, encoding="utf-8") as handle:
        return handle.read()


def seconds(text: str) -> float:
    """Back out of _fmt_duration's own output, so the two agree by construction."""
    hours, minutes, secs = _DURATION.match(text + " ").groups()
    return (int(hours or 0) * 3600 + int(minutes or 0) * 60 + int(secs or 0))


def spread(count: int, duration_s: float, dropped: int):
    """`count` compactions whose totals are exactly what was asked for.

    Divided evenly with the remainder on the first one, because the totals are
    what the line reports and an even split that lost a token to rounding would
    fail this test for a reason that has nothing to do with the format.
    """
    each_drop, extra_drop = divmod(dropped, count)
    each_time, extra_time = divmod(duration_s, count)
    return [
        {"at": None, "trigger": "auto", "pre": 100000, "post": 10000,
         "dropped": each_drop + (extra_drop if i == 0 else 0),
         "duration_s": each_time + (extra_time if i == 0 else 0)}
        for i in range(count)
    ]


class TestTheREADMEStillShowsWhatItProduces(unittest.TestCase):
    def test_the_readme_quotes_both_lines_at_all(self):
        # Without this, deleting the examples would make the two tests below
        # vacuous rather than failing — they iterate over what they found.
        text = readme()
        self.assertTrue(_SHOW_LINE.search(text), "no `context  compacted` example")
        self.assertTrue(_DIGEST_LINE.search(text), "no digest compaction example")

    def test_the_show_example_is_what_show_would_print(self):
        for count, spent, dropped in _SHOW_LINE.findall(readme()):
            count, dropped = int(count), int(dropped.replace(",", ""))
            session = {"compactions": spread(count, seconds(spent), dropped)}
            self.assertEqual(
                render._fmt_compactions(session),
                f"compacted {count}x — {spent} spent on it, {dropped:,} tokens dropped",
                "README.md quotes output agentlog no longer produces")

    def test_the_digest_example_is_what_the_digest_would_print(self):
        for count, in_sessions, spent, dropped in _DIGEST_LINE.findall(readme()):
            count, in_sessions = int(count), int(in_sessions)
            dropped = int(dropped.replace(",", ""))
            # Dealt round-robin across the sessions, so every one of them has at
            # least one: the line reports how many sessions compacted, and a
            # session holding none of them is not one of those.
            everything = spread(count, seconds(spent), dropped)
            sessions = [{"compactions": everything[i::in_sessions]}
                        for i in range(in_sessions)]
            self.assertTrue(all(s["compactions"] for s in sessions))
            self.assertEqual(
                render.compaction_note(sessions),
                f"compacted {count}x in {in_sessions} sessions"
                f" · {spent} spent on it, {dropped:,} tokens dropped",
                "README.md quotes output agentlog no longer produces")


if __name__ == "__main__":
    unittest.main()
