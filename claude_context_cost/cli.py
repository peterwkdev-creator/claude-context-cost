"""Command line: claude-context-cost <transcript.jsonl | folder>."""
import argparse
import json
import sys
from pathlib import Path

from . import __version__, example_path
from .attribute import FLOOR, analyze

TOP = 20


def label(key):
    return f"{key[0]}: {key[1]}"


def how_text(s):
    if not s.how:
        return "-"
    return ", ".join(k for k, _ in sorted(s.how.items(), key=lambda kv: -kv[1]))


def print_report(rep, top, out):
    total = rep.total or 1
    comp = f"{rep.compactions} compaction" + ("" if rep.compactions == 1 else "s")
    out.write(f"{Path(rep.path).name}: {len(rep.responses)} responses, {comp}, "
              f"{rep.total:,} input tokens over all responses\n")
    if rep.ratio_is_default:
        out.write(f"bytes per token: {rep.bytes_per_token:.2f} (default: only {rep.ratio_pairs} "
                  f"text-only steps here, too few to calibrate)\n")
    else:
        out.write(f"bytes per token: {rep.bytes_per_token:.2f} (median of {rep.ratio_pairs} "
                  f"text-only steps in this transcript)\n")
    if rep.bad_lines:
        out.write(f"skipped {rep.bad_lines} line(s) that are not JSON\n")
    out.write("\ncost = tokens x responses it stayed in context; entered = tokens it brought in\n")
    out.write(f"{'cost':>12} {'share':>6} {'entered':>9} {'in':>5}  {'chars/4':>9} {'error':>6}  "
              f"{'how':<20} source\n")
    rows = sorted(rep.sources.values(), key=lambda s: -s.cost)
    for s in rows[:top]:
        est = s.estimate_div4
        err = f"{(est - s.entered) / s.entered:+.0%}" if est is not None and s.entered > 0 else "-"
        est_txt = f"{est:,.0f}" if est is not None else "-"
        out.write(f"{s.cost:>12,} {s.cost / total:>6.1%} {s.entered:>9,} {s.responses:>5}  "
                  f"{est_txt:>9} {err:>6}  {how_text(s):<20} {label((s.kind, s.name))}\n")
    if len(rows) > top:
        rest = sum(s.cost for s in rows[top:])
        out.write(f"{rest:>12,} {rest / total:>6.1%}  ... {len(rows) - top} more sources (--all)\n")


def print_steps(rep, out):
    prev = None
    for n, r in enumerate(rep.responses, 1):
        start = " (segment start: the remainder is the system prompt and tools)" if r.segment_start else ""
        out.write(f"#{n} {r.id} context {r.context:,}{start}\n")
        if prev is not None and not r.segment_start:
            out.write(f"    {prev.output:>+9,}  output: responses (previous output)\n")
        for i in r.entered:
            out.write(f"    {i.tokens:>+9,}  {label(i.key)} ({i.bytes:,} B, {i.how})\n")
        before = {} if (r.segment_start or prev is None) else prev.ledger
        rest = r.ledger.get(FLOOR, 0) - before.get(FLOOR, 0)
        if rest:
            out.write(f"    {rest:>+9,}  unattributed\n")
        prev = r


def as_json(rep):
    return {
        "file": Path(rep.path).name, "version": __version__,
        "responses": len(rep.responses), "compactions": rep.compactions, "total": rep.total,
        "bad_lines": rep.bad_lines, "bytes_per_token": rep.bytes_per_token, "ratio_pairs": rep.ratio_pairs,
        "ratio_is_default": rep.ratio_is_default,
        "sources": [{"kind": s.kind, "name": s.name, "cost": s.cost, "entered": s.entered,
                     "responses": s.responses, "bytes": s.bytes, "chars": s.chars, "how": s.how}
                    for s in sorted(rep.sources.values(), key=lambda s: -s.cost)],
        "steps": [{"id": r.id, "context": r.context, "output": r.output,
                   "segment_start": r.segment_start,
                   "entered": [{"kind": i.kind, "name": i.name, "bytes": i.bytes, "tokens": i.tokens,
                                "how": i.how} for i in r.entered]} for r in rep.responses],
    }


def print_folder(folder, out, as_json_output=False):
    files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        if as_json_output:
            json.dump({"folder": folder.name, "version": __version__, "transcripts": []}, out, indent=1)
            out.write("\n")
        else:
            out.write(f"no .jsonl transcripts in {folder}\n")
        return 1
    rows = []
    for f in files:
        rep = analyze(f)
        top = max(rep.sources.values(), key=lambda s: s.cost, default=None)
        rows.append({"file": f.name, "responses": len(rep.responses), "compactions": rep.compactions,
                     "total": rep.total,
                     "top": {"kind": top.kind, "name": top.name, "cost": top.cost} if top else None})
    if as_json_output:
        json.dump({"folder": folder.name, "version": __version__, "transcripts": rows}, out, indent=1)
        out.write("\n")
        return 0
    out.write(f"{len(files)} transcripts in {folder.name} (oldest first); run on one file for the detail\n")
    for r in rows:
        top = r["top"]
        top_txt = f"top: {label((top['kind'], top['name']))} {top['cost'] / (r['total'] or 1):.0%}" if top else ""
        out.write(f"  {r['file']}  {r['responses']:>5} responses  {r['total']:>13,} tokens  {top_txt}\n")
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="claude-context-cost",
                                 description="How much each source costs in the context of a Claude Code "
                                             "session, counted from the API usage in its transcript.")
    ap.add_argument("path", nargs="?", help="a transcript (.jsonl) or a folder of them "
                                            "(usually ~/.claude/projects/<project>)")
    ap.add_argument("--example", action="store_true", help="run on the synthetic transcript shipped with the tool")
    ap.add_argument("--steps", action="store_true", help="also show what entered before each response")
    ap.add_argument("--all", action="store_true", help="list every source, not only the top 20")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--version", action="version", version=f"claude-context-cost {__version__}")
    a = ap.parse_args(argv)
    out = sys.stdout
    if a.example:
        target = example_path()
    elif a.path:
        target = Path(a.path).expanduser()
    else:
        ap.error("give a transcript or a folder, or --example")
    if target.is_dir():
        if a.steps or a.all:
            ap.error("--steps and --all need one transcript, not a folder")
        return print_folder(target, out, a.json)
    if not target.is_file():
        ap.error(f"not found: {target}")
    rep = analyze(target)
    if a.json:
        json.dump(as_json(rep), out, indent=1)
        out.write("\n")
        return 0
    print_report(rep, len(rep.sources) if a.all else TOP, out)
    if a.steps:
        out.write("\n")
        print_steps(rep, out)
    return 0
