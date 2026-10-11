"""Command line: claude-context-cost <transcript.jsonl | folder>, or --budget FILE [repository]."""
import argparse
import json
import sys
from pathlib import Path

from . import __version__, example_path
from .attribute import FLOOR, analyze
from .budget import BudgetError, check_budget
from .summary import summarize

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


def plural(n, word):
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def folder_json(s):
    def row(r):
        top = {"kind": r.top.kind, "name": r.top.name, "cost": r.top.cost} if r.top else None
        d = {"file": r.file, "project": r.project, "responses": r.responses, "compactions": r.compactions,
             "total": r.total, "top": top}
        return {**d, "session": r.session} if r.session else d
    return {
        "folder": Path(s.path).name, "version": __version__, "responses": s.responses, "total": s.total,
        "projects": [{"name": p, "transcripts": sum(1 for r in s.rows if r.project == p and not r.session),
                      "subagents": sum(1 for r in s.rows if r.project == p and r.session),
                      "responses": sum(r.responses for r in s.rows if r.project == p),
                      "total": sum(r.total for r in s.rows if r.project == p)} for p in s.projects],
        "transcripts": [row(r) for r in s.rows if not r.session],
        "subagents": [row(r) for r in s.rows if r.session],
        "sources": [{"kind": t.kind, "name": t.name, "project": t.project, "cost": t.cost, "entered": t.entered,
                     "chars": t.chars, "transcripts": t.transcripts}
                    for t in sorted(s.sources.values(), key=lambda t: -t.cost)],
    }


def print_folder(folder, top, out, as_json_output=False):
    s = summarize(folder)
    if as_json_output:
        json.dump(folder_json(s), out, indent=1)
        out.write("\n")
        return 0 if s.rows else 1
    if not s.rows:
        out.write(f"no .jsonl transcripts in {folder}\n")
        return 1
    sessions = [r for r in s.rows if not r.session]
    many = len(s.projects) > 1
    total = s.total or 1
    head = f"{plural(len(s.projects), 'project')}, " if many else ""
    out.write(f"{Path(s.path).name}: {head}{plural(len(sessions), 'transcript')} and "
              f"{plural(len(s.rows) - len(sessions), 'subagent transcript')}, "
              f"{plural(s.responses, 'response')}, {s.total:,} input tokens over all responses\n")
    out.write("\ncost = tokens x responses it stayed in context, summed; entered = tokens it brought in; "
              "in = transcripts it was in\n")
    out.write(f"{'cost':>14} {'share':>6} {'entered':>11} {'in':>5}  {'chars/4':>11} {'error':>6}  source\n")
    rows = sorted(s.sources.values(), key=lambda t: -t.cost)
    for t in rows[:top]:
        est = t.estimate_div4
        err = f"{(est - t.entered) / t.entered:+.0%}" if est is not None and t.entered > 0 else "-"
        est_txt = f"{est:,.0f}" if est is not None else "-"
        where = f"  [{t.project}]" if many and t.project else ""
        out.write(f"{t.cost:>14,} {t.cost / total:>6.1%} {t.entered:>11,} {t.transcripts:>5}  "
                  f"{est_txt:>11} {err:>6}  {label((t.kind, t.name))}{where}\n")
    if len(rows) > top:
        rest = sum(t.cost for t in rows[top:])
        out.write(f"{rest:>14,} {rest / total:>6.1%}  ... {len(rows) - top} more sources (--all)\n")
    if many:
        out.write("\nprojects, costliest first; run on a project's folder for its transcripts\n")
        for p in sorted(folder_json(s)["projects"], key=lambda p: -p["total"]):
            out.write(f"  {p['name']}  {plural(p['transcripts'], 'transcript')}, "
                      f"{plural(p['subagents'], 'subagent')}, {p['responses']:>7,} responses  "
                      f"{p['total']:>15,} tokens\n")
        return 0
    out.write("\ntranscripts, oldest first; run on one file for the detail\n")
    for r in sessions:
        top_txt = f"top: {label((r.top.kind, r.top.name))} {r.top.cost / (r.total or 1):.0%}" if r.top else ""
        subs = [x for x in s.rows if x.session == Path(r.file).stem]
        sub_txt = (f"  (+{plural(len(subs), 'subagent')}, {sum(x.total for x in subs):,} tokens)"
                   if subs else "")
        out.write(f"  {r.file}  {r.responses:>5} responses  {r.total:>13,} tokens  {top_txt}{sub_txt}\n")
    return 0


def budget_json(b):
    return {
        "budget": Path(b.budget_file).name, "version": __version__, "ok": b.ok,
        "bytes_per_token": b.bytes_per_token, "ratio_is_default": b.ratio_is_default,
        "startup": {"tokens": b.start_tokens, "limit": b.start_limit},
        "files": [{"kind": f.kind, "name": f.name, "bytes": f.bytes, "tokens": f.tokens, "startup": f.start,
                   "imported_by": f.imported_by or None, "limit": f.limit} for f in b.files],
        "over": [{"kind": o.kind or None, "name": o.name, "tokens": o.tokens, "limit": o.limit,
                  "pattern": o.pattern or None} for o in b.over],
        "outside": b.outside,
    }


def print_budget(b, out):
    ratio = "default" if b.ratio_is_default else f"declared in {Path(b.budget_file).name}"
    out.write(f"context budget: {plural(len(b.files), 'instruction file')}, "
              f"{b.bytes_per_token:.2f} bytes per token ({ratio})\n")
    out.write(f"\n{'tokens':>9} {'limit':>9}  {'loaded':<9} file\n")
    for f in b.files:
        limit = f"{f.limit:,}" if f.limit is not None else "-"
        mark = "  OVER" if f.limit is not None and f.tokens > f.limit else ""
        via = f" (imported by {f.imported_by})" if f.imported_by else ""
        out.write(f"{f.tokens:>9,} {limit:>9}  {'start-up' if f.start else 'on demand':<9} "
                  f"{label((f.kind, f.name))}{via}{mark}\n")
    limit = f"{b.start_limit:,}" if b.start_limit is not None else "-"
    mark = "  OVER" if b.start_limit is not None and b.start_tokens > b.start_limit else ""
    out.write(f"{b.start_tokens:>9,} {limit:>9}  start-up total{mark}\n")
    if b.outside:
        out.write(f"\nnot counted: {plural(len(b.outside), 'import')} outside the repository "
                  f"({', '.join(sorted(set(b.outside)))})\n")
    if b.ok:
        out.write("\nwithin budget\n")
        return 0
    out.write(f"\nover budget: {plural(len(b.over), 'limit')} passed\n")
    for o in b.over:
        what = label((o.kind, o.name)) if o.kind else o.name
        where = f" (limit \"{o.pattern}\")" if o.pattern else " (limit startup)"
        out.write(f"  {what}: {o.tokens:,} tokens > {o.limit:,}{where}\n")
    return 1


def run_budget(budget_file, root, out, as_json_output=False):
    try:
        b = check_budget(root, budget_file)
    except (BudgetError, OSError) as e:
        sys.stderr.write(f"claude-context-cost: {e}\n")
        return 2
    if as_json_output:
        json.dump(budget_json(b), out, indent=1)
        out.write("\n")
        return 0 if b.ok else 1
    return print_budget(b, out)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="claude-context-cost",
                                 description="How much each source costs in the context of a Claude Code "
                                             "session, counted from the API usage in its transcript.")
    ap.add_argument("path", nargs="?", help="a transcript (.jsonl), or a folder to sum: a project's "
                                            "(~/.claude/projects/<project>) or ~/.claude/projects for all")
    ap.add_argument("--example", action="store_true", help="run on the synthetic transcript shipped with the tool")
    ap.add_argument("--steps", action="store_true", help="also show what entered before each response")
    ap.add_argument("--all", action="store_true", help="list every source, not only the top 20")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--budget", metavar="FILE",
                    help="check a repository (the path, or the current folder) against the limits in a TOML "
                         "file: the CLAUDE.md, rules and imports Claude Code loads from it, in estimated "
                         "tokens; exit code 1 if a limit is passed, 2 if the budget file is invalid")
    ap.add_argument("--version", action="version", version=f"claude-context-cost {__version__}")
    a = ap.parse_args(argv)
    out = sys.stdout
    if a.budget:
        if a.example or a.steps or a.all:
            ap.error("--budget takes a repository folder; --example, --steps and --all are for transcripts")
        root = Path(a.path or ".").expanduser()
        if not root.is_dir():
            ap.error(f"--budget needs a repository folder: {root}")
        return run_budget(Path(a.budget).expanduser(), root, out, a.json)
    if a.example:
        target = example_path()
    elif a.path:
        target = Path(a.path).expanduser()
    else:
        ap.error("give a transcript or a folder, or --example")
    if target.is_dir():
        if a.steps:
            ap.error("--steps needs one transcript, not a folder")
        return print_folder(target, 10 ** 9 if a.all else TOP, out, a.json)
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
