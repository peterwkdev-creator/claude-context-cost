"""Reads a Claude Code transcript (.jsonl) into responses and what entered before each one.

The format is not documented and changes between versions; what this reader
relies on, each point checked against real transcripts (Claude Code 2.1.284
to 2.1.293, October 2026):

- One API response is one `message.id`, but Claude Code writes one line per
  content block (thinking, text, each tool call) and repeats the same `usage`
  on every line. Counting lines instead of ids roughly doubles the total.
- Input context = `input_tokens` + `cache_read_input_tokens` +
  `cache_creation_input_tokens`.
- An attachment reaches the model only when its line has `rendered`; the
  rendered text is what counts. `prompt_snapshot` (system prompt and tools)
  has none: it is the floor, left to the remainder.
- `instructions` carries the CLAUDE.md files, MEMORY.md and the rules without
  `paths:`; `nested_memory` is a rule with `paths:` (or a subfolder CLAUDE.md)
  at the moment it actually loaded.
- After a compaction, the messages it preserves are written again with their
  old ids: they are back in the context, not new responses.

A file whose lines this reader does not recognise (no `type`, or assistant
lines with no `message.usage.input_tokens`) gets a warning on stderr: its
responses would otherwise be counted as zero without a word.
"""
import json
import os
import sys
from dataclasses import dataclass, field

USER_FILES = {"User", "AutoMem"}


@dataclass
class Item:
    """Something that entered the context between two responses."""
    kind: str
    name: str
    bytes: int          # UTF-8 bytes of the text that reached the model
    chars: int
    opaque: bool = False  # image or tool reference: its size in tokens is not in the text
    tokens: int = 0
    how: str = ""

    @property
    def key(self):
        return (self.kind, self.name)


@dataclass
class Response:
    id: str
    model: str
    context: int        # input context of this call, from `usage`
    output: int
    line: int
    entered: list       # items that entered since the previous response
    segment_start: bool  # first response of the session or after a compaction
    ledger: dict = field(default_factory=dict)


@dataclass
class Transcript:
    path: str
    responses: list
    compactions: int
    bad_lines: int


def _item(kind, name, text, opaque=False):
    return Item(kind, name, len(text.encode("utf-8")), len(text), opaque)


def _norm(path):
    return str(path or "").replace("\\", "/")


def short_path(path, cwd, user_file=False):
    """Path relative to the session folder; the user's own files as ~/.claude/..."""
    p, base = _norm(path), _norm(cwd).rstrip("/")
    if base and p.lower().startswith(base.lower() + "/"):
        return p[len(base) + 1:]
    i = p.find("/.claude/")
    if user_file and i >= 0:
        return "~" + p[i:]
    return p


def _rendered_text(rendered):
    if isinstance(rendered, str):
        return rendered
    parts = []
    for x in rendered or []:
        if isinstance(x, dict) and isinstance(x.get("content"), str):
            parts.append(x["content"])
        else:
            parts.append(json.dumps(x, ensure_ascii=False))
    return "".join(parts)


def _split(text, files, wrapper):
    """Each file found verbatim in the rendered text is its own item; the rest is the wrapper.

    A match is taken out of the text before the next file is looked up, longest
    first: two files with the same content, or one inside another, are counted
    only as many times as they appear.
    """
    found, rest = {}, text
    for n in sorted(range(len(files)), key=lambda n: -len(files[n][2])):
        kind, name, content = files[n]
        if content and content in rest:
            found[n] = _item(kind, name, content)
            rest = rest.replace(content, "", 1)
    items = [found[n] for n in sorted(found)]   # in the order Claude Code listed them
    rest_b = len(rest.encode("utf-8"))
    if rest_b > 0:
        items.append(Item("attachment", wrapper, rest_b, len(rest)))
    return items


def _attachment_items(att, text, cwd):
    typ = att.get("type")
    if typ == "instructions":
        files = []
        for f in att.get("files") or []:
            p = _norm(f.get("path"))
            if f.get("type") == "AutoMem":
                kind = "memory"
            elif "/.claude/rules/" in p:
                kind = "rule"
            else:
                kind = "claude.md"
            files.append((kind, short_path(p, cwd, f.get("type") in USER_FILES), f.get("content") or ""))
        return _split(text, files, "instructions wrapper")
    if typ == "nested_memory":
        content = att.get("content") if isinstance(att.get("content"), dict) else {}
        p = _norm(att.get("path") or content.get("path"))
        kind = "path rule" if content.get("globs") or "/.claude/rules/" in p else "claude.md"
        return [_item(kind, short_path(p, cwd), text)]
    if typ == "invoked_skills":
        skills = [("skill", s.get("name") or "?", s.get("content") or "")
                  for s in att.get("skills") or [] if isinstance(s, dict)]
        return _split(text, skills, "skills wrapper")
    if typ == "skill_listing":
        return [_item("skill", "listing", text)]
    if typ == "file":
        return [_item("file", short_path(att.get("displayPath") or att.get("filename"), cwd), text)]
    return [_item("attachment", str(typ), text)]


def _block_text(block):
    t = block.get("type")
    if t == "text":
        return block.get("text") or ""
    if t == "thinking":
        return block.get("thinking") or ""
    if t == "tool_use":
        return (block.get("name") or "") + json.dumps(block.get("input"), ensure_ascii=False)
    return json.dumps(block, ensure_ascii=False)


def _result_item(block, tool_names):
    c = block.get("content")
    name = tool_names.get(block.get("tool_use_id"), "?")
    if isinstance(c, str):
        return _item("tool", name, c)
    text, opaque = [], False
    for x in c or []:
        if isinstance(x, dict) and x.get("type") == "text":
            text.append(x.get("text") or "")
        else:
            opaque = True
    return _item("tool", name, "".join(text), opaque)


def _content_text(c):
    if isinstance(c, str):
        return c
    return "".join(x.get("text") or "" for x in c or [] if isinstance(x, dict) and x.get("type") == "text")


def _dict(x):
    return x if isinstance(x, dict) else {}


def _tokens(x):
    return x if isinstance(x, int) and not isinstance(x, bool) else 0


def _warn(path, text):
    sys.stderr.write(f"claude-context-cost: warning: {os.path.basename(str(path))}: {text}\n")


def _user_items(entry, tool_names):
    c = _dict(entry.get("message")).get("content")
    if entry.get("isCompactSummary"):
        return [_item("summary", "compaction", _content_text(c))]
    who = "meta" if entry.get("isMeta") else "user"
    if isinstance(c, str):
        return [_item("prompt", who, c)]
    items = []
    for x in c or []:
        if not isinstance(x, dict):
            continue
        if x.get("type") == "tool_result":
            items.append(_result_item(x, tool_names))
        elif x.get("type") == "text":
            items.append(_item("prompt", who, x.get("text") or ""))
        else:
            items.append(Item("prompt", str(x.get("type")), 0, 0, opaque=True))
    return items


def _subagent_only(path):
    """A subagent's own transcript (`subagents/agent-*.jsonl`) has only sidechain messages."""
    side = False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("type") in ("user", "assistant"):
                if not e.get("isSidechain"):
                    return False
                side = True
    return side


def read(path):
    """Parse one transcript. Lines that are not JSON objects are counted, not fatal."""
    responses, pending = [], []
    seen_segment, seen_ever, tool_names = set(), set(), {}
    cwd, segment_start, compactions, bad = "", True, 0, 0
    objects, typed, assistants, known = 0, 0, 0, 0   # to tell a format this reader does not know
    skip_side = not _subagent_only(path)   # in a session's transcript, sidechains are other contexts
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            try:
                e = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(e, dict):
                bad += 1
                continue
            if skip_side and e.get("isSidechain"):
                continue
            objects += 1
            cwd = e.get("cwd") if isinstance(e.get("cwd"), str) and e.get("cwd") else cwd
            t = e.get("type")
            typed += isinstance(t, str)
            if t == "system" and e.get("subtype") == "compact_boundary":
                compactions += 1
                pending, seen_segment, segment_start = [], set(), True
            elif t == "assistant":
                m = _dict(e.get("message"))
                u = _dict(m.get("usage"))
                assistants += 1
                known += "input_tokens" in u
                # one response is one message.id; with none, the request id (the same on every block of
                # a response), then the line's own uuid, then its number: never one shared None
                mid = str(m.get("id") or e.get("requestId") or e.get("uuid") or f"line {n}")
                content = m.get("content")
                blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
                for b in blocks:
                    if b.get("type") == "tool_use":
                        tool_names[b.get("id")] = b.get("name") or "?"
                if mid in seen_segment:
                    continue                    # another block of a response already counted
                if mid in seen_ever:            # preserved by the compaction, written again
                    pending += [_item("output", "kept by compaction", _block_text(b)) for b in blocks]
                    continue
                ctx = _tokens(u.get("input_tokens")) + _tokens(u.get("cache_read_input_tokens")) \
                    + _tokens(u.get("cache_creation_input_tokens"))
                if not ctx:
                    continue                    # <synthetic> and other lines with no API call
                seen_segment.add(mid)
                seen_ever.add(mid)
                responses.append(Response(mid, str(m.get("model") or ""), ctx,
                                          _tokens(u.get("output_tokens")), n, pending, segment_start))
                pending, segment_start = [], False
            elif t == "user":
                pending += _user_items(e, tool_names)
            elif t == "attachment":
                text = _rendered_text(e.get("rendered")) if e.get("rendered") else ""
                if text:
                    pending += _attachment_items(_dict(e.get("attachment")), text, cwd)
    if objects and not typed:
        _warn(path, f"{objects:,} JSON lines and none has a \"type\": not a Claude Code transcript, or a "
                    f"format this version does not know; nothing is counted")
    elif assistants and not known:
        _warn(path, f"{assistants:,} assistant lines and none has \"message.usage.input_tokens\": a "
                    f"transcript format this version does not know; their responses are not counted")
    return Transcript(str(path), responses, compactions, bad)
