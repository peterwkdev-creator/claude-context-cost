"""Which git version of each instruction file a session loaded: synthetic repositories, fixed dates.

Each repository is built with git and fixed names and dates, so its commit hashes
are the same on every machine; the README example is this output.
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from claude_context_cost import loaded_versions
from claude_context_cost.cli import main, print_versions

HAS_GIT = shutil.which("git") is not None


class Repo:
    """A git repository and a transcript of one session that loaded files from it."""

    def __init__(self, tmp):
        self.root = Path(tmp) / "repo"
        self.root.mkdir()
        self.config = Path(tmp) / "gitconfig"   # no global or system setting changes a hash
        self.config.write_text("", encoding="utf-8")
        self.git("init", "-q")
        self.lines = []

    def git(self, *args, date="2026-10-01T12:00:00+00:00"):
        env = {**os.environ, "GIT_CONFIG_GLOBAL": str(self.config), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "Example", "GIT_AUTHOR_EMAIL": "example@example.com",
               "GIT_COMMITTER_NAME": "Example", "GIT_COMMITTER_EMAIL": "example@example.com",
               "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        subprocess.run(["git", "-C", str(self.root), *args], env=env, check=True, capture_output=True)

    def write(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
        return p

    def commit(self, date):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"change of {date[:10]}", date=date)

    def load(self, when, path, text, start=True, kind="Project"):
        if start:
            att = {"type": "instructions", "files": [{"path": str(path), "type": kind, "content": text}]}
        else:
            att = {"type": "nested_memory", "path": str(path),
                   "content": {"path": str(path), "content": text, "globs": ["src/**"]}}
        self.lines.append({"type": "attachment", "timestamp": when, "cwd": str(self.root),
                           "rendered": text, "attachment": att})

    def transcript(self):
        p = self.root.parent / "session.jsonl"
        p.write_text("".join(json.dumps(x) + "\n" for x in self.lines), encoding="utf-8")
        return p


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestLoadedVersions(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.r = Repo(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def versions(self):
        return loaded_versions(self.r.transcript(), 2.0)

    def test_the_commit_before_the_load_is_found_and_today_is_compared(self):
        claude = self.r.write("CLAUDE.md", "First rules.\n")
        self.r.commit("2026-10-01T12:00:00+00:00")
        self.r.write("CLAUDE.md", "Second rules, longer.\n")
        self.r.commit("2026-10-05T12:00:00+00:00")
        self.r.load("2026-10-03T00:00:00Z", claude, "First rules.")
        self.r.load("2026-10-06T00:00:00Z", claude, "Second rules, longer.")
        first, second = self.versions()
        self.assertEqual((first.commit_date, first.committed_after, first.today, first.today_bytes,
                          first.today_tokens, first.bytes, first.tokens),
                         ("2026-10-01", False, "changed", 9, 4, 12, 6))
        self.assertEqual((second.commit_date, second.today, second.today_bytes), ("2026-10-05", "same", 0))
        self.assertEqual(len(first.commit), 40)
        self.assertNotEqual(first.commit, second.commit)

    @unittest.skipUnless(os.name == "nt", "Windows short names")
    def test_a_path_with_a_windows_short_name_is_found(self):
        # the CI runner's temporary folder is C:\Users\RUNNER~1\...: git names it in full
        import ctypes
        buf = ctypes.create_unicode_buffer(1000)
        ctypes.windll.kernel32.GetShortPathNameW(self.tmp.name, buf, 1000)
        if buf.value in ("", self.tmp.name):
            self.skipTest("this volume has no short names")
        self.r.write("CLAUDE.md", "Rules.\n")
        self.r.commit("2026-10-01T12:00:00+00:00")
        self.r.load("2026-10-02T00:00:00Z", os.path.join(buf.value, "repo", "CLAUDE.md"), "Rules.")
        [v] = self.versions()
        self.assertEqual((v.git, v.commit_date, v.today), (True, "2026-10-01", "same"))

    def test_the_same_text_twice_is_one_row_with_two_loads(self):
        claude = self.r.write("CLAUDE.md", "Rules.\n")
        self.r.commit("2026-10-01T12:00:00+00:00")
        self.r.load("2026-10-02T00:00:00Z", claude, "Rules.")
        self.r.load("2026-10-02T01:00:00Z", claude, "Rules.")
        vs = self.versions()
        self.assertEqual(len(vs), 1)
        self.assertEqual((vs[0].loads, vs[0].loaded), (2, "2026-10-02T00:00:00+00:00"))

    def test_a_text_no_commit_has_is_not_committed(self):
        claude = self.r.write("CLAUDE.md", "Rules.\n")
        self.r.commit("2026-10-01T12:00:00+00:00")
        self.r.load("2026-10-02T00:00:00Z", claude, "Rules, edited and never committed.")
        [v] = self.versions()
        self.assertEqual((v.git, v.commit, v.commit_date), (True, "", ""))

    def test_a_text_committed_only_after_the_load_is_marked_later(self):
        claude = self.r.write("CLAUDE.md", "Old.\n")
        self.r.commit("2026-10-01T12:00:00+00:00")
        self.r.write("CLAUDE.md", "New.\n")
        self.r.commit("2026-10-05T12:00:00+00:00")
        self.r.write("CLAUDE.md", "Newer.\n")
        self.r.commit("2026-10-07T12:00:00+00:00")
        self.r.write("CLAUDE.md", "New.\n")   # committed again: the first commit after the load is the one
        self.r.commit("2026-10-09T12:00:00+00:00")
        self.r.load("2026-10-03T00:00:00Z", claude, "New.")
        [v] = self.versions()
        self.assertEqual((v.commit_date, v.committed_after), ("2026-10-05", True))

    def test_when_the_text_comes_back_the_latest_commit_before_the_load_wins(self):
        claude = self.r.write("CLAUDE.md", "A.\n")
        self.r.commit("2026-10-01T12:00:00+00:00")
        self.r.write("CLAUDE.md", "B.\n")
        self.r.commit("2026-10-02T12:00:00+00:00")
        self.r.write("CLAUDE.md", "A.\n")
        self.r.commit("2026-10-03T12:00:00+00:00")
        self.r.write("CLAUDE.md", "A.\n\nC.\n")
        self.r.commit("2026-10-05T12:00:00+00:00")
        self.r.write("CLAUDE.md", "A.\n")   # and again after the load, which it cannot be
        self.r.commit("2026-10-06T12:00:00+00:00")
        self.r.load("2026-10-04T00:00:00Z", claude, "A.")
        [v] = self.versions()
        self.assertEqual((v.commit_date, v.committed_after), ("2026-10-03", False))

    def test_a_deleted_file_is_found_in_git_and_not_found_today(self):
        rule = self.r.write(".claude/rules/api.md", "---\npaths: src/**\n---\nAPI rules.\n")
        self.r.commit("2026-10-01T12:00:00+00:00")
        self.r.git("rm", "-q", "-r", ".claude")
        self.r.commit("2026-10-05T12:00:00+00:00")
        self.r.load("2026-10-02T00:00:00Z", rule, "API rules.\n", start=False)
        [v] = self.versions()
        self.assertEqual((v.kind, v.name, v.commit_date, v.today), ("path rule", ".claude/rules/api.md",
                                                                    "2026-10-01", "not found"))

    def test_rendering_frontmatter_comments_and_line_ends_is_what_matches(self):
        # git holds LF, the session saw the file checked out with CRLF; on demand the end is kept
        rule = self.r.write(".claude/rules/web.md",
                            "---\npaths: web/**\n---\n<!-- note for people -->\n\nWeb rules.\n")
        self.r.commit("2026-10-01T12:00:00+00:00")
        self.r.load("2026-10-02T00:00:00Z", rule, "Web rules.\r\n", start=False)
        [v] = self.versions()
        self.assertEqual(v.commit_date, "2026-10-01")
        self.r.load("2026-10-02T00:00:00Z", rule, "Web rules.", start=False)   # end stripped: not this file
        self.assertEqual(self.versions()[1].commit, "")

    def test_a_file_outside_a_repository_has_no_git(self):
        home = Path(self.tmp.name) / "home" / ".claude"
        home.mkdir(parents=True)
        user = home / "CLAUDE.md"
        user.write_text("Mine.\n", encoding="utf-8")
        self.r.load("2026-10-02T00:00:00Z", user, "Mine.", kind="User")
        [v] = self.versions()
        self.assertEqual((v.name, v.git, v.commit, v.today), ("~/.claude/CLAUDE.md", False, "", "same"))

    def test_only_md_files_are_looked_up(self):
        other = self.r.write("notes.txt", "Text.\n")
        self.r.commit("2026-10-01T12:00:00+00:00")
        self.r.load("2026-10-02T00:00:00Z", other, "Text.")
        [v] = self.versions()
        self.assertEqual((v.git, v.today), (False, ""))

    def test_a_subagent_line_in_a_session_is_not_its_load(self):
        claude = self.r.write("CLAUDE.md", "Rules.\n")
        self.r.commit("2026-10-01T12:00:00+00:00")
        self.r.load("2026-10-02T00:00:00Z", claude, "Rules.")
        self.r.lines.append({"type": "user", "message": {"role": "user", "content": "hi"}})
        side = dict(self.r.lines[0], isSidechain=True)
        side["attachment"] = {"type": "instructions",
                              "files": [{"path": str(claude), "type": "Project", "content": "Sidechain."}]}
        self.r.lines.append(side)
        self.assertEqual([v.loads for v in self.versions()], [1])


@unittest.skipUnless(HAS_GIT, "git is not installed")
class TestVersionsCli(unittest.TestCase):

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(list(args))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_the_readme_example_is_the_real_output(self):
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        shown = re.search(r"```text\n(CLAUDE\.md, rules and memory as.*?)```", readme, re.S).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            r = Repo(tmp)
            home = Path(tmp) / "home" / ".claude"
            home.mkdir(parents=True)
            user = home / "CLAUDE.md"
            user.write_text("Answer in English. " * 40 + "\n", encoding="utf-8")
            claude = r.write("CLAUDE.md", "# Project\n" + "House rules. " * 120 + "\n")
            api = r.write(".claude/rules/api.md", "---\npaths: src/api/**\n---\n" + "API conventions. " * 90)
            r.commit("2026-10-01T12:00:00+00:00")
            r.write("CLAUDE.md", "# Project\n" + "House rules. " * 150 + "\n")
            r.commit("2026-10-05T12:00:00+00:00")
            style = r.write(".claude/rules/style.md", "Style. " * 80 + "\n")
            tests = r.write(".claude/rules/tests.md", "Test first. " * 30 + "\n")
            for f in (user, claude, style, tests):
                r.load("2026-10-06T09:00:00Z", f, f.read_text(encoding="utf-8").strip(),
                       kind="User" if f == user else "Project")
            r.load("2026-10-06T09:20:00Z", api, "API conventions. " * 90, start=False)
            r.load("2026-10-06T11:00:00Z", api, "API conventions. " * 90, start=False)
            r.write("CLAUDE.md", "# Project\n" + "House rules. " * 200 + "\n")
            r.git("add", "CLAUDE.md", ".claude/rules/tests.md")   # style.md is never committed
            r.git("rm", "-q", ".claude/rules/api.md")
            r.git("commit", "-q", "-m", "change of 2026-10-08", date="2026-10-08T12:00:00+00:00")
            out = io.StringIO()
            print_versions(loaded_versions(r.transcript()), out)
        self.assertEqual(out.getvalue(), shown)

    def test_versions_follows_the_report_and_goes_into_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = Repo(tmp)
            claude = r.write("CLAUDE.md", "Rules.\n")
            r.commit("2026-10-01T12:00:00+00:00")
            r.load("2026-10-02T00:00:00Z", claude, "Rules.")
            t = r.transcript()
            code, out, _ = self.run_cli("--versions", str(t))
            self.assertEqual(code, 0)
            self.assertIn("responses", out.split("CLAUDE.md, rules and memory")[0])
            self.assertRegex(out, r"\n +\d+ +1  [0-9a-f]{7} 2026-10-01 +same +claude\.md: CLAUDE\.md\n")
            code, out, _ = self.run_cli("--versions", "--json", str(t))
            [v] = json.loads(out)["versions"]
            self.assertEqual((v["name"], v["commit_date"], v["today"], v["loads"]),
                             ("CLAUDE.md", "2026-10-01", "same", 1))
            code, out, _ = self.run_cli("--json", str(t))
            self.assertNotIn("versions", json.loads(out))

    def test_versions_on_a_folder_or_with_budget_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self.run_cli("--versions", tmp)
            self.assertEqual(code, 2)
            self.assertIn("need one transcript", err)
            code, _, err = self.run_cli("--versions", "--budget", "b.toml", tmp)
            self.assertEqual(code, 2)
            self.assertIn("--versions", err)


if __name__ == "__main__":
    unittest.main()
