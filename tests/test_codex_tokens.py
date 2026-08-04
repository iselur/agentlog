"""What a Codex session actually spent, against what was reported.

A Codex `token_count` record carries two usage blocks side by side:

    "last_token_usage":  {"input_tokens": 15965, ...}   <- this turn
    "total_token_usage": {"input_tokens": 59385, ...}   <- the session so far

The parser read the first one and took the running maximum, on the stated
belief — written down in a comment — that `last_token_usage` was cumulative.
It is not.  It is the turn that just finished, and `total_token_usage` is the
cumulative one, sitting in the same record.  So the number reported as a
session total was really its single most expensive turn.

Measured across the 1134 Codex sessions on this machine:

    input   48,779,049 reported     526,686,226 true    10.8x
    output   3,372,290 reported       7,473,333 true     2.2x

and the worst single session reported 220,864 against 21,519,930 — 97x.  Input
is the worse half because context is resent every turn, so the total climbs all
day while any one turn stays roughly the size of the context window.  That is
also why the bug is invisible: the reported number is the size of a plausible
turn, and a plausible turn is not a suspicious thing to see.

`total_token_usage` is exactly the running sum of `last_token_usage` — checked
on real sessions, and pinned below.  That gives an honest fallback for a log
too old to have the field: add up the per-turn numbers, which reconstructs it
exactly.  Every one of the 1134 sessions here has the field, so the fallback is
for logs this machine has never seen.

Direction: an under-count, and the recoverable kind — the totals are still on
disk, so an old digest can be regenerated and will simply be right.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.parser import parse_codex_session  # noqa: E402

SID = "019f80fa-4d34-7513-8add-a5368508ba77"


def token_count(last_in, last_out, total_in=None, total_out=None,
                ts="2026-08-04T09:00:00.000Z", omit_total=False):
    info = {"last_token_usage": {"input_tokens": last_in,
                                 "cached_input_tokens": 0,
                                 "output_tokens": last_out,
                                 "reasoning_output_tokens": 0,
                                 "total_tokens": last_in + last_out}}
    if not omit_total:
        ti = last_in if total_in is None else total_in
        to = last_out if total_out is None else total_out
        info["total_token_usage"] = {"input_tokens": ti,
                                     "cached_input_tokens": 0,
                                     "output_tokens": to,
                                     "reasoning_output_tokens": 0,
                                     "total_tokens": ti + to}
    return {"timestamp": ts, "type": "event_msg",
            "payload": {"type": "token_count", "info": info}}


def turns(*pairs, omit_total=False):
    """A session's worth of token_count records, totals accumulated."""
    out = []
    ti = to = 0
    for i, (li, lo) in enumerate(pairs):
        ti += li
        to += lo
        out.append(token_count(li, lo, ti, to,
                               ts="2026-08-04T09:%02d:00.000Z" % i,
                               omit_total=omit_total))
    return out


def session_meta(ts="2026-08-04T08:59:00.000Z"):
    return {"timestamp": ts, "type": "session_meta",
            "payload": {"id": SID, "cwd": "/home/you/api",
                        "originator": "codex_cli_rs"}}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="al-ctok-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def parsed(self, records):
        d = os.path.join(self.tmp, ".codex", "sessions", "2026", "08", "04")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "rollout-2026-08-04T09-00-00-" + SID + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        out = parse_codex_session(path)
        self.assertIsNotNone(out, "the session did not parse at all")
        return out


class TestTheTotalIsTheTotal(Case):

    def test_a_single_turn_reports_that_turn(self):
        s = self.parsed([session_meta()] + turns((13019, 233)))
        self.assertEqual((s["tokens_in"], s["tokens_out"]), (13019, 233))

    def test_four_turns_report_the_sum_not_the_largest(self):
        # The real numbers from one session on disk.  The old parser said
        # 15965 in / 267 out — the biggest turn, not the day.
        s = self.parsed([session_meta()] + turns(
            (13019, 233), (15077, 188), (15324, 267), (15965, 135)))
        self.assertEqual((s["tokens_in"], s["tokens_out"]), (59385, 823))

    def test_the_largest_single_turn_is_not_the_answer(self):
        s = self.parsed([session_meta()] + turns(
            (100, 10), (900, 90), (100, 10)))
        self.assertNotEqual(s["tokens_in"], 900)
        self.assertEqual(s["tokens_in"], 1100)

    def test_a_long_session_climbs_far_past_any_one_turn(self):
        # Input is resent every turn, so the gap widens all day.  This is the
        # shape that produced 97x on a real session.
        s = self.parsed([session_meta()] + turns(*[(20000, 200)] * 50))
        self.assertEqual((s["tokens_in"], s["tokens_out"]), (1000000, 10000))

    def test_the_final_snapshot_is_what_counts(self):
        # total_token_usage is monotonic, so the last one is the largest; the
        # parser must not be confused by reading them in order.
        s = self.parsed([session_meta()] + turns((5, 1), (5, 1), (5, 1)))
        self.assertEqual((s["tokens_in"], s["tokens_out"]), (15, 3))


class TestTheTwoBlocksAreRelatedAsAssumed(Case):
    """The fallback is only honest if this holds, so pin it."""

    def test_total_is_the_running_sum_of_last(self):
        recs = turns((13019, 233), (15077, 188), (15324, 267), (15965, 135))
        running_in = running_out = 0
        for r in recs:
            info = r["payload"]["info"]
            running_in += info["last_token_usage"]["input_tokens"]
            running_out += info["last_token_usage"]["output_tokens"]
            self.assertEqual(info["total_token_usage"]["input_tokens"],
                             running_in)
            self.assertEqual(info["total_token_usage"]["output_tokens"],
                             running_out)

    def test_summing_last_reconstructs_total_exactly(self):
        s = self.parsed([session_meta()] + turns(
            (13019, 233), (15077, 188), (15324, 267), (15965, 135),
            omit_total=True))
        self.assertEqual((s["tokens_in"], s["tokens_out"]), (59385, 823))


class TestOlderLogsWithoutTheField(Case):

    def test_a_log_with_no_total_block_still_adds_up(self):
        s = self.parsed([session_meta()] + turns((100, 10), (200, 20),
                                                 omit_total=True))
        self.assertEqual((s["tokens_in"], s["tokens_out"]), (300, 30))

    def test_a_mixed_log_does_not_double_count(self):
        # A session that gains the field partway through must not add the
        # summed half to the cumulative half.
        recs = [session_meta(),
                token_count(100, 10, omit_total=True,
                            ts="2026-08-04T09:00:00.000Z"),
                token_count(200, 20, 300, 30, ts="2026-08-04T09:01:00.000Z")]
        s = self.parsed(recs)
        self.assertEqual((s["tokens_in"], s["tokens_out"]), (300, 30))


class TestTheRecordIsReadDefensively(Case):

    def test_a_session_with_no_token_records_reports_nothing(self):
        s = self.parsed([session_meta()])
        self.assertIsNone(s["tokens_in"])
        self.assertIsNone(s["tokens_out"])

    def test_a_non_numeric_count_is_ignored_not_crashed(self):
        rec = token_count(100, 10, 100, 10)
        rec["payload"]["info"]["total_token_usage"]["input_tokens"] = "lots"
        s = self.parsed([session_meta(), rec])
        self.assertIsNone(s["tokens_in"])
        self.assertEqual(s["tokens_out"], 10)

    def test_a_missing_info_block_is_ignored(self):
        rec = {"timestamp": "2026-08-04T09:00:00.000Z", "type": "event_msg",
               "payload": {"type": "token_count"}}
        s = self.parsed([session_meta(), rec])
        self.assertIsNone(s["tokens_in"])

    def test_an_info_block_that_is_not_a_dict_is_ignored(self):
        rec = {"timestamp": "2026-08-04T09:00:00.000Z", "type": "event_msg",
               "payload": {"type": "token_count", "info": "none"}}
        s = self.parsed([session_meta(), rec])
        self.assertIsNone(s["tokens_in"])

    def test_a_total_that_goes_backwards_keeps_the_high_water_mark(self):
        # Not seen on disk, but a reset partway would otherwise throw away
        # everything before it.
        recs = [session_meta(),
                token_count(500, 50, 500, 50, ts="2026-08-04T09:00:00.000Z"),
                token_count(10, 1, 10, 1, ts="2026-08-04T09:01:00.000Z")]
        s = self.parsed(recs)
        self.assertEqual((s["tokens_in"], s["tokens_out"]), (500, 50))


if __name__ == "__main__":
    unittest.main()
