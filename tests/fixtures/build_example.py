"""Writes the synthetic transcript `claude_context_cost/example.jsonl`.

    python tests/fixtures/build_example.py

Hand-designed, never copied from a real session: every size and every `usage`
below is chosen so that each source has one exact answer (the acceptance tests
in `tests/test_acceptance.py` hold the numbers). The line shapes follow
Claude Code 2.1.293 (October 2026). All text is ASCII, so bytes = characters,
and the ratio is exactly 2.5 bytes per token.

The story, response by response (context = input + cache read + cache write):

    before m1  instructions: user CLAUDE.md 1000 B, project CLAUDE.md 2000 B,
               rule without paths 500 B, MEMORY.md 500 B, wrapper 100 B;
               prompt 100 B                      -> 1680 tokens, rest is floor
    m1  20000  (2 lines, same id)  calls Read
    m2  22100  Read result 5000 B            -> 2000 measured
    m3  23150  Grep result 2500 B            -> 1000 measured
    m4  25000  Read 3000 B + path rule 1000 B + Glob 500 B -> 1800, split
               (a nested_memory without `rendered` never reached the model)
    m5  26660  Bash result 4000 B            -> 1600 measured
    (a <synthetic> response with zero usage; a broken line)
    compaction
    m6  21060  instructions again 4100 B, summary 1500 B, path rule reloaded
               1000 B, m5 text kept by the compaction 250 B -> 2740, rest floor
    m7  21190  (3 lines, same id) prompt 250 B -> 100 measured

Previous outputs: m1 100, m2 50, m3 50, m4 60, m5 40, m6 30, m7 20.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "claude_context_cost" / "example.jsonl"
HOME = "/home/dev"
CWD = HOME + "/demo"
VERSION = "2.1.293"
SESSION = "00000000-0000-4000-8000-000000000001"


def text(n, word):
    """Exactly n ASCII bytes of readable filler built from one word."""
    unit = word + " "
    return (unit * (n // len(unit) + 1))[:n]


class Writer:
    def __init__(self):
        self.lines = []
        self.clock = 0

    def add(self, entry):
        self.clock += 1
        base = {"uuid": f"00000000-0000-4000-9000-{self.clock:012d}", "sessionId": SESSION,
                "timestamp": f"2026-10-10T12:{self.clock // 60:02d}:{self.clock % 60:02d}.000Z",
                "cwd": CWD, "version": VERSION, "isSidechain": False}
        base.update(entry)
        self.lines.append(json.dumps(base, ensure_ascii=True, separators=(",", ":")))

    def raw(self, line):
        self.lines.append(line)

    def attachment(self, att, rendered=None):
        entry = {"type": "attachment", "attachment": att}
        if rendered is not None:
            entry["rendered"] = [{"content": rendered}]
        self.add(entry)

    def prompt(self, content, **flags):
        self.add({"type": "user", "message": {"role": "user", "content": content}, **flags})

    def result(self, tool_id, content):
        self.add({"type": "user", "toolUseResult": {"type": "text"},
                  "message": {"role": "user", "content": [
                      {"type": "tool_result", "tool_use_id": tool_id, "content": content}]}})

    def response(self, mid, context, output, blocks, model="claude-opus-5-5"):
        """One line per block, the same usage repeated in each (as Claude Code writes it)."""
        usage = {"input_tokens": 10, "cache_creation_input_tokens": 1000,
                 "cache_read_input_tokens": context - 1010, "output_tokens": output}
        for block in blocks:
            self.add({"type": "assistant", "requestId": "req_" + mid,
                      "message": {"id": mid, "type": "message", "role": "assistant", "model": model,
                                  "content": [block], "usage": usage}})


def tool(tid, name, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def instructions(reason=None):
    files = [
        {"type": "User", "path": HOME + "/.claude/CLAUDE.md", "content": text(1000, "user")},
        {"type": "Project", "path": CWD + "/CLAUDE.md", "content": text(2000, "project")},
        {"type": "Project", "path": CWD + "/.claude/rules/style.md", "content": text(500, "style")},
        {"type": "AutoMem", "path": HOME + "/.claude/projects/-home-dev-demo/memory/MEMORY.md",
         "content": text(500, "memory")},
    ]
    att = {"type": "instructions", "files": files}
    if reason:
        att.update({"changed": True, "reason": reason})
    return att, text(100, "Instructions:") + "".join(f["content"] for f in files)


def path_rule(name, glob, size):
    path = f"{CWD}/.claude/rules/{name}"
    body = text(size, name.split(".")[0])
    return {"type": "nested_memory", "path": path, "displayPath": f".claude/rules/{name}",
            "content": {"type": "Project", "path": path, "globs": [glob], "content": body,
                        "rawContent": body, "contentDiffersFromDisk": False}}, body


def build():
    w = Writer()
    w.attachment({"type": "prompt_snapshot", "systemPrompt": "synthetic", "tools": []})
    w.attachment(*instructions())
    w.attachment({"type": "hook_success", "hookName": "SessionStart", "content": "ok"})
    w.prompt(text(100, "please"))
    w.response("msg_01", 20000, 100, [{"type": "thinking", "thinking": "plan", "signature": "sig"},
                                      tool("tu_01", "Read", file_path=CWD + "/README.md")])
    w.result("tu_01", text(5000, "readme"))
    w.attachment({"type": "deferred_tools_record", "entries": []})
    w.attachment({"type": "thinking_drop", "newlyDropped": 1})
    w.response("msg_02", 22100, 50, [tool("tu_02", "Grep", pattern="fetch", path="web/")])
    w.result("tu_02", text(2500, "match"))
    w.response("msg_03", 23150, 50, [tool("tu_03", "Read", file_path=CWD + "/src/app.py")])
    w.result("tu_03", text(3000, "code"))
    w.attachment(*path_rule("python.md", "src/**/*.py", 1000))
    w.attachment(path_rule("web.md", "web/**", 800)[0])        # no `rendered`: never reached the model
    w.response("msg_03", 23150, 50, [tool("tu_04", "Glob", pattern="src/*.py")])
    w.result("tu_04", text(500, "path"))
    w.response("msg_04", 25000, 60, [tool("tu_05", "Bash", command="python -m unittest")])
    w.result("tu_05", text(4000, "test"))
    kept = {"type": "text", "text": text(250, "done")}
    w.response("msg_05", 26660, 40, [kept])
    w.response("msg_syn", 0, 0, [{"type": "text", "text": "No response requested."}], model="<synthetic>")
    w.raw("{not json")
    w.add({"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted",
           "compactMetadata": {"trigger": "auto", "preTokens": 26700, "postTokens": 21000}})
    w.attachment(*instructions("compaction"))
    w.prompt(text(1500, "summary"), isCompactSummary=True)
    w.attachment(*path_rule("python.md", "src/**/*.py", 1000))
    w.response("msg_05", 26660, 40, [kept])                 # preserved by the compaction
    w.response("msg_06", 21060, 30, [{"type": "text", "text": "ready"}])
    w.prompt(text(250, "thanks"))
    w.attachment({"type": "hook_success", "hookName": "UserPromptSubmit", "content": "ok"})
    w.response("msg_07", 21190, 20, [{"type": "thinking", "thinking": "ok", "signature": "sig"},
                                     {"type": "text", "text": "You are welcome."},
                                     {"type": "text", "text": "Bye."}])
    return "\n".join(w.lines) + "\n"


if __name__ == "__main__":
    OUT.write_bytes(build().encode("ascii"))
    print(f"wrote {OUT}")
