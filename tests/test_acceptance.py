"""Acceptance criteria 1 to 4 of version 0.1, on the synthetic transcript.

Every expected number below is worked out by hand from the story in
`tests/fixtures/build_example.py`, not taken from the program's output.
"""
import unittest
from pathlib import Path

from claude_context_cost import analyze, example_path

HERE = Path(__file__).resolve().parent

USER_MD = ("claude.md", "~/.claude/CLAUDE.md")
PROJECT_MD = ("claude.md", "CLAUDE.md")
RULE = ("rule", ".claude/rules/style.md")
MEMORY = ("memory", "~/.claude/projects/-home-dev-demo/memory/MEMORY.md")
WRAPPER = ("attachment", "instructions wrapper")
PROMPT = ("prompt", "user")
READ = ("tool", "Read")
GREP = ("tool", "Grep")
GLOB = ("tool", "Glob")
BASH = ("tool", "Bash")
PYTHON_RULE = ("path rule", ".claude/rules/python.md")
WEB_RULE = ("path rule", ".claude/rules/web.md")
SUMMARY = ("summary", "compaction")
OUTPUT = ("output", "responses")
KEPT = ("output", "kept by compaction")
FLOOR = ("unattributed", "system prompt, tools, overhead")

CONTEXTS = [20000, 22100, 23150, 25000, 26660, 21060, 21190]

# what is in context at the first response of each segment
START = {USER_MD: 400, PROJECT_MD: 800, RULE: 200, MEMORY: 200, WRAPPER: 40, PROMPT: 40, FLOOR: 18320}
AFTER_COMPACTION = {USER_MD: 400, PROJECT_MD: 800, RULE: 200, MEMORY: 200, WRAPPER: 40, SUMMARY: 600,
                    PYTHON_RULE: 400, KEPT: 100, FLOOR: 18320}

# tokens in context, response by response (m1..m7)
EXPECTED_LEDGERS = [
    START,
    {**START, OUTPUT: 100, READ: 2000},
    {**START, OUTPUT: 150, READ: 2000, GREP: 1000},
    {**START, OUTPUT: 200, READ: 3200, GREP: 1000, PYTHON_RULE: 400, GLOB: 200},
    {**START, OUTPUT: 260, READ: 3200, GREP: 1000, PYTHON_RULE: 400, GLOB: 200, BASH: 1600},
    AFTER_COMPACTION,
    {**AFTER_COMPACTION, OUTPUT: 30, PROMPT: 100},
]

EXPECTED_COST = {
    USER_MD: 2800, PROJECT_MD: 5600, RULE: 1400, MEMORY: 1400, WRAPPER: 280,
    PROMPT: 40 * 5 + 100, FLOOR: 18320 * 7,
    OUTPUT: 100 + 150 + 200 + 260 + 30, KEPT: 200,
    READ: 2000 * 4 + 1200 * 2, GREP: 1000 * 3, GLOB: 200 * 2, BASH: 1600,
    PYTHON_RULE: 400 * 4, SUMMARY: 600 * 2,
}

EXPECTED_ENTERED = {
    USER_MD: 800, PROJECT_MD: 1600, RULE: 400, MEMORY: 400, WRAPPER: 80, PROMPT: 140,
    FLOOR: 18320 * 2, OUTPUT: 100 + 50 + 50 + 60 + 30, KEPT: 100,
    READ: 3200, GREP: 1000, GLOB: 200, BASH: 1600, PYTHON_RULE: 800, SUMMARY: 600,
}


class TestAcceptance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = analyze(example_path())

    # 1. each source comes out exact
    def test_each_source_exact(self):
        cost = {k: s.cost for k, s in self.report.sources.items()}
        self.assertEqual(cost, EXPECTED_COST)
        entered = {k: s.entered for k, s in self.report.sources.items()}
        self.assertEqual(entered, EXPECTED_ENTERED)

    def test_ledger_per_response(self):
        self.assertEqual([r.ledger for r in self.report.responses], EXPECTED_LEDGERS)

    def test_ratio_calibrated_from_text_steps(self):
        # m2, m3, m4 and m5: only text entered, >= 2000 B, previous output < 400
        self.assertEqual(self.report.bytes_per_token, 2.5)
        self.assertEqual(self.report.ratio_pairs, 4)
        self.assertFalse(self.report.ratio_is_default)

    def test_measured_and_split(self):
        how = {(r.id, i.key): i.how for r in self.report.responses for i in r.entered}
        self.assertEqual(how.get(("msg_02", READ)), "measured")
        self.assertEqual(how.get(("msg_04", READ)), "split")
        self.assertEqual(how.get(("msg_04", PYTHON_RULE)), "split")
        self.assertEqual(how.get(("msg_07", PROMPT)), "measured")
        self.assertEqual(how.get(("msg_01", USER_MD)), "estimated")

    # 2. sources + unattributed = context of the usage, in every response
    def test_sum_equals_usage(self):
        self.assertEqual([r.context for r in self.report.responses], CONTEXTS)
        for r in self.report.responses:
            with self.subTest(response=r.id):
                self.assertEqual(sum(r.ledger.values()), r.context)
        self.assertEqual(sum(s.cost for s in self.report.sources.values()), sum(CONTEXTS))
        self.assertEqual(self.report.total, sum(CONTEXTS))

    # 3. a paths: rule that never loaded counts 0; one loaded at step N counts from N
    def test_path_rule_counts_only_when_loaded(self):
        self.assertNotIn(WEB_RULE, self.report.sources)
        present = [PYTHON_RULE in r.ledger for r in self.report.responses]
        self.assertEqual(present, [False, False, False, True, True, True, True])
        self.assertEqual(self.report.sources[PYTHON_RULE].responses, 4)

    # 4. a response written over several lines (same message.id) counts once
    def test_multiline_response_counts_once(self):
        ids = [r.id for r in self.report.responses]
        self.assertEqual(ids, [f"msg_0{i}" for i in range(1, 8)])
        self.assertEqual(self.report.compactions, 1)

    def test_fixture_matches_its_builder(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_example", HERE / "fixtures" / "build_example.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(example_path().read_bytes(), mod.build().encode("ascii"))


class TestInstructionsSplit(unittest.TestCase):
    """Files inside one `instructions` attachment: each byte of the rendered text counts once."""

    def entered(self, files, rendered):
        import json
        import tempfile
        from claude_context_cost import read
        att = {"type": "attachment", "cwd": "/home/dev/demo", "rendered": rendered,
               "attachment": {"type": "instructions", "files": files}}
        call = {"type": "assistant", "message": {"id": "m1", "content": [], "usage": {"input_tokens": 900}}}
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "t.jsonl"
            f.write_text(json.dumps(att) + "\n" + json.dumps(call) + "\n", encoding="utf-8")
            return [(i.name, i.bytes) for i in read(f).responses[0].entered]

    def test_same_content_twice_counts_where_it_appears(self):
        body = "Answer in English. " * 20
        files = [{"path": "/home/dev/demo/CLAUDE.md", "type": "Project", "content": body},
                 {"path": "/home/dev/demo/sub/CLAUDE.md", "type": "Project", "content": body}]
        got = self.entered(files, f"<a>{body}</a>")
        self.assertEqual(got, [("CLAUDE.md", len(body)), ("instructions wrapper", 7)])

    def test_file_inside_another_is_not_counted_again(self):
        short = "Use tabs. " * 10
        files = [{"path": "/home/dev/demo/.claude/rules/a.md", "type": "Project", "content": short},
                 {"path": "/home/dev/demo/CLAUDE.md", "type": "Project", "content": short + "And tests."}]
        got = self.entered(files, f"<a>{short}And tests.</a>")
        self.assertEqual(got, [("CLAUDE.md", len(short) + 10), ("instructions wrapper", 7)])


class TestSubagentTranscript(unittest.TestCase):
    """A subagent's own transcript has only sidechain lines; inside a session they are skipped."""

    def rewrite(self, change):
        import json
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        lines = []
        for line in example_path().read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                lines.append(line)
                continue
            lines.extend(json.dumps(x) for x in change(e))
        f = Path(tmp.name) / "agent-a1.jsonl"
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return analyze(f)

    def test_subagent_file_counts_like_a_session(self):
        rep = self.rewrite(lambda e: [{**e, "isSidechain": True}])
        self.assertEqual([r.ledger for r in rep.responses], EXPECTED_LEDGERS)
        self.assertEqual({k: s.cost for k, s in rep.sources.items()}, EXPECTED_COST)

    def test_sidechain_lines_in_a_session_are_skipped(self):
        def add_side(e):
            if e.get("type") != "assistant":
                return [e]
            m = {**e["message"], "id": e["message"]["id"] + "_side"}
            return [e, {**e, "isSidechain": True, "message": m}]
        rep = self.rewrite(add_side)
        self.assertEqual([r.id for r in rep.responses], [f"msg_0{i}" for i in range(1, 8)])
        self.assertEqual([r.ledger for r in rep.responses], EXPECTED_LEDGERS)


if __name__ == "__main__":
    unittest.main()
