"""`--brief` answers "what did you get done", and answers it honestly.

The digest is an activity log: files, commands, errors, the prompt you typed.
This view is a report, and a report makes claims a log never has to:

  - **that a thing is finished.**  A transcript is full of activity and short of
    outcomes; a thousand commands can leave nothing behind and one can ship a
    release.  So what counts as done is pinned here, narrowly, by test.
  - **that the numbers are true.**  Half of this page is written by a model, and
    a model will happily write "three sessions" about four.  Every figure is
    computed from the transcripts instead, and the tests below check that by
    giving the model an answer that lies and reading the page it produces.
  - **that a status mark is earned.**  ``done`` needs a receipt in the
    transcripts, a goal comes from the goal store or not at all, and ``not
    started`` is read off the store and the logs with no model in the room.

The model is a seam (``render_brief(..., ask=)``), so none of this runs one.
The goal store is a seam too (``render_brief(..., goals=)``), so none of this
touches the filesystem.  The one test class that does go through the command
line checks the flag combinations, which is the only way to check exit codes.
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
              seconds=600, recaps=(), source="claude"):
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
        "source": source, "start": start, "end": end,
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


def a_goal(cwd, text, set_at=1_700_000_000.0):
    """A goal-store entry as `goal.everything_declared` would return it."""
    real = os.path.realpath(cwd)
    return {real: {"cwd": real, "goal": text, "set_at": set_at}}


def an_answer(*lines):
    """A model reply in the format the prompt asks for."""
    return "\n".join(lines)


def render(sessions, answer, goals=None):
    return brief.render_brief(sessions, "today",
                              ask=lambda _prompt: answer, goals=goals)


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

    def test_a_sentence_that_states_a_tally_never_reaches_the_page(self):
        # The model is told to write no counts.  This one writes counts, and
        # they are wrong, which is exactly the failure the split exists for:
        # "47 sessions" printed one line above a computed "2 sessions" is the
        # page contradicting itself, and the reader has no way to tell which
        # half was counted.
        lying = an_answer(
            "PROJECT: api",
            "STATUS: none",
            "SAID: closed out all 47 sessions across 9 projects.",
            "SAID: 3 files are still unfinished.",
            "SAID: the change went in and the suite is green.",
        )
        page = render([a_session(sid="s1"), a_session(sid="s2")], lying)
        self.assertNotIn("47", page, page)
        self.assertNotIn("9 projects", page, page)
        self.assertNotIn("3 files are still", page, page)
        # The honest sentence survives, and so does the computed tally.
        self.assertIn("the change went in and the suite is green.", page, page)
        self.assertIn("2 sessions", page, page)

    def test_a_number_that_is_not_a_count_is_left_alone(self):
        # A version, a width, a test count: the model read these off the
        # evidence and none of them is a figure this page computes.  "214
        # tests green" is a receipt, and a receipt with a number in it is
        # exactly the kind of sentence the report exists to carry.
        page = render([a_session()], an_answer(
            "PROJECT: api",
            "STATUS: none",
            "SAID: released 0.3.0 and fixed the 32-bit path.",
            "SAID: merged with 214 tests green.",
        ))
        self.assertIn("released 0.3.0 and fixed the 32-bit path.", page, page)
        self.assertIn("merged with 214 tests green.", page, page)

    def test_a_number_beside_a_unit_word_across_punctuation_is_not_a_tally(self):
        # "stays at 5; the session ended there" is a number and a unit word in
        # one sentence, not a count of sessions.  The gap the filter allows is
        # word-shaped so it cannot bridge the punctuation between them.
        keep = "the retry cap stays at 5; the session ended on that question."
        self.assertFalse(brief._states_a_tally(keep))
        self.assertFalse(brief._states_a_tally("capped at 5. The session died"))
        self.assertTrue(brief._states_a_tally("closed out 47 sessions"))
        self.assertTrue(brief._states_a_tally("spent 1.1M input tokens"))
        self.assertTrue(brief._states_a_tally("about 2 more hours of it"))

    def test_a_project_the_model_invented_carries_no_claims(self):
        # A PROJECT name nobody counted drops its whole block: a made-up
        # project must not carry made-up claims onto the page.
        reports = brief.read_the_answer(an_answer(
            "PROJECT: api",
            "STATUS: none",
            "SAID: the change went in.",
            "PROJECT: warehouse-service",
            "STATUS: done",
            "SAID: it shipped, honest.",
        ), ["api"])
        self.assertEqual([r.project for r in reports], ["api"])
        # and its sentences do not leak into the block above it
        self.assertNotIn("it shipped, honest.", " ".join(reports[0].said))

    def test_an_answer_naming_only_invented_projects_reports_nothing(self):
        page = render([a_session()], an_answer(
            "PROJECT: warehouse-service",
            "STATUS: done",
            "SAID: it was done.",
        ))
        self.assertNotIn("warehouse-service", page, page)
        self.assertNotIn("it was done.", page, page)
        # and the day's facts still print instead of a blank page
        self.assertIn("api", page, page)
        # An answer that reported nothing cannot vouch that nothing is waiting.
        self.assertNotIn("Waiting on you", page, page)

    def test_the_tally_under_a_project_counts_that_project_alone(self):
        sessions = [a_session(cwd="/home/you/api", sid="s1"),
                    a_session(cwd="/home/you/web", sid="s2"),
                    a_session(cwd="/home/you/web", sid="s3")]
        page = render(sessions, an_answer(
            "PROJECT: web",
            "STATUS: none",
            "SAID: it went in.",
        ))
        # Two of the three sessions are `web`; the headline still counts three.
        self.assertIn("3 sessions", page.splitlines()[0], page)
        block = [l for l in page.splitlines()
                 if l.strip().startswith("2 sessions")]
        self.assertEqual(len(block), 1, page)

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

    def test_the_newest_declaration_wins_across_merged_directories(self):
        # The same rule the store applies: the goal the work was last pointed
        # at is the one the project is judged against.
        facts = brief.facts_by_project([
            a_session(cwd="/home/you/api", sid="s1"),
            a_session(cwd="/home/you/worktrees/api", sid="s2"),
        ])
        goals = {**a_goal("/home/you/api", "the old goal", set_at=1_000.0),
                 **a_goal("/home/you/worktrees/api", "the new goal",
                          set_at=2_000.0)}
        record = brief._goal_for(facts["api"], goals)
        self.assertEqual(record["goal"], "the new goal")

    def test_the_headline_counts_the_sessions_it_was_given(self):
        page = render([a_session(sid="s1"), a_session(sid="s2")], an_answer(
            "PROJECT: api", "STATUS: none", "SAID: the change went in."))
        first = page.splitlines()[0]
        self.assertIn("today", first)
        self.assertIn("2 sessions", first)
        self.assertIn("1 project", first)

    def test_the_headline_counts_goals_when_there_are_goals(self):
        goals = {**a_goal("/home/you/api", "Fix the parser."),
                 **a_goal("/home/you/importer", "Rewrite the importer.")}
        page = render([a_session()], an_answer(
            "PROJECT: api", "STATUS: in progress", "SAID: some landed."),
            goals=goals)
        self.assertIn("2 goals in play", page.splitlines()[0], page)


class TestTheStatusIsEarned(unittest.TestCase):
    """A mark on the page is evidence-shaped, not model-shaped."""

    GOAL = a_goal("/home/you/api", "Fix the parser; done when the suite runs.")

    def test_done_with_a_receipt_is_done(self):
        page = render([a_session(commands=['git commit -m "fix"',
                                           "git push origin main"])],
                      an_answer("PROJECT: api", "STATUS: done",
                                "SAID: it shipped."),
                      goals=self.GOAL)
        self.assertIn("✔ done — api", page, page)

    def test_done_without_a_receipt_is_demoted_to_in_progress(self):
        # A model's opinion that something is finished is not evidence that it
        # is.  No commit, no push, no release in the transcripts: the claim is
        # printed as in progress, which is the most it can prove.
        page = render([a_session(commands=["ls"])],
                      an_answer("PROJECT: api", "STATUS: done",
                                "SAID: all finished, trust me."),
                      goals=self.GOAL)
        self.assertNotIn("✔", page, page)
        self.assertIn("◐ in progress — api", page, page)

    def test_a_project_with_no_goal_is_never_judged(self):
        # A verdict needs something to be a verdict against.  Whatever the
        # model claims, a goalless project gets the undecided mark.
        page = render([a_session(commands=['git commit -m "fix"'])],
                      an_answer("PROJECT: api", "STATUS: done",
                                "SAID: it shipped."))
        self.assertNotIn("✔", page, page)
        self.assertIn("· api — no goal declared.", page, page)

    def test_failed_is_reported_as_failed(self):
        page = render([a_session(failed=["pytest -x"])],
                      an_answer("PROJECT: api", "STATUS: failed",
                                "SAID: the attempt ended broken."),
                      goals=self.GOAL)
        self.assertIn("✘ failed — api", page, page)

    def test_a_models_synonym_for_in_progress_is_understood(self):
        for word in ("ongoing", "partly", "In Progress."):
            with self.subTest(word=word):
                page = render([a_session()],
                              an_answer("PROJECT: api", "STATUS: " + word,
                                        "SAID: some of it landed."),
                              goals=self.GOAL)
                self.assertIn("◐ in progress — api", page, page)

    def test_a_goal_no_session_visited_is_not_started(self):
        # Read from the store and the logs alone: a declared goal whose
        # directory shows up in none of the period's transcripts was not
        # started, and no model is consulted about it.
        goals = {**self.GOAL,
                 **a_goal("/home/you/importer",
                          "Rewrite the importer. Why: malformed rows crash it.")}
        page = render([a_session()],
                      an_answer("PROJECT: api", "STATUS: in progress",
                                "SAID: some landed."),
                      goals=goals)
        self.assertIn("○ not started — importer", page, page)
        self.assertIn("Rewrite the importer.", page, page)

    def test_untouched_goals_print_newest_declaration_first(self):
        # The goal most recently set and then not picked up is the one most
        # worth being reminded of.
        goals = {**a_goal("/home/you/importer", "The old plan.", set_at=1.0),
                 **a_goal("/home/you/exporter", "The new plan.", set_at=2.0)}
        page = render([a_session()], an_answer(
            "PROJECT: api", "STATUS: none", "SAID: it went in."), goals=goals)
        self.assertLess(page.index("exporter"), page.index("importer"), page)

    def test_not_started_prints_even_when_no_model_answers(self):
        def missing(_prompt):
            raise NoModel("no model")
        goals = a_goal("/home/you/importer", "Rewrite the importer.")
        page = brief.render_brief([a_session()], "today", ask=missing,
                                  goals=goals)
        self.assertIn("○ not started — importer", page, page)

    def test_a_goal_holding_project_the_model_ignored_still_prints(self):
        # The model went quiet about the one project with a goal.  Its goal
        # and its figures print anyway: prose is optional, the record is not.
        page = render([a_session()], "nothing useful at all",
                      goals=self.GOAL)
        self.assertIn("· api —", page, page)
        self.assertIn("Fix the parser;", page, page)
        self.assertIn("1 session", page, page)

    def test_the_goal_is_quoted_in_the_header_never_paraphrased(self):
        page = render([a_session()],
                      an_answer("PROJECT: api", "STATUS: in progress",
                                "SAID: some landed."),
                      goals=self.GOAL)
        self.assertIn('"Fix the parser; done when the suite runs."', page,
                      page)


class TestWaitingOnYou(unittest.TestCase):
    """What is blocked on the reader is pulled out where a skimming eye lands."""

    def test_a_waiting_line_lands_in_its_own_section_with_the_project(self):
        page = render([a_session()], an_answer(
            "PROJECT: api",
            "STATUS: in progress",
            "SAID: the retry work landed.",
            "WAITING: decide whether the retry cap stays at 5; the session "
            "ended on that question.",
        ), goals=a_goal("/home/you/api", "Retry the webhook."))
        self.assertIn("Waiting on you", page, page)
        self.assertIn("api — decide whether the retry cap stays at 5", page,
                      page)

    def test_nothing_waiting_says_so_with_the_hedge(self):
        # Silence from the model about blockers is reported as what it is: an
        # absence in the transcripts, not a promise that nothing needs you.
        page = render([a_session()], an_answer(
            "PROJECT: api", "STATUS: none", "SAID: it went in."))
        self.assertIn("Waiting on you", page, page)
        self.assertIn("nothing, as far as the transcripts show.", page, page)

    def test_no_model_means_no_waiting_section_at_all(self):
        # The section is inference, and a page that could not ask cannot claim
        # "nothing needs you" -- so the section is absent, not empty.
        def missing(_prompt):
            raise NoModel("no model")
        page = brief.render_brief([a_session()], "today", ask=missing)
        self.assertNotIn("Waiting on you", page, page)


class TestTheReportReads(unittest.TestCase):
    """It is meant to be read by a person in a few seconds."""

    def test_no_line_runs_past_the_page(self):
        # A report line is a sentence, and a sentence that is cut loses the
        # half that says what was done -- so this view wraps where the digest
        # cuts.
        long_one = ("the parser was rewritten to read both formats and the "
                    "whole suite was brought back green after the change to "
                    "the window clipping, which had been failing since Tuesday")
        page = render([a_session()],
                      an_answer("PROJECT: api", "STATUS: in progress",
                                "SAID: " + long_one),
                      goals=a_goal("/home/you/api",
                                   "A goal long enough that the header has to "
                                   "shorten the quotation to keep the line on "
                                   "the page, which it does with an ellipsis"))
        for line in page.splitlines():
            self.assertLessEqual(len(line), brief.WIDTH, repr(line))
        # and wrapping kept the words rather than dropping them
        self.assertIn("failing since Tuesday", " ".join(page.split()))

    def test_two_blocks_for_one_project_are_one_paragraph(self):
        # A model that split its answer is merged rather than printed twice.
        page = render([a_session()], an_answer(
            "PROJECT: api", "STATUS: none", "SAID: the first half.",
            "PROJECT: api", "SAID: the second half.",
        ))
        headers = [l for l in page.splitlines() if "· api" in l]
        self.assertEqual(len(headers), 1, page)
        self.assertIn("the first half. the second half.", page, page)

    def test_a_reply_wrapped_in_chatter_is_still_read(self):
        # A CLI that says "Here you go:" first, or numbers the blocks, should
        # not cost somebody their report.
        page = render([a_session()],
                      ("Sure, here is the report:\n\n"
                       "1. PROJECT: api\n"
                       "   STATUS: none\n"
                       "   - SAID: the change went in.\n"
                       "\nHope that helps!\n"))
        self.assertIn("the change went in.", page)
        self.assertNotIn("Hope that helps", page)

    def test_goalless_projects_nobody_reported_on_roll_into_one_line(self):
        # A fleet's day is mostly short sessions -- reviewer gates, small
        # fixes -- and a report that reprimanded each one for having no goal
        # would be twenty lines of nagging.
        sessions = [a_session(cwd="/home/you/api", sid="s1"),
                    a_session(cwd="/home/you/gate-1", sid="s2"),
                    a_session(cwd="/home/you/gate-1", sid="s3"),
                    a_session(cwd="/home/you/gate-2", sid="s4")]
        page = render(sessions, an_answer(
            "PROJECT: api", "STATUS: in progress", "SAID: some landed."),
            goals=a_goal("/home/you/api", "Fix the parser."))
        # 3 sessions, 2 projects: the line counts sessions, not project names.
        self.assertIn("Plus 3 sessions across 2 projects", page, page)
        self.assertIn("no goals declared there.", page, page)
        self.assertNotIn("gate-1", page, page)

    def test_the_footer_carries_the_figures_and_only_the_figures(self):
        page = render([a_session(sid="s1", source="claude",
                                 written=["/home/you/api/a.py"]),
                       a_session(sid="s2", source="codex",
                                 commands=["ls"], failed=["make lint"])],
                      an_answer("PROJECT: api", "STATUS: none",
                                "SAID: it went in."))
        self.assertIn("  " + "─" * (brief.WIDTH - 2), page, page)
        tail = page.split("─" * (brief.WIDTH - 2))[1]
        self.assertIn("2 sessions", tail, page)
        self.assertIn("1 claude, 1 codex", tail, page)
        self.assertIn("1 file edited", tail, page)
        self.assertIn("1 error", tail, page)
        self.assertIn("3k tokens", tail, page)

    def test_an_empty_window_says_so_without_asking_a_model(self):
        def refuse(_prompt):
            raise AssertionError("a model was asked about an empty day")
        self.assertIn("no sessions found",
                      brief.render_brief([], "today", ask=refuse))


class TestWhenNoModelAnswers(unittest.TestCase):
    """The page degrades; it does not disappear."""

    def page(self, goals=None):
        def missing(_prompt):
            raise NoModel("the claude command is not on PATH")
        return brief.render_brief(
            [a_session(commands=['git commit -m "Fix the parser"',
                                 "git push origin main"],
                       failed=["make lint"],
                       written=["/home/you/api/parser.py"])],
            "today", ask=missing, goals=goals)

    def test_it_says_what_is_missing_and_why(self):
        self.assertIn("no summary: the claude command is not on PATH",
                      self.page())

    def test_the_facts_are_all_still_there(self):
        page = self.page()
        for expected in ("api", "1 session", "committed: Fix the parser",
                         "pushed", "make lint"):
            self.assertIn(expected, page, page)

    def test_the_declared_goal_is_still_quoted(self):
        page = self.page(goals=a_goal("/home/you/api",
                                      "Fix the parser; done when green."))
        self.assertIn('"Fix the parser; done when green."', page, page)

    def test_it_falls_back_to_the_ask_only_when_nothing_else_says_why(self):
        # With outcomes to show, the prompt stays off the page -- that is the
        # point of this view.  With a declared goal, the goal says what the
        # work was for.  Only with neither is the ask the last thing left.
        def missing(_prompt):
            raise NoModel("no model")
        finished = brief.render_brief(
            [a_session(commands=["git push origin main"])], "today",
            ask=missing)
        self.assertNotIn("get the parser fixed", finished, finished)
        with_goal = brief.render_brief(
            [a_session(commands=["ls"])], "today", ask=missing,
            goals=a_goal("/home/you/api", "Fix the parser."))
        self.assertNotIn("get the parser fixed", with_goal, with_goal)
        nothing = brief.render_brief([a_session(commands=["ls"])], "today",
                                     ask=missing)
        self.assertIn("get the parser fixed", nothing, nothing)


class TestWhatIsPutToTheModel(unittest.TestCase):
    """The prompt is the other half of this feature, so it is read directly."""

    def question(self, sessions, goals=None):
        return brief.the_question(brief.facts_by_project(sessions), "today",
                                  goals)

    def test_it_carries_the_evidence_a_judgement_needs(self):
        q = self.question([a_session(
            commands=['git commit -m "Fix the parser"'],
            written=["/home/you/api/parser.py"],
            failed=["make lint"])])
        for expected in ("project: api", "get the parser fixed",
                         "committed: Fix the parser", "parser.py", "make lint"):
            self.assertIn(expected, q, q)

    def test_it_carries_each_declared_goal_and_how_to_judge_by_it(self):
        q = self.question([a_session()],
                          goals=a_goal("/home/you/api",
                                       "Fix the parser. Why: it drops rows."))
        self.assertIn("declared goal: Fix the parser. Why: it drops rows.",
                      q, q)
        self.assertIn("judge those projects against their goal", q, q)
        # and the reason convention is explained rather than assumed
        self.assertIn('after "Why:"', q, q)

    def test_it_asks_for_no_counts(self):
        # Because any count it wrote would be a number nobody checked.
        q = self.question([a_session()])
        self.assertIn("Write no counts of sessions", q)

    def test_it_asks_for_the_waiting_line_to_be_earned(self):
        q = self.question([a_session()])
        self.assertIn("A next step\n  an agent could take is not WAITING", q)

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
