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


def make_projects(root):
    """projA: two sessions and a subagent of s1; projB: one session.

    Each is the example, with message ids of its own: two sessions never share
    a response (a resumed one does, see TestResumedSession).
    """
    import json
    import os
    import re
    text = example_path().read_text(encoding="utf-8")
    side = "\n".join(json.dumps({**json.loads(x), "isSidechain": True}) if x.startswith('{"') else x
                     for x in text.splitlines())
    files = [("projA/s2.jsonl", text), ("projA/s1.jsonl", text),
             ("projA/s1/subagents/agent-a.jsonl", side + "\n"), ("projB/s3.jsonl", text)]
    for n, (name, body) in enumerate(files):
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(re.sub(r'("id": ?"msg_)', rf"\g<1>f{n}_", body), encoding="utf-8")
        os.utime(f, (1_000_000 + n, 1_000_000 + n))   # s2 older than s1


class TestSummary(unittest.TestCase):
    """Sum over a project folder (its subagents included) and over a folder of projects."""

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        make_projects(self.root)

    def test_project_folder_sums_its_sessions_and_subagents(self):
        from claude_context_cost import summarize
        s = summarize(self.root / "projA")
        self.assertEqual(s.projects, ["projA"])
        self.assertEqual([(r.file, r.session) for r in s.rows],
                         [("s2.jsonl", ""), ("s1.jsonl", ""), ("agent-a.jsonl", "s1")])
        self.assertEqual(s.total, 3 * 159160)
        self.assertEqual(s.responses, 3 * 7)
        read = s.sources.get(READ + ("",))
        self.assertEqual(read and (read.cost, read.entered, read.transcripts), (3 * 10400, 3 * 3200, 3))
        self.assertIn(PROJECT_MD + ("projA",), s.sources)
        self.assertEqual({k[:2]: t.cost for k, t in s.sources.items()},
                         {k: 3 * v for k, v in EXPECTED_COST.items()})

    def test_folder_of_projects_keeps_project_files_apart(self):
        from claude_context_cost import summarize
        s = summarize(self.root)
        self.assertEqual(s.projects, ["projA", "projB"])
        self.assertEqual(s.total, 4 * 159160)
        cost = {k: t.cost for k, t in s.sources.items()}
        self.assertEqual(cost.get(READ + ("",)), 4 * 10400)
        self.assertEqual(cost.get(USER_MD + ("",)), 4 * 2800)          # the user's file: one source
        self.assertEqual(cost.get(MEMORY + ("",)), 4 * 1400)
        self.assertEqual(cost.get(PROJECT_MD + ("projA",)), 3 * 5600)  # same name, two files
        self.assertEqual(cost.get(PROJECT_MD + ("projB",)), 5600)
        self.assertEqual(cost.get(PYTHON_RULE + ("projB",)), 1600)
        self.assertNotIn(PROJECT_MD + ("",), cost)

    def test_empty_folder(self):
        from claude_context_cost import summarize
        empty = self.root / "empty"
        empty.mkdir()
        s = summarize(empty)
        self.assertEqual((s.projects, s.rows, s.total), ([], [], 0))


def assistant(usage, mid=None, **line):
    m = {"model": "claude-test", "content": [{"type": "text", "text": "ok"}], "usage": usage}
    if mid:
        m["id"] = mid
    return {"type": "assistant", "cwd": "/home/dev/demo", **line, "message": m}


def usage(context, output=5):
    return {"input_tokens": context, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            "output_tokens": output}


def write_lines(path, lines, tail=""):
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines) + tail, encoding="utf-8")
    return path


class TestResumedSession(unittest.TestCase):
    """A resumed or forked session repeats the responses it came from: a sum counts each once."""

    M7_OUTPUT = 20   # msg_07's output_tokens in the example

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proj = Path(tmp.name) / "proj"
        self.proj.mkdir()
        self.text = example_path().read_text(encoding="utf-8")

    def write(self, name, body, when):
        import os
        f = self.proj / name
        f.write_text(body, encoding="utf-8")
        os.utime(f, (when, when))

    def test_a_fork_with_no_new_response_counts_once(self):
        from claude_context_cost import summarize
        self.write("s1.jsonl", self.text, 1_000_000)
        self.write("s1-fork.jsonl", self.text, 1_000_001)
        s = summarize(self.proj)
        self.assertEqual([(r.file, r.responses, r.repeated) for r in s.rows],
                         [("s1.jsonl", 7, 0), ("s1-fork.jsonl", 0, 7)])
        self.assertEqual((s.total, s.responses), (159160, 7))
        self.assertEqual({k[:2]: t.cost for k, t in s.sources.items()}, EXPECTED_COST)
        self.assertEqual(s.rows[1].top, None)

    def test_a_resumed_session_adds_only_its_new_responses(self):
        import json
        from claude_context_cost import summarize
        context = CONTEXTS[-1] + self.M7_OUTPUT + 500    # only the new prompt entered: 500 tokens
        new = [{"type": "user", "cwd": "/home/dev/demo", "message": {"role": "user", "content": "go on"}},
               assistant(usage(context), "msg_08")]
        self.write("s1.jsonl", self.text, 1_000_000)
        self.write("s1-resumed.jsonl", self.text + "".join(json.dumps(x) + "\n" for x in new), 1_000_001)
        s = summarize(self.proj)
        self.assertEqual([(r.file, r.responses, r.repeated, r.total) for r in s.rows],
                         [("s1.jsonl", 7, 0, 159160), ("s1-resumed.jsonl", 1, 7, context)])
        last = {**EXPECTED_LEDGERS[-1], OUTPUT: 30 + self.M7_OUTPUT, PROMPT: 100 + 500}
        cost = {k: EXPECTED_COST.get(k, 0) + last.get(k, 0) for k in set(EXPECTED_COST) | set(last)}
        entered = {**EXPECTED_ENTERED, OUTPUT: EXPECTED_ENTERED[OUTPUT] + self.M7_OUTPUT,
                   PROMPT: EXPECTED_ENTERED[PROMPT] + 500}
        self.assertEqual({k[:2]: t.cost for k, t in s.sources.items()}, cost)
        self.assertEqual({k[:2]: t.entered for k, t in s.sources.items()}, entered)
        self.assertEqual({k[:2]: t.transcripts for k, t in s.sources.items()},
                         {k: 2 if k in last else 1 for k in cost})
        self.assertEqual((s.rows[1].top.kind, s.rows[1].top.cost), ("unattributed", 18320))

    def test_ids_made_from_line_numbers_are_not_shared_between_files(self):
        from claude_context_cost import summarize
        for n, name in enumerate(["a.jsonl", "b.jsonl"]):
            write_lines(self.proj / name, [assistant(usage(1000 + n))])
        s = summarize(self.proj)
        self.assertEqual((s.responses, s.total), (2, 2001))


class TestRobustness(unittest.TestCase):
    """Damaged, empty or unknown transcripts: count what can be counted, and say what cannot."""

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def analyze_quiet(self, path):
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with redirect_stderr(err):
            rep = analyze(path)
        return rep, err.getvalue()

    def test_responses_without_message_id_each_count(self):
        lines = [assistant(usage(1000), uuid="u1"), assistant(usage(1100), uuid="u2"),
                 assistant(usage(1200))]
        rep, _ = self.analyze_quiet(write_lines(self.dir / "t.jsonl", lines))
        self.assertEqual([r.context for r in rep.responses], [1000, 1100, 1200])
        self.assertEqual([r.id for r in rep.responses], ["u1", "u2", "line 3"])

    def test_blocks_of_one_response_without_message_id_share_its_request_id(self):
        lines = [assistant(usage(1000), requestId="req_1", uuid="u1"),
                 assistant(usage(1000), requestId="req_1", uuid="u2"),
                 assistant(usage(1300), requestId="req_2", uuid="u3")]
        rep, _ = self.analyze_quiet(write_lines(self.dir / "t.jsonl", lines))
        self.assertEqual([(r.id, r.context) for r in rep.responses], [("req_1", 1000), ("req_2", 1300)])

    def test_a_known_transcript_gives_no_warning(self):
        rep, err = self.analyze_quiet(example_path())
        self.assertEqual((len(rep.responses), err), (7, ""))

    def test_lines_with_no_type_are_an_unknown_format(self):
        f = write_lines(self.dir / "notes.jsonl", [{"kind": "assistant", "usage": usage(1000)}] * 2)
        rep, err = self.analyze_quiet(f)
        self.assertEqual(rep.responses, [])
        self.assertIn("warning: notes.jsonl: 2 JSON lines and none has a \"type\"", err)

    def test_assistant_lines_with_no_input_tokens_are_an_unknown_format(self):
        renamed = {"prompt_tokens": 1000, "completion_tokens": 5}
        f = write_lines(self.dir / "t.jsonl", [assistant(renamed, "m1"), assistant({}, "m2")])
        rep, err = self.analyze_quiet(f)
        self.assertEqual(rep.responses, [])
        self.assertIn("warning: t.jsonl: 2 assistant lines and none has \"message.usage.input_tokens\"", err)

    def test_a_truncated_last_line_is_skipped_and_the_rest_counts(self):
        whole = analyze(example_path())
        f = self.dir / "cut.jsonl"
        last = '{"type":"assistant","message":{"id":"msg_09","usage":{"input_tokens":5'
        f.write_text(example_path().read_text(encoding="utf-8") + last, encoding="utf-8")
        rep, err = self.analyze_quiet(f)
        self.assertEqual(rep.bad_lines, whole.bad_lines + 1)
        self.assertEqual([r.ledger for r in rep.responses], EXPECTED_LEDGERS)
        self.assertEqual(err, "")

    def test_an_empty_file_has_no_responses(self):
        for body in ("", "\n\n"):
            f = self.dir / "empty.jsonl"
            f.write_text(body, encoding="utf-8")
            rep, err = self.analyze_quiet(f)
            self.assertEqual((rep.responses, rep.total, rep.compactions, err), ([], 0, 0, ""))

    def test_bytes_that_are_not_utf8_do_not_stop_the_count(self):
        raw = example_path().read_bytes()
        raw = raw.replace(b"please please", b"please \xff\xfe please", 1)   # inside the first prompt
        f = self.dir / "bytes.jsonl"
        f.write_bytes(b"\xff\xfe\x00garbage\n" + raw)
        rep, _ = self.analyze_quiet(f)
        self.assertEqual(rep.bad_lines, analyze(example_path()).bad_lines + 1)
        self.assertEqual([r.id for r in rep.responses], [f"msg_0{i}" for i in range(1, 8)])
        self.assertEqual(rep.total, 159160)

    def test_fields_of_the_wrong_type_are_not_fatal(self):
        lines = [{"type": "assistant", "message": "text"}, {"type": "assistant", "message": {"usage": [1]}},
                 {"type": "user", "message": "text"}, {"type": "attachment", "rendered": "x", "attachment": "y"},
                 {"type": "assistant", "cwd": 3, "message": {"id": "m1", "content": "text",
                                                            "usage": {"input_tokens": "9", "output_tokens": None,
                                                                      "cache_read_input_tokens": 100}}}]
        rep, _ = self.analyze_quiet(write_lines(self.dir / "t.jsonl", lines))
        self.assertEqual([(r.id, r.context, r.output) for r in rep.responses], [("m1", 100, 0)])


if __name__ == "__main__":
    unittest.main()
