"""The context budget: what a repository loads, measured as Claude Code renders it, held to the limits.

Every repository here is synthetic, written to a temporary folder.
"""
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from claude_context_cost import BudgetError, check_budget
from claude_context_cost.budget import render, scan
from claude_context_cost.cli import main


def write(root, files):
    for name, text in files.items():
        p = Path(root) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))


def by_name(root):
    files, outside = scan(root)
    return {f.name: f for f in files}, outside


class TestRender(unittest.TestCase):

    def test_frontmatter_and_comment_blocks_go_with_the_blank_lines_after_them(self):
        text = "---\npaths: src/**\n---\n\n<!-- note -->\n\n\nKeep\n<!-- two\nlines -->\nthis\n"
        self.assertEqual(render(text), "Keep\nthis")

    def test_a_comment_inside_a_line_stays(self):
        self.assertEqual(render("a <!-- b --> c\n"), "a <!-- b --> c")

    def test_start_up_strips_both_ends_on_demand_only_the_start(self):
        self.assertEqual(render("\n\nbody\n\n", start=True), "body")
        self.assertEqual(render("\n\nbody\n\n", start=False), "body\n\n")

    def test_line_ends_are_kept_unless_a_comment_was_taken_out(self):
        self.assertEqual(render("a\r\nb\r\n"), "a\r\nb")
        self.assertEqual(render("<!-- x -->\r\na\r\nb\r\n"), "a\nb")


class TestScan(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_what_loads_at_start_up_and_what_on_demand(self):
        write(self.root, {
            "CLAUDE.md": "root", ".claude/CLAUDE.md": "inner", "CLAUDE.local.md": "local",
            ".claude/rules/always.md": "---\ndescription: x\n---\nalways",
            ".claude/rules/deep/api.md": "---\npaths:\n  - api/**\n---\napi",
            "src/CLAUDE.md": "sub", "src/deeper/CLAUDE.md": "deeper",
            ".hidden/CLAUDE.md": "no", "node_modules/pkg/CLAUDE.md": "no", "README.md": "no",
        })
        files, _ = by_name(self.root)
        start = {n for n, f in files.items() if f.start}
        later = {n for n, f in files.items() if not f.start}
        self.assertEqual(start, {"CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md", ".claude/rules/always.md"})
        self.assertEqual(later, {".claude/rules/deep/api.md", "src/CLAUDE.md", "src/deeper/CLAUDE.md"})
        kinds = {n: f.kind for n, f in files.items() if n.startswith(".claude/rules/") or n.startswith("src/")}
        self.assertEqual(kinds, {".claude/rules/always.md": "rule", ".claude/rules/deep/api.md": "path rule",
                                 "src/CLAUDE.md": "claude.md", "src/deeper/CLAUDE.md": "claude.md"})

    def test_bytes_are_the_rendered_text_and_tokens_divide_by_the_ratio(self):
        write(self.root, {"CLAUDE.md": "---\nx: 1\n---\n" + "é" * 50 + "\n"})   # 100 bytes once rendered
        files, _ = scan(self.root, bytes_per_token=4)
        self.assertEqual((files[0].bytes, files[0].tokens), (100, 25))

    def test_imports_resolve_from_the_importing_file_and_load_with_it(self):
        write(self.root, {
            "CLAUDE.md": "See @docs/guide.md and @./docs/../notes.md.\n",
            "docs/guide.md": "Guide, then @more.md\n", "docs/more.md": "more",
            "notes.md": "notes",
            ".claude/rules/api.md": "---\npaths: api/**\n---\nsee @../specs/api.md",
            ".claude/specs/api.md": "spec",
        })
        files, _ = by_name(self.root)
        # (loaded at start-up, imported by); a rule loaded on demand brings its imports on demand
        self.assertEqual({n: (f.start, f.imported_by) for n, f in files.items()}, {
            "CLAUDE.md": (True, ""), "docs/guide.md": (True, "CLAUDE.md"),
            "docs/more.md": (True, "docs/guide.md"), "notes.md": (True, "CLAUDE.md"),
            ".claude/rules/api.md": (False, ""), ".claude/specs/api.md": (False, ".claude/rules/api.md"),
        })

    def test_an_import_in_code_is_not_followed(self):
        write(self.root, {"CLAUDE.md": "run `npm i @scope/pkg.md`\n```\n@block.md\n```\n",
                          "scope/pkg.md": "no", "block.md": "no"})
        files, _ = by_name(self.root)
        self.assertEqual(set(files), {"CLAUDE.md"})

    def test_imports_stop_after_five_hops_and_a_cycle_ends(self):
        chain = {"CLAUDE.md": "@f1.md"}
        chain.update({f"f{i}.md": f"@f{i + 1}.md" for i in range(1, 7)})
        chain["f7.md"] = "@CLAUDE.md"
        write(self.root, chain)
        files, _ = by_name(self.root)
        self.assertEqual(set(files), {"CLAUDE.md", "f1.md", "f2.md", "f3.md", "f4.md", "f5.md"})

    def test_an_import_outside_the_repository_is_listed_not_counted(self):
        with tempfile.TemporaryDirectory() as other:
            write(other, {"shared.md": "shared"})
            repo = Path(self.root) / "repo"
            rel = Path("..") / ".." / Path(other).name / "shared.md"
            write(repo, {"CLAUDE.md": f"@~/.claude/mine.md and @{rel.as_posix()}\n"})
            if not (repo / rel).resolve().is_file():
                self.skipTest("the temporary folders are on different drives")
            files, outside = by_name(repo)
        self.assertEqual(set(files), {"CLAUDE.md"})
        self.assertEqual(outside, ["~/.claude/mine.md", rel.as_posix()])


class TestCheckBudget(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, {
            "CLAUDE.md": "x" * 900,                          # 400 tokens at 2.25
            ".claude/rules/a.md": "y" * 450,                 # 200
            ".claude/rules/sub/b.md": "---\npaths: b/**\n---\n" + "z" * 225,   # 100, on demand
            "src/CLAUDE.md": "w" * 45,                       # 20, on demand
        })

    def tearDown(self):
        self.tmp.cleanup()

    def budget(self, text):
        p = self.root / "budget.toml"
        p.write_text(text, encoding="utf-8")
        return check_budget(self.root, p)

    def test_within_the_limits(self):
        b = self.budget('startup = 600\n[limits]\n"CLAUDE.md" = 400\n".claude/rules/**" = 200\n')
        self.assertTrue(b.ok)
        self.assertEqual(b.start_tokens, 600)
        self.assertTrue(b.ratio_is_default)

    def test_a_file_over_its_limit(self):
        b = self.budget('[limits]\n"CLAUDE.md" = 399\n')
        self.assertFalse(b.ok)
        self.assertEqual([(o.name, o.tokens, o.limit, o.pattern) for o in b.over],
                         [("CLAUDE.md", 400, 399, "CLAUDE.md")])

    def test_the_start_up_total_counts_only_what_loads_at_start_up(self):
        b = self.budget("startup = 599\n")
        self.assertEqual([(o.name, o.tokens, o.limit) for o in b.over], [("start-up total", 600, 599)])
        self.assertTrue(self.budget("startup = 600\n").ok)

    def test_a_file_is_held_to_every_pattern_that_matches_it(self):
        # the smaller limit first: the one read last must not replace it
        b = self.budget('[limits]\n".claude/rules/*.md" = 150\n"**/*.md" = 1000\n')
        self.assertEqual([(o.name, o.pattern) for o in b.over], [(".claude/rules/a.md", ".claude/rules/*.md")])
        limits = {f.name: f.limit for f in b.files}
        self.assertEqual(limits[".claude/rules/a.md"], 150)
        self.assertEqual(limits[".claude/rules/sub/b.md"], 1000)

    def test_a_star_stays_in_one_folder(self):
        b = self.budget('[limits]\n".claude/rules/*" = 99\n')
        self.assertEqual([o.name for o in b.over], [".claude/rules/a.md"])
        b = self.budget('[limits]\n"**/CLAUDE.md" = 19\n')
        self.assertEqual(sorted(o.name for o in b.over), ["CLAUDE.md", "src/CLAUDE.md"])

    def test_the_declared_ratio_is_used(self):
        b = self.budget('bytes_per_token = 4.5\n[limits]\n"CLAUDE.md" = 200\n')
        self.assertTrue(b.ok)
        self.assertFalse(b.ratio_is_default)
        self.assertEqual({f.name: f.tokens for f in b.files}["CLAUDE.md"], 200)

    def test_an_invalid_budget_is_an_error_never_a_pass(self):
        cases = {
            '[limits]\n"CLAUDE.mdd" = 400\n': "matches no instruction file",
            'start = 600\n': "unknown key",
            '[limits]\n"CLAUDE.md" = 0\n': "positive",
            '[limits]\n"CLAUDE.md" = true\n': "positive",
            '[limits]\n"CLAUDE.md" = 1.5\n': "positive",
            'bytes_per_token = -1\nstartup = 9\n': "positive",
            '[limits]\nCLAUDE.md = 400\n': "quote the pattern",
            'limits = 3\n': "must be a table",
            'startup = \n': "not valid TOML",
            '# nothing\n': "no limit declared",
        }
        for text, message in cases.items():
            with self.subTest(budget=text):
                with self.assertRaises(BudgetError) as e:
                    self.budget(text)
                self.assertIn(message, str(e.exception))


class TestBudgetCli(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, {"CLAUDE.md": "x" * 900, "docs/CLAUDE.md": "y" * 90})

    def tearDown(self):
        self.tmp.cleanup()

    def run_budget(self, text, *extra):
        (self.root / "budget.toml").write_text(text, encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--budget", str(self.root / "budget.toml"), str(self.root), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        code, out, _ = self.run_budget('startup = 400\n[limits]\n"**/CLAUDE.md" = 400\n')
        self.assertEqual(code, 0)
        self.assertIn("within budget", out)
        code, out, _ = self.run_budget('startup = 399\n')
        self.assertEqual(code, 1)
        self.assertIn("start-up total: 400 tokens > 399 (limit startup)", out)
        code, out, err = self.run_budget('[limits]\n"CLAUDE.txt" = 1\n')
        self.assertEqual((code, out), (2, ""))
        self.assertIn("matches no instruction file", err)

    def test_the_table(self):
        _, out, _ = self.run_budget('[limits]\n"docs/CLAUDE.md" = 39\n')
        self.assertIn("2 instruction files, 2.25 bytes per token (default)", out)
        self.assertIn("      400         -  start-up  claude.md: CLAUDE.md\n", out)
        self.assertIn("       40        39  on demand claude.md: docs/CLAUDE.md  OVER\n", out)
        self.assertIn('  claude.md: docs/CLAUDE.md: 40 tokens > 39 (limit "docs/CLAUDE.md")', out)

    def test_json(self):
        code, out, _ = self.run_budget('startup = 399\n', "--json")
        d = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(set(d), {"budget", "version", "ok", "bytes_per_token", "ratio_is_default", "startup",
                                  "files", "over", "outside"})
        self.assertEqual((d["ok"], d["startup"]), (False, {"tokens": 400, "limit": 399}))
        self.assertEqual(d["files"], [
            {"kind": "claude.md", "name": "CLAUDE.md", "bytes": 900, "tokens": 400, "startup": True,
             "imported_by": None, "limit": None},
            {"kind": "claude.md", "name": "docs/CLAUDE.md", "bytes": 90, "tokens": 40, "startup": False,
             "imported_by": None, "limit": None}])

    def test_the_readme_example_is_the_real_output(self):
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        toml = re.search(r"```toml\n(# context-budget\.toml.*?)```", readme, re.S).group(1)
        shown = re.search(r"```text\n(context budget:.*?)```", readme, re.S).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, {
                "CLAUDE.md": "# Project\n" + "Rules of the house. " * 190 + "\nSee @docs/architecture.md\n",
                "docs/architecture.md": "Architecture notes. " * 120,
                ".claude/rules/style.md": "Style. " * 200,
                ".claude/rules/api.md": "---\npaths: src/api/**\n---\n" + "API conventions. " * 240,
                "web/CLAUDE.md": "Frontend notes. " * 60,
                "context-budget.toml": toml,
            })
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--budget", str(Path(tmp) / "context-budget.toml"), tmp])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), shown)

    def test_the_repository_defaults_to_the_current_folder_and_transcript_options_are_refused(self):
        (self.root / "budget.toml").write_text("startup = 400\n", encoding="utf-8")
        here = os.getcwd()
        os.chdir(self.root)
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--budget", "budget.toml"]), 0)
        finally:
            os.chdir(here)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as e:
            main(["--budget", str(self.root / "budget.toml"), "--example"])
        self.assertEqual(e.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
