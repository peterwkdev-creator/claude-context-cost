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
from pathlib import Path

from claude_context_cost import analyze, summarize

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


if __name__ == "__main__":
    unittest.main()
