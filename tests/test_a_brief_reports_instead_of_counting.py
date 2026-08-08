"""`--brief` answers "what did you get done", and answers it honestly.

The digest is an activity log: files, commands, errors, the prompt you typed.
This view is a report, and a report makes two claims a log never has to:

  - **that a thing is finished.**  A transcript is full of activity and short of
    outcomes; a thousand commands can leave nothing behind and one can ship a
    release.  So what counts as done is pinned here, narrowly, by test.
  - **that the numbers are true.**  Half of this page is written by a model, and
    a model will happily write "three sessions" about four.  Every figure is
    computed from the transcripts instead, and the tests below check that by
    giving the model an answer that lies and reading the page it produces.

The model is a seam (``render_brief(..., ask=)``), so none of this runs one.
The one test that does go through the command line uses a script on disk that
records what it was sent, which is the only way to check the half of this
feature that never appears on screen.
"""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from agentlog import brief  # noqa: E402
from agentlog.asking_a_model import NoModel  # noqa: E402


def a_session(cwd="/home/you/api", commands=(), failed=(), written=(),
              asks=("get the parser fixed",), tokens=(1000, 500), sid="a1b2c3d4",
              seconds=600, recaps=()):
    """One session dict of the shape the parser produces.

    Written out longhand rather than parsed from a fixture log because what is
    under test here is the reporting, not the reading; the parser has its own
    tests and going through it would make every failure in this file ambiguous.
    """
    import datetime
    start = datetime.datetime(2026, 8, 8, 9, 0,
                              tzinfo=datetime.timezone.utc)
    end = start + datetime.timedelta(seconds=seconds)
    return {
        "id": sid, "project": cwd, "project_name": os.path.basename(cwd),
        "source": "claude", "start": start, "end": end,
        "duration_s": seconds, "active_s": seconds,
        "active_spans": [(start, end)],
        "win_start": start, "win_end": end, "window_s": seconds,
        "commands": list(commands), "failed_cmds": list(failed),
        "files_written": list(written), "files_read": [],
        "asks": list(asks), "asked": asks[0] if asks else "",
        "tokens_in": tokens[0], "tokens_out": tokens[1],
        "errors": len(failed), "user_turns": 1, "events": [],
        "models": ["claude-opus-5"], "compactions": [], "recaps": list(recaps),
        "write_counts": {}, "skipped_lines": 0, "token_events": [],
        "ai_title": "", "version": "", "recaps_": None,
    }


def an_answer(*blocks):
    """A model reply in the format the prompt asks for."""
    return "\n".join(blocks)


class TestWhatCountsAsFinished(unittest.TestCase):
    """The narrow bit.  A near-release is not a release."""

    def outcomes(self, *commands):
        return brief.outcomes_of(a_session(commands=commands))

    def test_a_commit_is_reported_with_what_the_person_called_it(self):
        # The commit subject is an engineer answering this view's own question,
        # in their own words, already on disk.  It is the single most useful
        # sentence a transcript contains and it costs nothing to read.
        self.assertEqual(
            self.outcomes('git commit -m "Show what you asked for"'),
            ["committed: Show what you asked for"])

    def test_a_commit_with_no_message_on_the_line_is_still_a_commit(self):
        self.assertEqual(self.outcomes("git commit --amend --no-edit"),
                         ["committed"])

    def test_a_commit_message_is_cut_to_its_subject(self):
        # `-m "subject\n\nbody"` is normal and the body can be twenty lines.
        got = self.outcomes('git commit -m "Fix the parser\n\nlong body here"')
        self.assertEqual(got, ["committed: Fix the parser"])

    def test_the_verbs_that_mean_something_shipped(self):
        for command, expected in (
                ("git push origin main", "pushed"),
                ("git tag v0.3.0", "tagged"),
                ("gh pr create --fill", "opened a pull request"),
                ("twine upload dist/*", "published"),
                ("pytest -x tests", "ran the tests"),
                ("/home/you/.venv/bin/pyproject-build .", "built"),
        ):
            with self.subTest(command=command):
                self.assertEqual(self.outcomes(command), [expected])

    def test_a_command_that_finished_nothing_is_not_an_outcome(self):
        # The commonest commands in any transcript are these, and a report that
        # called them outcomes would be a report of nothing.
        self.assertEqual(
            self.outcomes("ls -la", "grep -rn foo .", "cd /home/you/api",
                          "cat README.md", "git status"),
            [])

    def test_editing_files_is_not_finishing_anything(self):
        # Stated as its own test because it is the flattery this whole view is
        # against: forty files edited and nothing committed is a day that
        # finished nothing, and a report that says otherwise is worse than none.
        s = a_session(written=["/home/you/api/a.py", "/home/you/api/b.py"])
        self.assertEqual(brief.outcomes_of(s), [])

    def test_a_git_command_that_only_talks_about_committing_is_not_one(self):
        self.assertEqual(self.outcomes("git log --oneline",
                                       "grep -n 'git commit' notes.md"),
                         [])

    def test_only_the_failures_that_were_still_failing_are_kept(self):
        # A command that failed and then worked is an engineer working.  What a
        # report owes the reader is the tail: what was broken when they stopped.
        s = a_session(failed=["pytest -x", "pytest -x", "make lint"])
        self.assertEqual(brief._stuck(s), ["make lint", "pytest -x"])

    def test_the_same_failure_twice_is_reported_once(self):
        s = a_session(failed=["make lint", "make lint", "make lint"])
        self.assertEqual(brief._stuck(s), ["make lint"])


class TestTheNumbersAreNotTheModels(unittest.TestCase):
    """Half the page is written by a model.  None of the figures are."""

    ONE_PROJECT = an_answer(
        "THEME: get the parser fixed",
        "PROJECTS: api",
        "DID: the change went in and the suite is green.",
        "OPEN: it is not released.",
    )

    def render(self, sessions, answer):
        return brief.render_brief(sessions, "today", ask=lambda _prompt: answer)

    def test_a_sentence_that_states_a_tally_never_reaches_the_page(self):
        # The model is told to write no numbers.  This one writes numbers, and
        # they are wrong, which is exactly the failure the split exists for:
        # "47 sessions" printed one line above a computed "2 sessions" is the
        # page contradicting itself, and the reader has no way to tell which
        # half was counted.
        lying = an_answer(
            "THEME: get the parser fixed",
            "PROJECTS: api",
            "DID: closed out all 47 sessions across 9 projects.",
            "OPEN: 3 files are still unfinished.",
            "DID: the change went in and the suite is green.",
        )
        page = self.render([a_session(sid="s1"), a_session(sid="s2")], lying)
        self.assertNotIn("47", page, page)
        self.assertNotIn("9 projects", page, page)
        self.assertNotIn("3 files are still", page, page)
        # The honest sentence survives, and so does the computed tally.
        self.assertIn("the change went in and the suite is green.", page, page)
        self.assertIn("2 sessions", page, page)

    def test_a_number_that_is_not_a_count_is_left_alone(self):
        # A version, a port, a width: the model read these off the evidence and
        # none of them pretends to be a tally.  Cutting every digit would cost
        # more than it saved.
        page = self.render([a_session()], an_answer(
            "THEME: the release",
            "PROJECTS: api",
            "DID: released 0.3.0 and fixed the 32-bit path.",
        ))
        self.assertIn("released 0.3.0 and fixed the 32-bit path.", page, page)

    def test_a_project_the_model_invented_carries_no_figures(self):
        # The join between the two halves.  A theme's numbers are the sum of
        # the projects it names, so a name nobody counted has to be dropped
        # before it can add up to anything.
        made_up = an_answer(
            "THEME: get the parser fixed",
            "PROJECTS: api, warehouse-service, nope",
            "DID: the change went in.",
        )
        themes = brief.read_the_answer(made_up, ["api"])
        self.assertEqual(themes[0].projects, ["api"])

    def test_a_theme_naming_only_invented_projects_shows_no_tally(self):
        page = self.render([a_session()], an_answer(
            "THEME: something that did not happen",
            "PROJECTS: warehouse-service",
            "DID: it was done.",
        ))
        self.assertIn("something that did not happen", page)
        # No figures line under it: the projects it named were not counted, so
        # there is nothing honest to put there.
        self.assertNotIn("warehouse-service", page, page)

    def test_the_tally_sums_only_the_projects_the_theme_named(self):
        sessions = [a_session(cwd="/home/you/api", sid="s1"),
                    a_session(cwd="/home/you/web", sid="s2"),
                    a_session(cwd="/home/you/web", sid="s3")]
        page = self.render(sessions, an_answer(
            "THEME: the web work",
            "PROJECTS: web",
            "DID: it went in.",
        ))
        # Two of the three sessions are `web`; the headline still counts three.
        self.assertIn("3 sessions", page.splitlines()[0], page)
        tally = [l for l in page.splitlines() if l.strip().startswith("web ·")]
        self.assertEqual(len(tally), 1, page)
        self.assertIn("2 sessions", tally[0], tally[0])

    def test_two_directories_with_one_name_are_one_project_not_half_of_one(self):
        # A checkout and its worktree share a display name, and the model can
        # only refer to a project by that name.  Keyed naively, one of them
        # replaces the other and a whole day goes missing off a page that still
        # looks complete.
        facts = brief.facts_by_project([
            a_session(cwd="/home/you/api", sid="s1"),
            a_session(cwd="/home/you/worktrees/api", sid="s2"),
        ])
        self.assertEqual(sorted(facts), ["api"])
        self.assertEqual(len(facts["api"].sessions), 2)

    def test_the_figures_survive_a_theme_that_covers_many_places(self):
        # Six sandbox directories running one machine-written prompt is a real
        # day here, and their names once filled the whole tally line and pushed
        # the counts off the end of it -- a row of noise where the one
        # checkable thing on the page should have been.
        sessions = [a_session(cwd="/home/you/relay-review-%d" % n,
                              sid="s%d" % n) for n in range(7)]
        page = self.render(sessions, an_answer(
            "THEME: gating the worker changes",
            "PROJECTS: " + ", ".join("relay-review-%d" % n for n in range(7)),
            "DID: each change was read against its spec.",
        ))
        tally = [l for l in page.splitlines() if "7 sessions" in l]
        self.assertEqual(len(tally), 2, page)  # the headline and the theme
        self.assertIn("others", page, page)
        # A whole name and an honest remainder, never a name cut in half.
        self.assertNotIn("other…", page, page)
        for line in page.splitlines():
            self.assertLessEqual(len(line), brief.WIDTH, repr(line))

    def test_the_headline_counts_the_sessions_it_was_given(self):
        page = self.render([a_session(sid="s1"), a_session(sid="s2")],
                           self.ONE_PROJECT)
        first = page.splitlines()[0]
        self.assertIn("today", first)
        self.assertIn("2 sessions", first)
        self.assertIn("1 project", first)


class TestTheReportReads(unittest.TestCase):
    """It is meant to be read by a person in a few seconds."""

    def test_it_says_how_many_things_in_words(self):
        page = brief.render_brief(
            [a_session()], "today",
            ask=lambda _p: an_answer(
                "THEME: one", "PROJECTS: api", "DID: done.",
                "THEME: two", "PROJECTS: api", "DID: done.",
                "THEME: three", "PROJECTS: api", "DID: done."))
        self.assertIn("Three things:", page, page)

    def test_one_thing_is_singular(self):
        page = brief.render_brief(
            [a_session()], "today",
            ask=lambda _p: an_answer("THEME: one", "PROJECTS: api",
                                     "DID: done."))
        self.assertIn("One thing:", page, page)

    def test_done_and_not_done_are_both_labelled(self):
        page = brief.render_brief(
            [a_session()], "today",
            ask=lambda _p: an_answer("THEME: the work", "PROJECTS: api",
                                     "DID: the change went in.",
                                     "OPEN: it is not released."))
        self.assertIn("done      the change went in.", page.lower(), page)
        self.assertIn("not done  it is not released.", page.lower(), page)

    def test_no_line_runs_past_the_page(self):
        # A done line is a sentence, and a sentence that is cut loses the half
        # that says what was done -- so this view wraps where the digest cuts.
        long_one = ("the parser was rewritten to read both formats and the "
                    "whole suite was brought back green after the change to "
                    "the window clipping, which had been failing since Tuesday")
        page = brief.render_brief(
            [a_session()], "today",
            ask=lambda _p: an_answer("THEME: the work", "PROJECTS: api",
                                     "DID: " + long_one))
        for line in page.splitlines():
            self.assertLessEqual(len(line), brief.WIDTH, repr(line))
        # and wrapping kept the words rather than dropping them
        self.assertIn("failing since Tuesday", " ".join(page.split()))

    def test_a_theme_with_nothing_to_report_is_not_printed(self):
        # A heading with no done and no open line is a heading about nothing.
        page = brief.render_brief(
            [a_session()], "today",
            ask=lambda _p: an_answer("THEME: an empty heading",
                                     "PROJECTS: api"))
        self.assertNotIn("an empty heading", page)

    def test_a_reply_wrapped_in_chatter_is_still_read(self):
        # A CLI that says "Here you go:" first, or numbers the blocks, should
        # not cost somebody their report.
        page = brief.render_brief(
            [a_session()], "today",
            ask=lambda _p: ("Sure, here is the report:\n\n"
                            "1. THEME: the work\n"
                            "   PROJECTS: api\n"
                            "   - DID: the change went in.\n"
                            "\nHope that helps!\n"))
        self.assertIn("the work", page)
        self.assertIn("the change went in.", page)
        self.assertNotIn("Hope that helps", page)

    def test_an_empty_window_says_so_without_asking_a_model(self):
        def refuse(_prompt):
            raise AssertionError("a model was asked about an empty day")
        self.assertIn("no sessions found",
                      brief.render_brief([], "today", ask=refuse))


class TestWhenNoModelAnswers(unittest.TestCase):
    """The page degrades; it does not disappear."""

    def page(self):
        def missing(_prompt):
            raise NoModel("the claude command is not on PATH")
        return brief.render_brief(
            [a_session(commands=['git commit -m "Fix the parser"',
                                 "git push origin main"],
                       failed=["make lint"],
                       written=["/home/you/api/parser.py"])],
            "today", ask=missing)

    def test_it_says_what_is_missing_and_why(self):
        self.assertIn("no summary: the claude command is not on PATH",
                      self.page())

    def test_the_facts_are_all_still_there(self):
        page = self.page()
        for expected in ("api", "1 session", "committed: Fix the parser",
                         "pushed", "make lint"):
            self.assertIn(expected, page, page)

    def test_it_falls_back_to_the_goal_only_when_nothing_finished(self):
        # With outcomes to show, the prompt stays off the page -- that is the
        # point of this view.  With none, the goal is the only thing left that
        # says what the session was about, and a blank row is worse.
        def missing(_prompt):
            raise NoModel("no model")
        finished = brief.render_brief(
            [a_session(commands=["git push origin main"])], "today",
            ask=missing)
        self.assertNotIn("get the parser fixed", finished, finished)
        nothing = brief.render_brief([a_session(commands=["ls"])], "today",
                                     ask=missing)
        self.assertIn("get the parser fixed", nothing, nothing)


class TestWhatIsPutToTheModel(unittest.TestCase):
    """The prompt is the other half of this feature, so it is read directly."""

    def question(self, sessions):
        return brief.the_question(brief.facts_by_project(sessions), "today")

    def test_it_carries_the_evidence_a_judgement_needs(self):
        q = self.question([a_session(
            commands=['git commit -m "Fix the parser"'],
            written=["/home/you/api/parser.py"],
            failed=["make lint"])])
        for expected in ("project: api", "get the parser fixed",
                         "committed: Fix the parser", "parser.py", "make lint"):
            self.assertIn(expected, q, q)

    def test_it_asks_for_no_numbers(self):
        # Because any number it wrote would be a number nobody checked.
        q = self.question([a_session()])
        self.assertIn("Write no numbers at all", q)

    def test_it_carries_no_counts_to_repeat_back(self):
        # The evidence deliberately holds no tallies: a prompt that states
        # "3 sessions, 1.1M tokens" invites a model to put them in a sentence,
        # where they would look computed and be quoted.
        q = self.question([a_session(sid="s1"), a_session(sid="s2")])
        evidence = q.split("Answer with nothing but")[0]
        for absent in ("2 sessions", "tokens", "1500"):
            self.assertNotIn(absent, evidence, evidence)

    def test_a_project_where_nothing_happened_says_so(self):
        # Otherwise the model has to guess from an absence, and it will guess
        # generously.
        q = self.question([a_session(commands=["ls"])])
        self.assertIn("nothing was written or committed here", q)

    def test_one_project_cannot_crowd_out_the_rest(self):
        # A day can hold thousands of commands in one directory.  The model
        # needs the shape of the work, and a prompt that is 90% one project's
        # file list is a prompt that reports one project.
        busy = a_session(cwd="/home/you/api",
                         written=["/home/you/api/f%d.py" % n
                                  for n in range(200)])
        quiet = a_session(cwd="/home/you/web", sid="s2",
                          commands=["git push origin main"])
        q = self.question([busy, quiet])
        self.assertIn("project: web", q)
        self.assertLessEqual(q.count("/home/you/api/f"), brief._PER_PROJECT)


class TestTheFlagRefusesTheCombinationsThatWouldLie(unittest.TestCase):
    """Checked here as well as end-to-end, because the message is the point."""

    def run_cli(self, *argv):
        import subprocess
        import tempfile
        home = tempfile.mkdtemp(prefix="al-brief-")
        os.makedirs(os.path.join(home, ".claude", "projects"))
        return subprocess.run(
            [sys.executable, "-m", "agentlog", "--home", home, *argv],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT, COLUMNS="100"))

    def test_it_cannot_be_a_document_as_well(self):
        p = self.run_cli("--brief", "--json")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("report to read", p.stderr, p.stderr)

    def test_it_cannot_describe_a_single_session(self):
        # `show` is one session and a brief is a day; there is nothing to
        # group, and asking a model to group one thing is a slow way to quote.
        p = self.run_cli("show", "abcd1234", "--brief")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

    def test_it_is_in_the_help(self):
        p = self.run_cli("--help")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("--brief", p.stdout)
        # and the help says the thing a person needs to know before running it
        self.assertIn("model", p.stdout)


if __name__ == "__main__":
    unittest.main()
