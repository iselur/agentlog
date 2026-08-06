"""Codex has no read tool, so `files read` was empty for every Codex session.

Claude Code reads a file by calling a tool named ``Read``: the path is a field,
and finding it is a lookup.  Codex reads a file by running ``sed -n '1,200p'
notes.md``, and the command text is the only record of it anywhere in the log.

So the digest reported *no files read* for every Codex session it has ever
parsed.  Not an error, not a warning — a zero, sitting in the same column as
Claude's real number, and reading as a fact about the session rather than as a
gap in the parser.  Across the 1,217 Codex sessions on the machine this was
found on, ``files_read`` totalled 0 while ``commands`` totalled 8,322.  That is
this project's recurring bug again: a total computed from fewer inputs than
exist, printed as though it were complete.

The rule that fixes it is built to miss rather than to invent.  A path counts
only when the verb opens everything it is handed; nothing that searches counts
at all, because ``rg pattern src/`` puts a pattern, a glob and a directory in
the position a path goes and the text cannot say which is which.  A file named
in a digest that was never opened costs a reader more than one that is absent —
so the tests below are as much about what is *not* reported as what is.

The rule lives in ``transcript.py``, beside the other facts about the two
formats, because agentwatch needs the same answer for ``--reads`` and got the
same zero.  ``test_the_reads_flag_works_on_both_logs.py`` over there is the
other half of this.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog.parser import parse_codex_session          # noqa: E402
from agentlog.transcript import files_a_command_reads    # noqa: E402

SID = "4ef1361b-07e4-4bc9-bb29-1783b761d677"
CWD = "/home/you/api"


def meta(ts="2026-08-04T09:00:00.000Z"):
    return {"timestamp": ts, "type": "session_meta",
            "payload": {"session_id": SID, "id": SID, "cwd": CWD,
                        "cli_version": "0.55.0", "timestamp": ts}}


def script(commands, call_id="exec-1", workdir=CWD,
           ts="2026-08-04T09:00:05.000Z"):
    """A ``custom_tool_call`` carrying one or more commands, as Codex writes."""
    calls = ",\n  ".join(
        'tools.exec_command({cmd:"%s",workdir:"%s",yield_time_ms:10000})'
        % (c.replace("\\", "\\\\").replace('"', '\\"'), workdir)
        for c in commands)
    return {"timestamp": ts, "type": "response_item",
            "payload": {"type": "custom_tool_call", "name": "exec",
                        "call_id": call_id,
                        "input": "const r = await Promise.all([\n  %s\n]);"
                                 % calls}}


def old_call(command, call_id="fn-1", workdir=CWD,
             ts="2026-08-04T09:00:05.000Z"):
    """The older ``function_call`` shape, still on disk in older sessions."""
    return {"timestamp": ts, "type": "response_item",
            "payload": {"type": "function_call", "name": "exec_command",
                        "call_id": call_id,
                        "arguments": json.dumps({"cmd": command,
                                                 "workdir": workdir})}}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="al-codex-reads-")
        self.addCleanup(_rmtree, self.tmp)

    def parsed(self, records):
        d = os.path.join(self.tmp, ".codex", "sessions", "2026", "08", "04")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(
            d, "rollout-2026-08-04T09-00-00-" + SID + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        out = parse_codex_session(path)
        self.assertIsNotNone(out, "the session did not parse at all")
        return out


class TestTheSessionReportsWhatItRead(Case):
    """The defect, at the level a reader of the digest meets it."""

    def test_a_codex_session_that_read_a_file_says_so(self):
        s = self.parsed([meta(), script(["cat src/app.py"])])
        self.assertEqual(s["files_read"], ["/home/you/api/src/app.py"])

    def test_the_older_call_shape_reports_reads_too(self):
        # Both shapes are on disk and both are parsed side by side.  Wiring one
        # and not the other is how the last Codex gap lasted as long as it did.
        s = self.parsed([meta(), old_call("cat src/app.py")])
        self.assertEqual(s["files_read"], ["/home/you/api/src/app.py"])

    def test_the_commonest_idiom_in_the_corpus_is_read(self):
        # `sed -n '1,200p' FILE` is how a Codex session reads part of a file,
        # and it is the single most common read in 1,217 real sessions.  It is
        # also the one a shared flag table gets wrong: `-n` swallows the word
        # after it for `head`, and does not for `sed`, where the word after it
        # is the script.
        s = self.parsed([meta(), script(["sed -n '1,200p' notes.md"])])
        self.assertEqual(s["files_read"], ["/home/you/api/notes.md"])

    def test_a_read_becomes_an_event_on_the_timeline(self):
        # The digest's file list is one consumer; the event stream that `show`
        # and the HTML view walk is the other, and a read missing from it is a
        # gap in the story of the session rather than in a total.
        s = self.parsed([meta(), script(["cat src/app.py"])])
        self.assertIn(("read", "/home/you/api/src/app.py"),
                      [(kind, text) for _, kind, text in s["events"]])

    def test_a_path_is_resolved_against_the_directory_it_ran_in(self):
        # The same file reached from two places is one file.  Writes are
        # resolved this way already; a read left relative would show up beside
        # its own absolute spelling and the digest would report two.
        s = self.parsed([meta(),
                         script(["cat app.py"], workdir="/home/you/api/src")])
        self.assertEqual(s["files_read"], ["/home/you/api/src/app.py"])

    def test_a_session_that_only_ran_tests_reports_no_reads(self):
        # The zero has to still be reachable, or the fix has replaced one
        # wrong number with another.
        s = self.parsed([meta(), script(["pytest -x"])])
        self.assertEqual(s["files_read"], [])

    def test_one_file_read_twice_is_one_file(self):
        s = self.parsed([meta(), script(["cat src/app.py",
                                         "head -n 5 src/app.py"])])
        self.assertEqual(s["files_read"], ["/home/you/api/src/app.py"])


class TestItWouldRatherMissAReadThanInventOne(unittest.TestCase):
    """What is deliberately not counted, and why each one is left out."""

    def test_a_search_is_not_a_read(self):
        # `rg --files DIR` lists names without opening any of them, and an
        # early version reported the directory as a file that was read.  There
        # is no way to tell a pattern from a path from a directory in
        # `rg pattern src/` — they occupy the same position — so no searching
        # verb is counted at all, and real `grep` reads are missed on purpose.
        self.assertEqual(files_a_command_reads("rg --files .orchestrator"), [])
        self.assertEqual(files_a_command_reads("grep -n def src/app.py"), [])

    def test_writing_a_file_is_not_reading_one(self):
        self.assertEqual(files_a_command_reads("cat src/app.py > copy.py"), [])

    def test_editing_in_place_is_a_write_and_belongs_in_the_write_list(self):
        self.assertEqual(files_a_command_reads("sed -i 's/a/b/' src/app.py"),
                         [])

    def test_a_heredoc_names_nothing_that_was_read(self):
        # It is the `>` that decides this, not the `<<`.  Every heredoc in the
        # corpus is either redirected like this one or fed to a verb that reads
        # nothing (`python3 - <<'PY'`), so a separate heredoc test turned out
        # to change no answer anywhere and was removed.
        self.assertEqual(
            files_a_command_reads("cat <<'EOF' > x.py\nprint(1)\nEOF"), [])
        self.assertEqual(
            files_a_command_reads("python3 - <<'PY'\nopen('a.py')\nPY"), [])

    def test_a_bare_word_is_not_guessed_at(self):
        # `wc -l dispatch` could be a file, or could be nothing.  A word with
        # neither a separator nor an extension is dropped rather than claimed.
        self.assertEqual(files_a_command_reads("wc -l dispatch"), [])
        self.assertEqual(files_a_command_reads("wc -l src/dispatch"),
                         ["src/dispatch"])

    def test_a_device_is_not_a_file_anyone_wants_listed(self):
        self.assertEqual(files_a_command_reads("cat /dev/null"), [])
        self.assertEqual(files_a_command_reads("cat /proc/cpuinfo"), [])

    def test_a_flag_and_its_value_are_not_paths(self):
        self.assertEqual(files_a_command_reads("head -n 20 src/app.py"),
                         ["src/app.py"])
        self.assertEqual(files_a_command_reads("head -c 4096 src/app.py"),
                         ["src/app.py"])

    def test_a_variable_is_not_resolved(self):
        self.assertEqual(files_a_command_reads("cat $CONFIG"), [])
        self.assertEqual(files_a_command_reads("cat ~/notes.md"), [])

    def test_a_glob_is_not_expanded(self):
        # Expanding it against the machine reading the log is a different
        # question from what the machine writing it opened.
        self.assertEqual(files_a_command_reads("cat src/*.py"), [])

    def test_unbalanced_quotes_produce_nothing_rather_than_a_guess(self):
        self.assertEqual(files_a_command_reads("cat 'src/app.py"), [])

    def test_something_that_is_not_a_string_is_not_a_crash(self):
        # Everything here comes out of somebody else's log on a bad day.
        for junk in (None, 17, [], {}, ""):
            self.assertEqual(files_a_command_reads(junk), [])


class TestTheShapesRealCommandsCome(unittest.TestCase):
    """Idioms taken from the corpus, each of which broke an earlier draft."""

    def test_a_read_that_may_not_find_the_file(self):
        # `2>/dev/null || true` is how this corpus reads a file that may not be
        # there.  Treating the `>` in it as a redirect discarded the whole
        # statement, and with it the commonest guarded read in the logs.
        self.assertEqual(
            files_a_command_reads("sed -n '1,240p' PLAN.md 2>/dev/null || true"),
            ["PLAN.md"])

    def test_two_commands_on_one_line_are_two_commands(self):
        self.assertEqual(
            files_a_command_reads("cat a.py; head -n 3 b.py"), ["a.py", "b.py"])

    def test_a_newline_separates_them_as_surely_as_a_semicolon(self):
        # Codex snippets are full of newline-joined commands.  Splitting on
        # punctuation alone shlex-split the lot as one statement and produced
        # paths that were in none of them.
        self.assertEqual(
            files_a_command_reads("cat a.py\nhead -n 3 b.py"), ["a.py", "b.py"])

    def test_the_verb_on_the_second_line_is_the_one_that_line_ran(self):
        # The case above cannot actually see the newline: joined into one
        # statement it reads `cat a.py head -n 3 b.py`, and `cat` claims both
        # paths anyway.  Put a verb that reads nothing on the first line and
        # the two answers come apart — joined, the whole thing is a `pytest`
        # invocation and nothing is read at all.
        self.assertEqual(files_a_command_reads("pytest -x\ncat a.py"), ["a.py"])
        self.assertEqual(files_a_command_reads("pytest -x cat a.py"), [])

    def test_a_pipe_ends_a_statement_and_the_right_hand_side_reads_nothing(self):
        self.assertEqual(files_a_command_reads("cat a.py | head -n 5"),
                         ["a.py"])

    def test_the_order_they_were_read_in_is_kept(self):
        self.assertEqual(files_a_command_reads("cat z.py a.py m.py"),
                         ["z.py", "a.py", "m.py"])

    def test_a_full_path_to_the_verb_is_still_the_verb(self):
        self.assertEqual(files_a_command_reads("/bin/cat src/app.py"),
                         ["src/app.py"])

    def test_an_awk_program_is_not_a_path(self):
        self.assertEqual(files_a_command_reads("awk '{print $1}' data.csv"),
                         ["data.csv"])

    def test_a_sed_script_that_is_shaped_like_a_path_is_still_a_script(self):
        # `sed -n '1,200p' f` cannot see whether the script word was skipped:
        # `1,200p` has no separator and no extension, so it is turned down as a
        # path either way.  `/foo/p` has a slash in it and is turned down only
        # because sed's first non-flag word is known to be the script — and
        # only because `-n` was recognised as a flag and not counted as it.
        self.assertEqual(files_a_command_reads("sed -n '/foo/p' notes.md"),
                         ["notes.md"])

    def test_a_script_given_by_a_flag_leaves_the_first_word_a_file(self):
        # `-e` and `-f` supply the script, so there is no inline script to skip
        # and the word after the flags is a file like any other.  Skipping it
        # anyway reported nothing read for either of these.
        self.assertEqual(files_a_command_reads("sed -e 's/a/b/' notes.md"),
                         ["notes.md"])
        self.assertEqual(files_a_command_reads("awk -f prog.awk data.csv"),
                         ["data.csv"])

    def test_one_command_naming_a_file_twice_names_it_once(self):
        # The digest dedups across a session, so a rule that returned the same
        # path twice looked correct from there.  This is the rule's own answer,
        # where the second copy has nothing downstream to absorb it.
        self.assertEqual(files_a_command_reads("cat a.py a.py"), ["a.py"])
        self.assertEqual(files_a_command_reads("cat a.py; head -n 3 a.py"),
                         ["a.py"])

    def test_an_env_prefix_is_not_a_path(self):
        # The prefix sits where the verb goes, so the verb lookup turns the
        # whole statement down and the read is missed.  That is the under-
        # reporting this module prefers, and it is what makes the answer here
        # empty rather than `src/app.py`.
        self.assertEqual(files_a_command_reads("LC_ALL=C cat src/app.py"), [])


class TestBothPackagesReadItTheSameWay(unittest.TestCase):
    """The rule is in the shared module, which is the point of having one.

    agentwatch's ``--reads`` was empty for Codex for exactly the same reason
    this digest column was.  Two consumers of one missing rule is what makes
    the seam real rather than hypothetical — and a rule written twice is a rule
    that drifts, which is the whole reason ``transcript.py`` exists.
    """

    def test_the_rule_lives_in_the_shared_module(self):
        from agentlog import parser
        self.assertIs(parser.files_a_command_reads, files_a_command_reads)

    def test_neither_adapter_works_the_paths_out_for_itself(self):
        here = os.path.join(_ROOT, "agentlog", "parser.py")
        with open(here, encoding="utf-8") as fh:
            body = fh.read()
        for spelling in ("_READS_ITS_ARGS", "shlex.split"):
            self.assertNotIn(spelling, body,
                             "parser.py picks reads apart itself again")


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
