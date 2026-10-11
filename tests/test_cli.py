"""The command line, run the way a user runs it."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from claude_context_cost import __version__, example_path
from claude_context_cost.cli import main

ROOT = Path(__file__).resolve().parents[1]


def run_main(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(list(args))
    return code, buf.getvalue()


class TestCli(unittest.TestCase):

    def test_example_table(self):
        code, out = run_main("--example")
        self.assertEqual(code, 0)
        self.assertIn("7 responses, 1 compaction, 159,160 input tokens", out)
        self.assertIn("bytes per token: 2.50 (median of 4", out)
        # Read: 3,200 tokens entered, 8,000 characters -> chars / 4 says 2,000, -38%
        read = next(line for line in out.splitlines() if line.endswith("tool: Read"))
        self.assertEqual(read.split()[:6], ["10,400", "6.5%", "3,200", "4", "2,000", "-38%"])

    def test_steps(self):
        code, out = run_main("--example", "--steps")
        self.assertIn("#4 msg_04 context 25,000", out)
        self.assertIn("+400  path rule: .claude/rules/python.md (1,000 B, split)", out)

    def test_json(self):
        code, out = run_main("--example", "--json")
        data = json.loads(out)
        self.assertEqual(data["total"], 159160)
        self.assertEqual(sum(s["cost"] for s in data["sources"]), 159160)
        self.assertEqual(len(data["steps"]), 7)

    def test_folder_lists_each_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(example_path(), Path(tmp) / "a.jsonl")
            code, out = run_main(tmp)
        self.assertEqual(code, 0)
        self.assertIn("a.jsonl", out)
        self.assertIn("159,160 tokens", out)

    def test_folder_as_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(example_path(), Path(tmp) / "a.jsonl")
            code, out = run_main(tmp, "--json")
        self.assertEqual(code, 0)
        rows = json.loads(out)["transcripts"]
        self.assertEqual([(r["file"], r["responses"], r["total"]) for r in rows], [("a.jsonl", 7, 159160)])
        self.assertEqual(rows[0]["top"]["kind"], "unattributed")

    def test_project_folder_ranks_sources_and_counts_subagents(self):
        from test_acceptance import make_projects
        with tempfile.TemporaryDirectory() as tmp:
            make_projects(Path(tmp))
            code, out = run_main(str(Path(tmp) / "projA"))
        self.assertEqual(code, 0)
        self.assertIn("projA: 2 transcripts and 1 subagent transcript, 21 responses, 477,480 input tokens", out)
        read = next(line for line in out.splitlines() if line.endswith("tool: Read"))
        self.assertEqual(read.split()[:6], ["31,200", "6.5%", "9,600", "3", "6,000", "-38%"])
        lines = [line.split()[0] for line in out.splitlines() if line.startswith("  s")]
        self.assertEqual(lines, ["s2.jsonl", "s1.jsonl"])
        self.assertIn("(+1 subagent, 159,160 tokens)", out)

    def test_folder_of_projects(self):
        from test_acceptance import make_projects
        with tempfile.TemporaryDirectory() as tmp:
            make_projects(Path(tmp))
            code, out = run_main(tmp, "--all")
            _, js = run_main(tmp, "--json")
        self.assertIn("2 projects, 3 transcripts and 1 subagent transcript", out)
        self.assertIn("claude.md: CLAUDE.md  [projB]", out)
        self.assertNotIn("more sources (--all)", out)
        data = json.loads(js)
        self.assertEqual(data["total"], 4 * 159160)
        self.assertEqual(sum(s["cost"] for s in data["sources"]), data["total"])
        self.assertEqual([(p["name"], p["transcripts"], p["subagents"]) for p in data["projects"]],
                         [("projA", 2, 1), ("projB", 1, 0)])
        self.assertEqual([r["session"] for r in data["subagents"]], ["s1"])

    def test_folder_refuses_per_transcript_options(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            shutil.copy(example_path(), Path(tmp) / "a.jsonl")
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                main([tmp, "--steps"])

    def test_version_as_a_module(self):
        p = subprocess.run([sys.executable, "-m", "claude_context_cost", "--version"],
                           cwd=ROOT, capture_output=True)
        self.assertEqual(p.stdout.decode().strip(), f"claude-context-cost {__version__}")

    def test_non_ascii_name_on_a_cp1252_console(self):
        line = {"type": "attachment", "cwd": "/home/dev/demo",
                "attachment": {"type": "nested_memory", "path": "/home/dev/demo/.claude/rules/regra-ção.md"},
                "rendered": [{"content": "regra " * 50}]}
        call = {"type": "assistant", "message": {"id": "m1", "content": [], "usage": {"input_tokens": 500}}}
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.jsonl"
            f.write_text(json.dumps(line) + "\n" + json.dumps(call) + "\n", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
            env["PYTHONIOENCODING"] = "cp1252:strict"
            p = subprocess.run([sys.executable, "-m", "claude_context_cost", str(f)],
                               cwd=ROOT, capture_output=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b"path rule: .claude/rules/regra-", p.stdout)


if __name__ == "__main__":
    unittest.main()
