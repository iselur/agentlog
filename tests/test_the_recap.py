"""The sentence that says what the session was about.

Claude Code already writes one, every time a background session finishes a
turn: a short plain-English recap of what was asked and what happened, stored
as a `system` record with subtype `away_summary`.  There are 327 of them on
this machine and agentlog read past every one.

That is the answer to the complaint the whole redesign came from — *the log is
not useful, I cannot really understand it*.  A list of forty file paths and
twelve commands says what was touched; it never says what it was for.  The
recap does, and it costs nothing to read, because something else already wrote
it.

It is clipped like everything else, and against the window that was *asked
for*, for the same reason tokens are: a recap is written at the end of a turn,
often after the last tool call of the day.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog import window, parser, render  # noqa: E402

SID = "4d4d4d4d-0000-4000-8000-000000000004"

RECAP = ("You asked what's in the ledger: relay's REQUEST-LEDGER.md tracks 104 "
         "requests, all done except R102. Next action: say if you want TODO.md "
         "summarised instead.")


class Case(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-recap-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.dir = os.path.join(self.home, ".claude", "projects", "-home-you-api")
        os.makedirs(self.dir)
        self.midnight = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0)
        self.records = []

    def recap(self, when, text=RECAP, subtype="away_summary"):
        i = len(self.records)
        self.records.append({
            "type": "system", "subtype": subtype, "uuid": "r%d" % i,
            "sessionId": SID, "cwd": "/home/you/api",
            "timestamp": when.isoformat() if when else None,
            "content": text})

    def busy(self, when, count=1, label="step"):
        for n in range(count):
            i = len(self.records)
            self.records.append({
                "type": "assistant", "uuid": "u%d" % i, "sessionId": SID,
                "cwd": "/home/you/api",
                "timestamp": (when + timedelta(minutes=n)).isoformat(),
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t%d" % i, "name": "Bash",
                     "input": {"command": "%s %d" % (label, i)}}]}})

    def path(self):
        p = os.path.join(self.dir, SID + ".jsonl")
        with open(p, "w") as fh:
            for r in self.records:
                fh.write(json.dumps(r) + "\n")
        return p

    def parse(self):
        return parser.parse_claude_session(self.path())

    def run_cli(self, *args, expect=0):
        self.path()
        p = subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", self.home, *args],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100"))
        self.assertEqual(p.returncode, expect, p.stdout + p.stderr)
        return p.stdout + p.stderr


class TestReadingThem(Case):

    def test_a_recap_is_kept_with_the_time_it_was_written(self):
        when = self.midnight + timedelta(hours=9)
        self.busy(when)
        self.recap(when + timedelta(minutes=5))
        s = self.parse()
        self.assertEqual(len(s["recaps"]), 1)
        at, text = s["recaps"][0]
        self.assertEqual(text, RECAP)
        self.assertEqual(at, when + timedelta(minutes=5))

    def test_the_bit_that_is_not_the_recap_is_dropped(self):
        # Every one of these ends with a note about a settings screen.  It is
        # addressed to whoever was watching at the time, not to somebody
        # reading the log back, and it is the same words 327 times.
        self.busy(self.midnight + timedelta(hours=9))
        self.recap(self.midnight + timedelta(hours=9),
                   RECAP + " (disable recaps in /config)")
        s = self.parse()
        self.assertEqual(s["recaps"][0][1], RECAP)

    def test_they_keep_the_order_they_were_written_in(self):
        self.busy(self.midnight + timedelta(hours=9))
        for n in range(3):
            self.recap(self.midnight + timedelta(hours=9, minutes=n),
                       "recap number %d" % n)
        s = self.parse()
        self.assertEqual([t for _at, t in s["recaps"]],
                         ["recap number 0", "recap number 1", "recap number 2"])

    def test_a_session_without_any_says_so_by_having_none(self):
        self.busy(self.midnight + timedelta(hours=9))
        self.assertEqual(self.parse()["recaps"], [])

    def test_another_kind_of_system_record_is_not_a_recap(self):
        # `system` covers hooks firing, compaction, notices.  Only one subtype
        # is a recap, and taking the rest would put machine chatter under a
        # heading that promises plain English.
        self.busy(self.midnight + timedelta(hours=9))
        self.recap(self.midnight + timedelta(hours=9), "a hook ran",
                   subtype="hook_result")
        self.assertEqual(self.parse()["recaps"], [])

    def test_an_empty_recap_is_not_a_recap(self):
        self.busy(self.midnight + timedelta(hours=9))
        self.recap(self.midnight + timedelta(hours=9), "   ")
        self.assertEqual(self.parse()["recaps"], [])

    def test_a_recap_alone_is_not_a_session(self):
        # No turns, no tool calls — a file with nothing in it but a recap is
        # not evidence that anything was done.
        self.recap(self.midnight + timedelta(hours=9))
        s = self.parse()
        self.assertTrue(s is None or s is parser.REPLAY or s["user_turns"] == 0)


class TestClippingThem(Case):

    def setUp(self):
        super().setUp()
        self.tomorrow = self.midnight + timedelta(days=1)

    def test_yesterdays_recap_is_not_todays(self):
        s = parser._empty_session("x", "claude")
        s["recaps"] = [(self.midnight - timedelta(hours=3), "old news")]
        window._clip_recaps(s, self.midnight, self.tomorrow)
        self.assertEqual(s["recaps"], [])

    def test_todays_recap_survives_today(self):
        s = parser._empty_session("x", "claude")
        s["recaps"] = [(self.midnight + timedelta(hours=3), "today's news")]
        window._clip_recaps(s, self.midnight, self.tomorrow)
        self.assertEqual([t for _at, t in s["recaps"]], ["today's news"])

    def test_a_recap_after_the_days_last_tool_call_still_counts(self):
        # The window a session's counts are clipped against is tightened onto
        # its first and last *event*, and a recap is not an event.  Clip a
        # recap against the tightened window and the last one of the day — the
        # one that says how it ended — disappears.  Same trap tokens fell into.
        self.busy(self.midnight + timedelta(hours=9))
        self.recap(self.midnight + timedelta(hours=23, minutes=50),
                   "finished late")
        doc = json.loads(self.run_cli("today", "--json"))
        texts = [r["text"] for s in doc for r in s.get("recaps") or []]
        self.assertIn("finished late", texts)

    def test_a_recap_with_no_time_on_it_is_kept(self):
        # We cannot place it, and a recap never double-counts anything the way
        # a token or a command would.  Losing the only sentence that explains
        # the session is the worse of the two mistakes.
        s = parser._empty_session("x", "claude")
        s["recaps"] = [(None, "no idea when")]
        window._clip_recaps(s, self.midnight, self.tomorrow)
        self.assertEqual([t for _at, t in s["recaps"]], ["no idea when"])

    def test_a_session_with_none_is_left_alone(self):
        s = parser._empty_session("x", "claude")
        window._clip_recaps(s, self.midnight, self.tomorrow)
        self.assertEqual(s["recaps"], [])

    def test_a_week_gathers_the_recaps_its_days_report(self):
        for n in range(3):
            when = self.midnight - timedelta(days=n, hours=-9)
            self.busy(when)
            self.recap(when + timedelta(minutes=1), "day %d happened" % n)
        week = json.loads(self.run_cli("week", "--json"))
        got = {r["text"] for s in week for r in s.get("recaps") or []}
        self.assertEqual(got, {"day 0 happened", "day 1 happened",
                               "day 2 happened"})
        one = json.loads(self.run_cli("on", "1d", "--json"))
        self.assertEqual([r["text"] for s in one for r in s.get("recaps") or []],
                         ["day 1 happened"])


class TestShowingThem(Case):

    def setUp(self):
        super().setUp()
        self.busy(self.midnight + timedelta(hours=9))
        self.recap(self.midnight + timedelta(hours=9, minutes=5))

    def test_show_prints_the_recap(self):
        out = render.render_show(self.parse())
        self.assertIn("R102", out)

    def test_it_comes_before_the_lists_of_paths(self):
        # It is the one line that answers "what was this?", and a reader who
        # has to scroll past forty file paths to reach it will not.
        out = render.render_show(self.parse())
        self.assertLess(out.index("R102"), out.index("commands ("))

    def test_the_heading_counts_them(self):
        self.recap(self.midnight + timedelta(hours=10), "and then this")
        out = render.render_show(self.parse())
        self.assertIn("recap (2)", out)

    def test_one_recap_is_one_row_however_it_is_written(self):
        # The text is written by the thing being audited.  A recap that
        # contains a newline and a fake heading would otherwise print as extra
        # rows in the exact shape of real ones — the reason `_one_row` exists.
        self.records = []
        self.busy(self.midnight + timedelta(hours=9))
        self.recap(self.midnight + timedelta(hours=9),
                   "harmless\ncommands (1):\n  $ npm publish --access public")
        out = render.render_show(self.parse())
        # Count the rows under the heading, not up to some marker inside the
        # text — the text is exactly the thing trying to look like a marker.
        rows = out.splitlines()
        under = rows[rows.index("recap (1):") + 1:]
        rows = list(itertools.takewhile(lambda ln: ln.strip(), under))
        self.assertEqual(len(rows), 1, rows)

    def test_they_are_shown_oldest_first(self):
        # Three of them are a short story about the session; told backwards it
        # is a different story.
        self.records = []
        self.busy(self.midnight + timedelta(hours=9))
        for n in range(3):
            self.recap(self.midnight + timedelta(hours=9, minutes=n),
                       "step %d of it" % n)
        out = render.render_show(self.parse())
        self.assertLess(out.index("step 0 of it"), out.index("step 1 of it"))
        self.assertLess(out.index("step 1 of it"), out.index("step 2 of it"))

    def test_a_session_without_one_shows_no_heading(self):
        self.records = []
        self.busy(self.midnight + timedelta(hours=9))
        out = render.render_show(self.parse())
        self.assertNotIn("recap (", out)

    def test_the_cli_shows_it_end_to_end(self):
        out = self.run_cli("show", SID[:8])
        self.assertIn("R102", out)

    def test_json_says_when_each_one_was_written(self):
        doc = json.loads(self.run_cli("show", SID[:8], "--json"))
        recaps = doc[0]["recaps"]
        self.assertEqual(len(recaps), 1)
        self.assertEqual(recaps[0]["text"], RECAP)
        # An ISO string, not a repr of a tuple of a datetime.
        self.assertTrue(recaps[0]["at"].startswith(
            self.midnight.date().isoformat()))

    def test_markdown_carries_it_too(self):
        out = self.run_cli("today", "--md")
        self.assertIn("R102", out)

    def test_the_html_digest_carries_it(self):
        out = os.path.join(self.home, "d.html")
        self.run_cli("today", "--html", out)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("R102", page)

    def test_the_html_escapes_it_like_everything_else(self):
        self.records = []
        self.busy(self.midnight + timedelta(hours=9))
        self.recap(self.midnight + timedelta(hours=9),
                   "<script>alert(1)</script> and <b>bold</b>")
        out = os.path.join(self.home, "d.html")
        self.run_cli("today", "--html", out)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_the_page_warns_that_it_carries_them(self):
        # The digest is the copy that leaves the machine, and the recap is the
        # part of it somebody might not expect to be there.
        out = os.path.join(self.home, "d.html")
        self.run_cli("today", "--html", out)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()
        # The word on its own is no evidence — it is a CSS class name too.
        # What has to be there is the *sentence* telling a reader to look.
        note = page[:page.index("Review before sharing")]
        note = note[note.rindex("<p>"):]
        self.assertIn("recap", note.lower(), note)


if __name__ == "__main__":
    unittest.main()
