"""Every real transcript on this machine: the sources add up to the usage, response by response.

Opt-in, because it reads private files and takes a while:

    CLAUDE_CONTEXT_COST_CORPUS=1 python -m unittest tests.test_corpus -v
    CLAUDE_CONTEXT_COST_CORPUS=/some/folder python -m unittest tests.test_corpus -v

It prints only counts, never content or paths. The response count is checked
against an independent count (distinct `message.id` with a non-zero usage).
Subagent transcripts (`<session>/subagents/*.jsonl`) are checked too.
"""
import json
import os
import unittest
from datetime import datetime
from pathlib import Path

from claude_context_cost import analyze, summarize
from claude_context_cost.budget import scan
from claude_context_cost.transcript import _norm, short_path

SETTING = os.environ.get("CLAUDE_CONTEXT_COST_CORPUS", "")
BASE = Path.home() / ".claude" / "projects" if SETTING in ("", "1") else Path(SETTING)


def independent_count(path):
    ids = {False: set(), True: set()}   # by isSidechain
    main = False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict) or e.get("type") not in ("user", "assistant"):
                continue
            side = bool(e.get("isSidechain"))
            main = main or not side
            m = e.get("message") or {}
            u = (m.get("usage") or {}) if e.get("type") == "assistant" else {}
            if (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
                    + (u.get("cache_creation_input_tokens") or 0):
                ids[side].add(m.get("id"))
    return len(ids[False] if main else ids[True])   # a subagent's own file has only sidechain lines


def session_start(path):
    """When the session began: its first timestamp, read from the session's own transcript for a subagent."""
    if path.parent.name == "subagents":
        path = path.parents[2] / (path.parents[1].name + ".jsonl")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    ts = json.loads(line).get("timestamp")
                except (ValueError, AttributeError):
                    continue
                if ts:
                    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except OSError:
        pass
    return float("-inf")   # unknown: nothing on disk counts as unchanged


@unittest.skipUnless(SETTING, "set CLAUDE_CONTEXT_COST_CORPUS to read the transcripts on this machine")
class TestCorpus(unittest.TestCase):

    def test_every_transcript_adds_up(self):
        sessions = sorted(BASE.glob("*/*.jsonl")) or sorted(BASE.glob("*.jsonl"))
        subagents = sorted(BASE.glob("*/*/subagents/*.jsonl")) or sorted(BASE.glob("*/subagents/*.jsonl"))
        files = sessions + subagents
        self.assertTrue(sessions, f"no transcripts under {BASE}")
        responses = off = wrong_count = calibrated = 0
        for f in files:
            rep = analyze(f)
            responses += len(rep.responses)
            off += sum(1 for r in rep.responses if sum(r.ledger.values()) != r.context)
            wrong_count += independent_count(f) != len(rep.responses)
            calibrated += bool(rep.responses) and not rep.ratio_is_default
        print(f"\n{len(sessions)} transcripts and {len(subagents)} subagent transcripts, {responses} responses; sum != usage in {off}; "
              f"response count differs in {wrong_count} files; ratio calibrated in {calibrated}")
        self.assertEqual(off, 0)
        self.assertEqual(wrong_count, 0)

    def test_the_sum_of_every_project_takes_every_transcript(self):
        # live sessions keep writing, so compare with what existed before the sum, not totals file by file
        sessions = sorted(BASE.glob("*/*.jsonl")) or sorted(BASE.glob("*.jsonl"))
        subagents = sorted(BASE.glob("*/*/subagents/*.jsonl")) or sorted(BASE.glob("*/subagents/*.jsonl"))
        before = {(f.parent.name, "", f.name) for f in sessions} | \
                 {(f.parents[2].name, f.parent.parent.name, f.name) for f in subagents}
        s = summarize(BASE)
        if len(s.projects) == 1:   # BASE is one project's folder
            before = {(s.projects[0], session, name) for _, session, name in before}
        summed = {(r.project, r.session, r.file) for r in s.rows}
        print(f"\n{len(s.projects)} projects, {len(s.rows)} transcripts, {s.responses} responses, "
              f"{len(s.sources)} sources in the sum")
        self.assertEqual(before - summed, set())
        self.assertEqual(sum(t.cost for t in s.sources.values()), s.total)
        self.assertEqual(s.total, sum(r.total for r in s.rows))

    def test_the_budget_scan_finds_what_claude_code_loaded(self):
        # a file changed after the load can explain a difference, so a load is compared
        # only when no file involved changed since; the project folder must still exist
        start = start_same = on_demand = on_demand_same = bytes_ok = bytes_seen = 0
        scans = {}
        for f in sorted(BASE.glob("**/*.jsonl")):
            first = True
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"instructions"' not in line and '"nested_memory"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                        when = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).timestamp()
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue
                    a, cwd = e.get("attachment") or {}, e.get("cwd") or ""
                    if not isinstance(a, dict) or not cwd or not os.path.isdir(cwd):
                        continue
                    if cwd not in scans:
                        scans[cwd] = {x.name: x for x in scan(cwd)[0]}
                    mine, root = scans[cwd], Path(cwd)

                    def changed(name):
                        p = root / name
                        return not p.is_file() or p.stat().st_mtime > when
                    # a subagent gets the instructions its session loaded earlier: they were read
                    # no later than the session's first line
                    if a.get("type") == "instructions" and first:
                        when = min(when, session_start(f))
                        first = False
                        got = {}
                        for x in a.get("files") or []:
                            name = short_path(x.get("path"), cwd)
                            if x.get("type") == "Project" and name != _norm(x.get("path")):
                                got[name] = x.get("content") or ""
                        want = {n for n, x in mine.items() if x.start}
                        if any(changed(n) for n in set(got) ^ want):
                            continue
                        start += 1
                        start_same += set(got) == want
                        for n in set(got) & want:
                            if not changed(n):
                                bytes_seen += 1
                                bytes_ok += mine[n].bytes == len(got[n].encode("utf-8"))
                    elif a.get("type") == "nested_memory":
                        c = a.get("content") if isinstance(a.get("content"), dict) else {}
                        name = short_path(a.get("path") or c.get("path"), cwd)
                        if name == _norm(a.get("path") or c.get("path")) or changed(name):
                            continue
                        on_demand += 1
                        x = mine.get(name)
                        on_demand_same += x is not None and not x.start
                        if x is not None and isinstance(c.get("content"), str):
                            bytes_seen += 1
                            bytes_ok += x.bytes == len(c["content"].encode("utf-8"))
        print(f"\nbudget scan: start-up set equal in {start_same} of {start} loads, on-demand file found "
              f"in {on_demand_same} of {on_demand}, bytes equal in {bytes_ok} of {bytes_seen} files")
        self.assertEqual(start_same, start)
        self.assertEqual(on_demand_same, on_demand)
        self.assertEqual(bytes_ok, bytes_seen)


if __name__ == "__main__":
    unittest.main()
