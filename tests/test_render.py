"""Tests for agentlog.render — formatting output from session dicts."""

import json
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentlog.clock import duration as _fmt_duration
from agentlog.terminal import display_width
from agentlog.render import (
    _busiest_hour,
    _cmd_headline,
    group_by_project,
    render_digest,
    render_json,
    render_list,
    render_markdown,
    render_show,
    render_text,
    summary_line,
)


def _make_session(**overrides) -> dict:
    """Return a minimal but valid session dict."""
    base = {
        "id": "abc12345-0000-0000-0000-000000000000",
        "source": "claude",
        "project": "/home/test/myproject",
        "project_name": "myproject",
        "start": datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc),
        "end": datetime(2026, 7, 16, 11, 30, 0, tzinfo=timezone.utc),
        "duration_s": 5400.0,
        "models": ["claude-test"],
        "user_turns": 5,
        "files_read": ["/home/test/myproject/src/app.py"],
        "files_written": ["/home/test/myproject/src/app.py"],
        "commands": ["python3 -m pytest", "git status"],
        "errors": 0,
        "tokens_in": 5000,
        "tokens_out": 1500,
        "ai_title": "fix the auth bug",
        "version": "2.1.0",
        "skipped_lines": 0,
    }
    base.update(overrides)
    return base


class TestFmtDuration(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(_fmt_duration(45), "45s")

    def test_minutes(self):
        self.assertEqual(_fmt_duration(125), "2m 05s")

    def test_hours(self):
        self.assertEqual(_fmt_duration(3720), "1h 02m")

    def test_none(self):
        self.assertEqual(_fmt_duration(None), "?")

    def test_zero(self):
        self.assertEqual(_fmt_duration(0), "0s")


class TestSummaryLine(unittest.TestCase):
    def test_empty(self):
        result = summary_line([])
        self.assertIn("0 sessions", result)

    def test_single_session(self):
        sess = _make_session(duration_s=3600)
        result = summary_line([sess])
        self.assertIn("1 session", result)
        # singular form
        self.assertNotIn("1 sessions", result)

    def test_multiple_sessions(self):
        sessions = [_make_session(duration_s=1800), _make_session(duration_s=900)]
        result = summary_line(sessions)
        self.assertIn("2 sessions", result)

    def test_errors_shown(self):
        sess = _make_session(errors=3)
        result = summary_line([sess])
        self.assertIn("error", result)


class TestRenderText(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(render_text([]), "")

    def test_contains_project_name(self):
        sess = _make_session()
        result = render_text([sess])
        self.assertIn("myproject", result)

    def test_contains_command(self):
        sess = _make_session(commands=["pytest"])
        result = render_text([sess])
        self.assertIn("pytest", result)

    def test_verbose_shows_skipped(self):
        sess = _make_session(skipped_lines=7)
        result = render_text([sess], verbose=True)
        self.assertIn("7", result)

    def test_no_verbose_hides_zero_skipped(self):
        sess = _make_session(skipped_lines=0)
        result = render_text([sess], verbose=False)
        self.assertNotIn("skipped", result)

    def test_file_truncation(self):
        """More than 6 files should show a '... and N more' line."""
        many_files = [f"/tmp/file{i}.py" for i in range(20)]
        sess = _make_session(files_read=many_files, files_written=[])
        result = render_text([sess])
        self.assertIn("more", result)


class TestRenderList(unittest.TestCase):
    def test_empty(self):
        result = render_list([])
        self.assertIn("no sessions", result)

    def test_header_present(self):
        sessions = [_make_session()]
        result = render_list(sessions)
        self.assertIn("PROJECT", result)
        self.assertIn("WHEN", result)

    def test_session_id_truncated(self):
        sess = _make_session()
        result = render_list([sess])
        # First 8 chars of id should appear
        self.assertIn("abc12345", result)


class TestRenderShow(unittest.TestCase):
    def test_contains_all_key_fields(self):
        sess = _make_session()
        result = render_show(sess)
        self.assertIn("session", result)
        self.assertIn("project", result)
        self.assertIn("duration", result)
        self.assertIn("errors", result)

    def test_files_listed(self):
        sess = _make_session(
            files_read=["/tmp/a.py", "/tmp/b.py"],
            files_written=["/tmp/c.py"],
        )
        result = render_show(sess)
        self.assertIn("/tmp/a.py", result)
        self.assertIn("/tmp/c.py", result)

    def test_commands_listed(self):
        sess = _make_session(commands=["make build"])
        result = render_show(sess)
        self.assertIn("make build", result)


class TestRenderMarkdown(unittest.TestCase):
    def test_has_heading(self):
        result = render_markdown([_make_session()])
        self.assertIn("# agentlog", result)

    def test_has_session_project(self):
        sess = _make_session()
        result = render_markdown([sess])
        self.assertIn("myproject", result)


class TestRenderJson(unittest.TestCase):
    def test_valid_json(self):
        sessions = [_make_session()]
        result = render_json(sessions)
        data = json.loads(result)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["project_name"], "myproject")

    def test_datetimes_serialized(self):
        sess = _make_session()
        result = render_json([sess])
        data = json.loads(result)
        self.assertIsInstance(data[0]["start"], str)

    def test_empty_list(self):
        result = render_json([])
        self.assertEqual(json.loads(result), [])

    def test_none_timestamps(self):
        sess = _make_session(start=None, end=None)
        result = render_json([sess])
        data = json.loads(result)
        self.assertIsNone(data[0]["start"])


class TestCmdHeadline(unittest.TestCase):
    """A failing command has to be recognisable in one line."""

    def test_single_line_passes_through(self):
        self.assertEqual(_cmd_headline("git status"), "git status")

    def test_multi_line_keeps_first_line_and_marks_it(self):
        head = _cmd_headline("python3 - <<'EOF'\nimport os\nprint(1)\nEOF")
        self.assertEqual(head, "python3 - <<'EOF' …")

    def test_blank_leading_lines_are_skipped(self):
        self.assertEqual(_cmd_headline("\n\n  make test  "), "make test")

    def test_long_line_is_truncated(self):
        # Ten cells means ten cells: the mark comes out of the width rather
        # than being added once the cutting is done.  A width is a promise
        # about the row the text goes in, and a mark added after the cut
        # breaks that promise by exactly the width of the mark -- which is
        # how a row that fits becomes a row that wraps.
        head = _cmd_headline("x" * 200, width=10)
        self.assertEqual(head, "x" * 9 + "…")
        self.assertEqual(display_width(head), 10)

    def test_empty_command(self):
        self.assertEqual(_cmd_headline("   \n  "), "")


class TestTheEditedRowFitsTheDigest(unittest.TestCase):
    """How a path is written is `which_file.py`; how much room it gets is here.

    The row used to allow each name 34 characters and then not hold it to
    them, so three deep paths ran past the edge of an 80-column terminal --
    directly under the project row, which is measured to the cell.  See
    `test_the_way_a_file_path_is_written.py` for the spelling itself.
    """

    def _digest(self, files):
        at = datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc)
        return render_digest([{
            "id": "s1", "project": "/home/test/proj", "project_name": "proj",
            "start": at, "end": at, "win_start": at, "win_end": at,
            "files_read": [], "files_written": files, "commands": [],
            "errors": 0, "models": [], "user_turns": 1, "source": "claude",
            "active_spans": [(at, at)],
        }])

    def test_three_deep_paths_still_fit_the_row(self):
        deep = ["/home/test/proj/" + "nested/" * 8 + "file{}.py".format(i)
                for i in range(3)]
        row = [ln for ln in self._digest(deep).splitlines()
               if ln.startswith("      edited")][0]
        self.assertLessEqual(display_width(row), 80, row)
        self.assertEqual(row.count(","), 2, row)

    def test_one_file_gets_the_whole_row_rather_than_a_third_of_it(self):
        one = ["/home/test/proj/" + "nested/" * 8 + "file.py"]
        row = [ln for ln in self._digest(one).splitlines()
               if ln.startswith("      edited")][0]
        self.assertLessEqual(display_width(row), 80, row)
        # Room for more of it than any of the three above got.
        self.assertGreater(display_width(row), 60, row)

    def test_a_short_name_is_left_alone(self):
        row = [ln for ln in self._digest(["/home/test/proj/a.py"]).splitlines()
               if ln.startswith("      edited")][0]
        self.assertEqual(row, "      edited   a.py")


class TestBusiestHour(unittest.TestCase):

    def _sess_with_events(self, hours):
        events = [
            (datetime(2026, 7, 16, h, 0, tzinfo=timezone.utc).astimezone(), "cmd", "x")
            for h in hours
        ]
        return _make_session(events=events)

    def test_none_without_events(self):
        self.assertIsNone(_busiest_hour([_make_session()]))

    def test_picks_the_fullest_hour(self):
        sess = self._sess_with_events([9, 14, 14, 14, 20])
        hour = _busiest_hour([sess])
        expected = datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc).astimezone().hour
        self.assertEqual(hour, f"{expected:02d}:00–{(expected + 1) % 24:02d}:00")

    def test_turn_events_do_not_count(self):
        ts = datetime(2026, 7, 16, 3, 0, tzinfo=timezone.utc).astimezone()
        sess = _make_session(events=[(ts, "turn", ""), (ts, "turn", "")])
        self.assertIsNone(_busiest_hour([sess]))


class TestGroupByProject(unittest.TestCase):

    def test_sessions_in_the_same_project_merge(self):
        a = _make_session(id="a", commands=["one"], errors=1)
        b = _make_session(id="b", commands=["two", "three"], errors=2)
        groups = group_by_project([a, b])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["name"], "myproject")
        self.assertEqual(groups[0]["sessions"], [a, b])
        self.assertEqual(groups[0]["commands"], 3)
        self.assertEqual(groups[0]["errors"], 3)

    def test_busiest_project_comes_first(self):
        quiet = _make_session(
            project="/p/quiet",
            project_name="quiet",
            start=datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 16, 10, 5, tzinfo=timezone.utc),
        )
        busy = _make_session(
            project="/p/busy",
            project_name="busy",
            start=datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 16, 13, 0, tzinfo=timezone.utc),
        )
        names = [g["name"] for g in group_by_project([quiet, busy])]
        self.assertEqual(names, ["busy", "quiet"])

    def test_files_are_deduplicated_across_sessions(self):
        a = _make_session(id="a", files_written=["/p/x.py", "/p/y.py"])
        b = _make_session(id="b", files_written=["/p/x.py"])
        self.assertEqual(group_by_project([a, b])[0]["files"], 2)

    def test_top_files_rank_by_edit_count(self):
        sess = _make_session(
            files_written=["/home/test/myproject/rare.py", "/home/test/myproject/hot.py"],
            write_counts={
                "/home/test/myproject/rare.py": 1,
                "/home/test/myproject/hot.py": 7,
            },
        )
        top = group_by_project([sess])[0]["top_files"]
        self.assertEqual(top[0], "/home/test/myproject/hot.py")

    def test_files_written_are_used_when_write_counts_is_absent(self):
        sess = _make_session(files_written=["/p/a.py", "/p/b.py"])
        top = group_by_project([sess])[0]["top_files"]
        self.assertEqual(sorted(top), ["/p/a.py", "/p/b.py"])

    def test_failed_commands_are_counted(self):
        a = _make_session(id="a", failed_cmds=["make", "make", ""])
        b = _make_session(id="b", failed_cmds=["make", "pytest"])
        top = group_by_project([a, b])[0]["top_failed"]
        self.assertEqual(top, [("make", 3), ("pytest", 1)])


class TestRenderDigest(unittest.TestCase):

    def test_empty(self):
        self.assertIn("nothing recorded", render_digest([]))

    def test_headline_names_the_period_and_project_count(self):
        out = render_digest([_make_session()], "week")
        self.assertIn("1 project ", out)
        self.assertIn("the last 7 days", out)

    def test_project_row_lists_stats(self):
        out = render_digest([_make_session(errors=2)])
        self.assertIn("myproject", out)
        self.assertIn("1 file", out)
        self.assertIn("2 commands", out)
        self.assertIn("2 errors", out)

    def test_quiet_project_says_so_instead_of_printing_zeroes(self):
        out = render_digest(
            [_make_session(files_written=[], commands=[], errors=0)]
        )
        self.assertIn("no edits or commands recorded", out)
        self.assertNotIn("0 commands", out)

    def test_edited_files_are_shown_relative_to_the_project(self):
        out = render_digest([_make_session()])
        self.assertIn("edited   src/app.py", out)

    def test_failed_commands_are_named(self):
        out = render_digest([_make_session(failed_cmds=["python3 -m pytest"])])
        self.assertIn("failed   python3 -m pytest", out)

    def test_identical_headlines_collapse_with_a_count(self):
        sess = _make_session(
            failed_cmds=["python3 - <<'EOF'\nimport a\nEOF", "python3 - <<'EOF'\nimport b\nEOF"]
        )
        out = render_digest([sess])
        self.assertIn("python3 - <<'EOF' …  (2x)", out)
        self.assertEqual(out.count("python3 - <<'EOF'"), 1)

    def test_at_most_three_failures_per_project(self):
        sess = _make_session(failed_cmds=[f"cmd{i}" for i in range(9)])
        out = render_digest([sess])
        self.assertEqual(sum(1 for ln in out.splitlines() if "cmd" in ln), 3)

    def test_project_list_is_capped(self):
        sessions = [
            _make_session(id=str(i), project=f"/p/{i}", project_name=f"p{i}")
            for i in range(5)
        ]
        out = render_digest(sessions, max_projects=2)
        self.assertIn("… and 3 more projects", out)

    def test_footer_counts_sessions_by_source(self):
        out = render_digest([_make_session(id="a"), _make_session(id="b", source="codex")])
        self.assertIn("2 sessions", out)
        self.assertIn("1 claude, 1 codex", out)

    def test_single_source_is_not_broken_out(self):
        out = render_digest([_make_session()])
        self.assertIn("1 session", out)
        self.assertNotIn("1 claude", out)

    def test_overlap_note_appears_when_projects_run_in_parallel(self):
        a = _make_session(id="a", project="/p/a", project_name="a")
        b = _make_session(id="b", project="/p/b", project_name="b")
        self.assertIn("projects overlap", render_digest([a, b]))

    def test_no_overlap_note_when_projects_ran_back_to_back(self):
        a = _make_session(
            id="a",
            project="/p/a",
            project_name="a",
            start=datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 16, 11, 0, tzinfo=timezone.utc),
        )
        b = _make_session(
            id="b",
            project="/p/b",
            project_name="b",
            start=datetime(2026, 7, 16, 11, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        )
        self.assertNotIn("projects overlap", render_digest([a, b]))

    def test_verbose_reports_skipped_lines(self):
        out = render_digest([_make_session(skipped_lines=4)], verbose=True)
        self.assertIn("skipped 4 unparseable lines", out)

    def test_no_message_text_leaks(self):
        out = render_digest([_make_session(ai_title="fix the auth bug")])
        self.assertNotIn("fix the auth bug", out)


class TestGroupedDocuments(unittest.TestCase):
    """Markdown and HTML follow the terminal view: project first."""

    def _two_projects(self):
        a = _make_session(
            id="a1", project="/p/alpha", project_name="alpha",
            start=datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 16, 10, 10, tzinfo=timezone.utc),
        )
        b = _make_session(
            id="b1", project="/p/beta", project_name="beta",
            start=datetime(2026, 7, 16, 11, 0, tzinfo=timezone.utc),
            end=datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc),
        )
        return [a, b]

    def test_markdown_has_one_heading_per_project(self):
        md = render_markdown(self._two_projects())
        self.assertEqual(md.count("## alpha"), 1)
        self.assertEqual(md.count("## beta"), 1)

    def test_markdown_puts_the_busiest_project_first(self):
        md = render_markdown(self._two_projects())
        self.assertLess(md.index("## beta"), md.index("## alpha"))

    def test_markdown_sessions_sit_under_their_project(self):
        md = render_markdown(self._two_projects())
        self.assertIn("### `", md)
        self.assertLess(md.index("## beta"), md.index("### `"))

    def test_markdown_project_line_carries_the_stats(self):
        md = render_markdown([_make_session(errors=3)])
        self.assertIn("1 file", md)
        self.assertIn("2 commands", md)
        self.assertIn("3 errors", md)

    def test_markdown_two_sessions_in_one_project_share_a_heading(self):
        a = _make_session(id="a1")
        b = _make_session(id="b1")
        md = render_markdown([a, b])
        self.assertEqual(md.count("## myproject"), 1)
        self.assertEqual(md.count("### `"), 2)

    def test_html_has_a_project_section_per_project(self):
        from agentlog.html import render_html
        page = render_html(self._two_projects(), ["claude"], "today")
        self.assertEqual(page.count('class="project-header"'), 2)
        self.assertLess(page.index(">beta<"), page.index(">alpha<"))

    def test_html_is_self_contained(self):
        # Self-contained means the page fetches nothing when it is opened: the
        # digest is read on machines that are offline, and a stylesheet that
        # silently fails to load is a page that renders as unstyled text.
        #
        # What that rules out is loading, not linking.  The footer links to the
        # project on GitHub and should; a reader clicking it is not the page
        # reaching out on its own.  So this checks the constructs that fetch --
        # and `http://` besides, which has no business here in any position.
        #
        # Written as a skipped check for `http://` once, which read as three
        # assertions and made one.
        from agentlog.html import render_html
        page = render_html(self._two_projects(), ["claude"], "today")
        for fetches in ("<script", "<link", "src=", "@import", "url(",
                        "http://"):
            self.assertNotIn(
                fetches, page,
                "the digest is opened offline; {!r} makes it reach for "
                "something it will not get".format(fetches))
        self.assertIn("<style>", page)

    def test_html_reports_the_running_version(self):
        from agentlog import __version__
        from agentlog.html import render_html
        page = render_html([_make_session()], ["claude"], "today")
        self.assertIn(__version__, page)

    def test_html_escapes_project_names(self):
        from agentlog.html import render_html
        sess = _make_session(project="/p/<script>", project_name="<script>")
        page = render_html([sess], ["claude"], "today")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_html_with_no_sessions(self):
        from agentlog.html import render_html
        page = render_html([], [], "today")
        self.assertIn("No sessions found", page)


def _columns(text: str) -> int:
    """How many terminal cells a string occupies.

    Stated here rather than imported, so this is a claim about terminals and not
    a restatement of whatever ``render`` happens to do.  CJK is drawn two cells
    wide; a combining mark sits on the character before it and takes none.
    """
    import unicodedata
    total = 0
    for char in text:
        if unicodedata.category(char) in ("Mn", "Me"):
            continue
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


class TestColumnsAreCellsNotCharacters(unittest.TestCase):
    """A table padded with ``ljust`` is padded in characters.

    Every column here is read by eye, which reads cells.  A project named in
    Japanese is drawn twice as wide as it is long, so the row after it starts
    somewhere else and the table stops being a table.
    """

    def test_the_digest_project_column_lines_up(self):
        sessions = [
            _make_session(id="a" * 36, project="/p/api", project_name="api"),
            _make_session(id="b" * 36, project="/p/jp",
                          project_name="日本語プロジェクト"),
        ]
        rows = [ln for ln in render_digest(sessions).splitlines()
                if "1 file" in ln]
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual(len({_columns(ln.split("1 file")[0]) for ln in rows}),
                         1, rows)

    def test_the_sessions_table_lines_up(self):
        sessions = [
            _make_session(id="a" * 36, project_name="api"),
            _make_session(id="b" * 36, project_name="日本語プロジェクト"),
            _make_session(id="c" * 36, project_name="web"),
        ]
        body = render_list(sessions).splitlines()[2:]
        starts = {_columns(row.split("2026-")[0]) for row in body}
        self.assertEqual(len(starts), 1, body)

    def test_a_name_with_a_character_a_terminal_obeys_still_lines_up(self):
        # The regression this table had for as long as it has existed.  The
        # column is measured from the value, the whole table is sanitised in one
        # go at the end, and sanitising used to *delete* -- so a name holding a
        # character a terminal obeys was counted as one cell, given one cell,
        # and then had that cell taken away again, and that row alone ended a
        # cell to the left of every other.  Nothing caught it; every test that
        # laid out a table used names made of letters.
        sessions = [
            _make_session(id="a" * 36, project_name="api"),
            _make_session(id="b" * 36, project_name="ap\x1bi"),
            _make_session(id="c" * 36, project_name="web"),
        ]
        body = render_list(sessions).splitlines()[2:]
        starts = {_columns(row.split("2026-")[0]) for row in body}
        self.assertEqual(len(starts), 1, body)

    def test_a_wide_name_is_cut_to_the_column_not_past_it(self):
        # Twenty-four characters of Japanese is forty-eight cells; left uncut it
        # pushes every column after it half a table to the right.
        sessions = [_make_session(project_name="日" * 40)]
        row = render_list(sessions).splitlines()[2]
        self.assertLessEqual(_columns(row.split("2026-")[0]),
                             _columns(render_list(
                                 [_make_session(project_name="x")]
                             ).splitlines()[2].split("2026-")[0]))
