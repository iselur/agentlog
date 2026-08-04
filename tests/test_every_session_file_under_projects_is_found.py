"""Session files are found at whatever depth they are sitting at.

Claude Code writes `~/.claude/projects/<slug>/<uuid>.jsonl`, one directory
down, and every fixture in this suite is built at exactly that depth.  So the
search that finds them — `glob("**/*.jsonl", recursive=True)` — was only ever
asked the one question it could not get wrong: without `recursive=True`, `**`
degrades to a plain `*` and still matches one level.  A mutation sweep turned
the flag off and the whole suite stayed green.

Anything else on disk was therefore unsearched, and the layout is not ours to
depend on.  It is written by somebody else's program, it has changed before,
and people move these files around: an archive folder inside a project, a
`projects/backup-2026-07/` holding last month's, a session copied to the top of
`projects/` to be looked at.  Each of those is a file that exists, contains a
day's work, and would silently not be in the digest.

Silently is the word that matters.  A session that is not found is not an
error — it is a smaller number, and there is nothing on screen to say a number
is smaller than it should be.
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

from agentlog.parser import find_sessions  # noqa: E402
from tests.fixtures import claude_assistant, claude_user  # noqa: E402

STAMP = "2026-08-04T10:00:00.000Z"
CWD = "/home/you/api"


class TestEverySessionFileUnderProjectsIsFound(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="al-depth-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.projects = os.path.join(self.home, ".claude", "projects")

    def write(self, relative_dir, session_id):
        """One complete session file at a chosen depth under projects/."""
        directory = os.path.join(self.projects, relative_dir) \
            if relative_dir else self.projects
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "{}.jsonl".format(session_id))
        records = [
            claude_user(session_id, STAMP, cwd=CWD, text="do the thing"),
            claude_assistant(session_id, STAMP),
        ]
        with open(path, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return path

    def ids_found(self):
        sessions, _sources, _unusable = find_sessions(self.home)
        return {s["id"] for s in sessions}

    def test_the_ordinary_layout_is_found(self):
        # The vacuity guard: everything below is "and this one too", so a
        # search that found nothing at all would pass them by being empty.
        self.write("-home-you-api", "sess-one-level")
        self.assertEqual(self.ids_found(), {"sess-one-level"})

    def test_a_session_file_sitting_directly_in_projects_is_found(self):
        self.write("-home-you-api", "sess-one-level")
        self.write("", "sess-at-the-top")
        self.assertIn("sess-at-the-top", self.ids_found(),
                      "a session file at the top of projects/ was not read")

    def test_a_session_file_in_a_subfolder_of_a_project_is_found(self):
        self.write("-home-you-api", "sess-one-level")
        self.write(os.path.join("-home-you-api", "archive"), "sess-two-levels")
        self.assertIn("sess-two-levels", self.ids_found(),
                      "a session file one folder deeper was not read")

    def test_a_folder_of_last_months_projects_is_found(self):
        # The realistic version of the same thing: somebody tidied up.
        self.write("-home-you-api", "sess-one-level")
        self.write(os.path.join("backup-2026-07", "-home-you-api"),
                   "sess-archived")
        self.assertIn("sess-archived", self.ids_found(),
                      "an archived project folder was not read")

    def test_all_of_them_at_once(self):
        # Depth is not meant to change anything about a session, so a digest
        # over a tree with files at four depths is a digest over four
        # sessions.
        self.write("", "a")
        self.write("-home-you-api", "b")
        self.write(os.path.join("-home-you-api", "archive"), "c")
        self.write(os.path.join("old", "-home-you-api", "archive"), "d")
        self.assertEqual(self.ids_found(), {"a", "b", "c", "d"})


if __name__ == "__main__":
    unittest.main()
