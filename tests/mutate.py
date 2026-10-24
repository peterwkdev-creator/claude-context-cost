"""Mutation proof: break each counting, budget or versions rule on purpose; the tests must fail.

    python tests/mutate.py

Each mutant changes one unique snippet in a copy of the package and runs
the SUITE there. A mutant counts as caught only when the run ends
in assertion failures (`failures=`), never in errors: an import or syntax
error proves nothing. The clean copy runs first and the whole round stops if it
is not green. Exit code 0 only if every mutant is caught.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ("tests.test_acceptance", "tests.test_budget", "tests.test_versions")

# (rule it breaks, file, snippet, replacement)
MUTANTS = [
    ("one response per message.id (criterion 4)", "transcript.py",
     "if mid in seen_segment:\n                    continue",
     "if mid in seen_segment:\n                    pass"),
    ("context includes the cache write (criterion 2)", "transcript.py",
     "+ _tokens(u.get(\"cache_creation_input_tokens\"))", "+ 0"),
    ("only attachments with `rendered` reach the model (criterion 3)", "transcript.py",
     "text = _rendered_text(e.get(\"rendered\")) if e.get(\"rendered\") else \"\"",
     "text = _rendered_text(e.get(\"rendered\")) if e.get(\"rendered\") else json.dumps(e.get(\"attachment\"))"),
    ("messages preserved by a compaction are not new responses", "transcript.py",
     "if mid in seen_ever:", "if False:"),
    ("each instructions file is its own source (criterion 1)", "transcript.py",
     "if content and content in rest:", "if False:"),
    ("a subagent's own transcript is read", "transcript.py",
     "skip_side = not _subagent_only(path)", "skip_side = True"),
    ("sidechain lines in a session's transcript are skipped", "transcript.py",
     "if not e.get(\"isSidechain\"):\n                    return False",
     "if not e.get(\"isSidechain\"):\n                    pass"),
    ("each byte of an attachment counts once", "transcript.py",
     "rest = rest.replace(content, \"\", 1)", "rest = rest"),
    ("a compaction empties the context (criterion 3)", "attribute.py",
     "            ledger = {}\n", "            ledger = dict(ledger)\n"),
    ("several items share by bytes (criterion 1)", "attribute.py",
     "shares, ordered = allocate(delta, [i.bytes for i in known]), known",
     "shares, ordered = allocate(delta, [1 for i in known]), known"),
    ("the ratio is calibrated on the transcript (criterion 1)", "attribute.py",
     "return statistics.median(ratios), len(ratios), False",
     "return DEFAULT_BYTES_PER_TOKEN, len(ratios), False"),
    ("the previous output enters the context (criterion 2)", "attribute.py",
     "ledger[OUTPUT] = ledger.get(OUTPUT, 0) + prev.output",
     "ledger[OUTPUT] = ledger.get(OUTPUT, 0) + 0"),
    ("what entered = context difference minus output (criterion 1)", "attribute.py",
     "r.context - prev.context - prev.output, ratio)", "r.context - prev.context, ratio)"),
    ("a project's own file keeps its project in a sum", "summary.py",
     "project if _is_local(src.kind, src.name) else \"\"", "\"\""),
    ("the user's own file is one source in every project", "summary.py",
     "return kind in LOCAL_KINDS and", "return kind in LOCAL_KINDS or"),
    ("a project's sum includes its subagents", "summary.py",
     "sorted(folder.glob(\"*/subagents/*.jsonl\"), key=by_time)", "[]"),
    ("a source's cost is summed over transcripts", "summary.py",
     "t.cost += src.cost", "t.cost = src.cost"),
    ("budget: the frontmatter is not sent", "budget.py",
     "t = FRONTMATTER.sub(\"\", t, 1)", "t = t"),
    ("budget: comment blocks are not sent", "budget.py",
     "t = COMMENT_BLOCK.sub(\"\", t)", "t = t"),
    ("budget: on demand only the start is stripped", "budget.py",
     "t = t.strip() if start else t.lstrip()", "t = t.strip()"),
    ("budget: the file's line ends are kept", "budget.py",
     "if \"\\r\\n\" in text and not comments else t", "if False else t"),
    ("budget: a rule with paths: loads on demand", "budget.py",
     "(p, not _has_paths(_read(p)))", "(p, True)"),
    ("budget: a subfolder's CLAUDE.md is counted", "budget.py",
     "found += [(p, False) for p in _subfolders_claude_md(root) if inside(p)]", "found += []"),
    ("budget: hidden folders and node_modules are skipped", "budget.py",
     "if not p.name.startswith(\".\") and p.name != \"node_modules\":", "if True:"),
    ("budget: imports are followed", "budget.py",
     "                    follow(path, text, start, 1)", "                    pass"),
    ("budget: an import is relative to the importing file", "budget.py",
     "p = (path.parent / target).resolve()", "p = (root / target).resolve()"),
    ("budget: imports stop after five hops", "budget.py",
     "if depth > MAX_IMPORT_DEPTH:", "if depth > MAX_IMPORT_DEPTH + 1:"),
    ("budget: an import in code is not followed", "budget.py",
     "text = CODE_SPAN.sub(\"\", CODE_BLOCK.sub(\"\", text))", "text = text"),
    ("budget: the declared ratio is used", "budget.py",
     "files, outside = scan(root, ratio or DEFAULT_BYTES_PER_TOKEN)", "files, outside = scan(root)"),
    ("budget: a file over its limit fails", "budget.py",
     "if f.tokens > limit:", "if f.tokens > limit + 1:"),
    ("budget: a file is held to every pattern", "budget.py",
     "f.limit = limit if f.limit is None else min(f.limit, limit)", "f.limit = limit"),
    ("budget: the start-up total has a limit", "budget.py",
     "if start is not None and b.start_tokens > start:", "if False:"),
    ("budget: a pattern that matches no file is an error", "budget.py",
     "if not hits:", "if False:"),
    ("budget: a star stays in one folder", "budget.py",
     "out.append(\"[^/]*\")", "out.append(\".*\")"),
    ("budget: an unknown key is an error", "budget.py",
     "if unknown:", "if False:"),
    ("budget: a limit is a positive integer", "budget.py",
     "if not ok or not math.isfinite(value) or value <= 0:", "if not math.isfinite(value) or value <= 0:"),
    ("budget: nan and inf are not a ratio", "budget.py",
     "if not ok or not math.isfinite(value) or value <= 0:", "if not ok or value <= 0:"),
    ("budget: a budget file that is not UTF-8 is invalid", "budget.py",
     "except UnicodeDecodeError:", "except KeyError:"),
    ("budget: a missing budget file is invalid", "budget.py",
     "except FileNotFoundError:", "except KeyError:"),
    ("budget: an import in a ~~~ block is not followed", "budget.py",
     "(```|~~~)", "(```)"),
    ("budget: an unquoted dotted pattern is named whole", "budget.py",
     "pattern += \".\" + key", "pass"),
    ("versions: git's file is rendered before comparing", "versions.py",
     "if _same(render(blob, start), text)]", "if _same(blob, text)]"),
    ("versions: line endings do not matter", "versions.py",
     "return a.replace(\"\\r\\n\", \"\\n\") == b.replace(\"\\r\\n\", \"\\n\")", "return a == b"),
    ("versions: the newest commit before the load", "versions.py",
     "h, t = before[0] if before else hits[-1]", "h, t = hits[0]"),
    ("versions: only a commit up to the load counts as before", "versions.py",
     "x[1] <= when]", "x[1] <= when + 10**9]"),
    ("versions: a commit after the load is marked", "versions.py",
     "v.commit, v.committed_after = h, not before", "v.commit, v.committed_after = h, False"),
    ("versions: the same text loaded twice is one line", "versions.py",
     "if key in seen:", "if False:"),
    ("versions: today's file is compared", "versions.py",
     "v.today = \"same\" if now == text else \"changed\"", "v.today = \"changed\""),
    ("versions: a deleted file is still found in git", "versions.py",
     "while not d.is_dir():", "while False:"),
    ("versions: a subagent's lines in a session are skipped", "versions.py",
     "(skip_side and e.get(\"isSidechain\"))", "(False)"),
    ("versions: only .md files are read", "versions.py",
     "if not p.lower().endswith(\".md\"):", "if False:"),
    ("a response repeated by a resumed session is summed once", "summary.py",
     "counted = [r for r, k in zip(rep.responses, keys) if k not in seen]", "counted = list(rep.responses)"),
    ("a partly repeated transcript sums only its new responses", "summary.py",
     "if id(r) not in keep:\n            continue", "if id(r) not in keep:\n            pass"),
    ("an id made from a line number is only unique in its file", "summary.py",
     "return (str(path), r.id) if r.id.startswith(\"line \") else r.id", "return r.id"),
    ("a response with no message.id is still one response", "transcript.py",
     "mid = str(m.get(\"id\") or e.get(\"requestId\") or e.get(\"uuid\") or f\"line {n}\")",
     "mid = str(m.get(\"id\"))"),
    ("with no message.id, the request id groups a response's blocks", "transcript.py",
     "or e.get(\"requestId\") or", "or"),
    ("lines with no type are an unknown format", "transcript.py",
     "if objects and not typed:", "if False:"),
    ("assistant lines with no input_tokens are an unknown format", "transcript.py",
     "elif assistants and not known:", "elif False:"),
    ("budget: a link out of the repository is not read", "budget.py",
     "if path.resolve().is_relative_to(root):", "if True:"),
    ("versions: git runs with core.fsmonitor off", "versions.py",
     "\"-c\", \"core.fsmonitor=false\",", ""),
    ("versions: a relative path from the transcript is not looked up", "versions.py",
     'return not path.replace("\\\\", "/").startswith("//") and Path(path).is_absolute()',
     'return not path.replace("\\\\", "/").startswith("//")'),
    ("versions: a UNC path from the transcript is not looked up", "versions.py",
     'return not path.replace("\\\\", "/").startswith("//") and Path(path).is_absolute()',
     "return Path(path).is_absolute()"),
]


def run(where):
    p = subprocess.run([sys.executable, "-m", "unittest", *SUITE], cwd=where, capture_output=True, timeout=120)
    out = (p.stdout + p.stderr).decode("utf-8", errors="replace")
    ran = re.search(r"Ran (\d+) test", out)
    status = out.strip().splitlines()[-1] if out.strip() else ""
    return p.returncode, int(ran.group(1)) if ran else 0, status


def main():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "lib"
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        code, ran, status = run(work)
        print(f"clean run: {ran} tests, {status}")
        if code != 0 or ran == 0:
            print("the clean copy is not green: no mutant can be judged")
            return 1
        pkg = work / "claude_context_cost"
        caught = 0
        for rule, name, old, new in MUTANTS:
            path = pkg / name
            original = path.read_text(encoding="utf-8")
            if original.count(old) != 1:
                print(f"INVALID  {rule}: snippet found {original.count(old)} times in {name}")
                return 1
            path.write_text(original.replace(old, new), encoding="utf-8")
            code, ran_m, status = run(work)
            path.write_text(original, encoding="utf-8")
            if code != 0 and "failures=" in status and "errors=" not in status:
                caught += 1
                print(f"caught   {rule} ({status})")
            elif code != 0:
                print(f"INVALID  {rule}: run ended in {status!r}, not in assertion failures")
            else:
                print(f"ALIVE    {rule}: {ran_m} tests passed")
        print(f"{caught} of {len(MUTANTS)} mutants caught by {' and '.join(SUITE)}")
        return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
