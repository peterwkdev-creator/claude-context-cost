"""Mutation proof: break each counting rule on purpose; the acceptance tests must fail.

    python tests/mutate.py

Each mutant changes one unique snippet in a copy of the package and runs
`tests.test_acceptance` there. A mutant counts as caught only when the run ends
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
SUITE = "tests.test_acceptance"

# (rule it breaks, file, snippet, replacement)
MUTANTS = [
    ("one response per message.id (criterion 4)", "transcript.py",
     "if mid in seen_segment:\n                    continue",
     "if mid in seen_segment:\n                    pass"),
    ("context includes the cache write (criterion 2)", "transcript.py",
     "+ (u.get(\"cache_creation_input_tokens\") or 0)", "+ 0"),
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
]


def run(where):
    p = subprocess.run([sys.executable, "-m", "unittest", SUITE], cwd=where, capture_output=True, timeout=120)
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
        print(f"{caught} of {len(MUTANTS)} mutants caught by {SUITE}")
        return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
