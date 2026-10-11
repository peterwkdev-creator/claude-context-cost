"""Command line: claude-context-cost <transcript.jsonl | folder>, or --budget FILE [repository]."""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__, example_path
from .attribute import FLOOR, analyze
from .budget import BudgetError, check_budget
from .summary import summarize
from .versions import loaded_versions

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
        out.write(f"skipped: {plural(rep.bad_lines, 'line')} not in JSON\n")
    out.write("\ncost: tokens x responses it stayed in context; share: of all input tokens; "
              "entered: tokens it brought in\n"
              "in: responses it stayed in; chars/4: the usual estimate; error: chars/4 against entered "
              "(-38% = 38% too low)\n"
              "how: measured from the usage, split by bytes, or estimated (README, \"What it counts\")\n")
    rows = sorted(rep.sources.values(), key=lambda s: -s.cost)
    wide = max([20] + [len(how_text(s)) for s in rows[:top]])
    out.write(f"{'cost':>12} {'share':>6} {'entered':>9} {'in':>5}  {'chars/4':>9} {'error':>6}  "
              f"{'how':<{wide}} source\n")
    for s in rows[:top]:
        est = s.estimate_div4
        err = f"{(est - s.entered) / s.entered:+.0%}" if est is not None and s.entered > 0 else "-"
        est_txt = f"{est:,.0f}" if est is not None else "-"
        out.write(f"{s.cost:>12,} {s.cost / total:>6.1%} {s.entered:>9,} {s.responses:>5}  "
                  f"{est_txt:>9} {err:>6}  {how_text(s):<{wide}} {label((s.kind, s.name))}\n")
    if len(rows) > top:
        rest = sum(s.cost for s in rows[top:])
        out.write(f"{rest:>12,} {rest / total:>6.1%}  ... {len(rows) - top} more sources (--all)\n")


def print_steps(rep, out):
    prev = None
    for n, r in enumerate(rep.responses, 1):
        start = (" (start of the session or after a compaction: the rest is the system prompt and the tool "
                 "definitions)" if r.segment_start else "")
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


def version_text(v):
    if v.commit:
        return f"{v.commit[:7]} {v.commit_date}" + (" (later)" if v.committed_after else "")
    return "not committed" if v.git else "no git"


def today_text(v):
    if v.today == "changed":
        return f"{v.today_tokens:+,} tokens" if v.today_tokens else "changed"
    return v.today or "-"


def print_versions(vs, out):
    out.write("CLAUDE.md, rules and memory as this session loaded them: their git version, and today's file\n")
    if not vs:
        out.write("\nnone loaded\n")
        return
    out.write(f"\n{'tokens':>9} {'loads':>6}  {'version':<30}  {'today':<14}  file\n")
    for v in vs:
        out.write(f"{v.tokens:>9,} {v.loads:>6}  {version_text(v):<30}  {today_text(v):<14}  "
                  f"{label((v.kind, v.name))}\n")
    out.write("\nversion: the commit with exactly this text; (later): committed only after it was loaded\n"
              "  not committed: no commit has this text; no git: the file is not in a git repository\n"
              "today: the file on disk now, as Claude Code would load it: same, +N or -N tokens (grew or "
              "shrank since), changed, or not found\n")
    if all(v.today == "not found" for v in vs):
        out.write("\nnone of these files is on this machine (as with --example)\n")


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
    out.write("\ncost: tokens x responses it stayed in context, summed; share: of all input tokens; "
              "entered: tokens it brought in\n"
              "in: transcripts it was in (not responses, as for one file); chars/4: the usual estimate; "
              "error: chars/4 against entered\n")
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


def print_budget(b, root, out, quiet=False):
    if quiet:
        # for a hook: only the verdict, and what exceeded
        return print_verdict(b, out, "")
    ratio = "default" if b.ratio_is_default else f"declared in {Path(b.budget_file).name}"
    out.write(f"context budget of {Path(root).resolve().name}: {plural(len(b.files), 'instruction file')}, "
              f"{b.bytes_per_token:.2f} bytes per token ({ratio})\n")
    out.write(f"\n{'tokens':>9} {'limit':>9}  {'loaded':<9}  file\n")
    for f in b.files:
        limit = f"{f.limit:,}" if f.limit is not None else "-"
        mark = "  OVER" if f.limit is not None and f.tokens > f.limit else ""
        via = f" (imported by {f.imported_by})" if f.imported_by else ""
        out.write(f"{f.tokens:>9,} {limit:>9}  {'start-up' if f.start else 'on demand':<9}  "
                  f"{label((f.kind, f.name))}{via}{mark}\n")
    limit = f"{b.start_limit:,}" if b.start_limit is not None else "-"
    mark = "  OVER" if b.start_limit is not None and b.start_tokens > b.start_limit else ""
    out.write(f"{b.start_tokens:>9,} {limit:>9}  start-up total{mark}\n")
    out.write("\nnot counted, as not in the repository: your ~/.claude/CLAUDE.md, memory and any CLAUDE.md "
              "above it\n")
    if b.outside:
        out.write(f"not counted: {plural(len(b.outside), 'import')} outside the repository "
                  f"({', '.join(sorted(set(b.outside)))})\n")
    return print_verdict(b, out, "\n")


def print_verdict(b, out, gap):
    if b.ok:
        out.write(f"{gap}within budget\n")
        return 0
    out.write(f"{gap}over budget: {plural(len(b.over), 'limit')} exceeded\n")
    for o in b.over:
        what = label((o.kind, o.name)) if o.kind else o.name
        where = f" (limit \"{o.pattern}\")" if o.pattern else " (limit startup)"
        out.write(f"  {what}: {o.tokens:,} tokens > {o.limit:,}{where}\n")
    return 1


def run_budget(budget_file, root, out, as_json_output=False, quiet=False):
    try:
        b = check_budget(root, budget_file)
    except (BudgetError, OSError) as e:
        sys.stderr.write(f"claude-context-cost: error: {e}\n")
        return 2
    if as_json_output:
        json.dump(budget_json(b), out, indent=1)
        out.write("\n")
        return 0 if b.ok else 1
    return print_budget(b, root, out, quiet)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="claude-context-cost",
                                 description="How much each source costs in the context of a Claude Code "
                                             "session, counted from the API usage in its transcript.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="examples:\n"
                                        "  claude-context-cost --example\n"
                                        "  claude-context-cost ~/.claude/projects/<project>/<session>.jsonl\n"
                                        "  claude-context-cost ~/.claude/projects/<project>\n"
                                        "  claude-context-cost --budget context-budget.toml\n\n"
                                        "Transcripts are in ~/.claude/projects (%USERPROFILE%\\.claude\\projects "
                                        "on Windows).\n"
                                        "What each column means, and the budget file: "
                                        "https://github.com/peterwkdev-creator/claude-context-cost")
    ap.add_argument("path", nargs="?", help="a transcript (.jsonl), or a folder to sum: a project's "
                                            "(~/.claude/projects/<project>) or ~/.claude/projects for all; "
                                            "with --budget, the repository folder (default: the current one)")
    ap.add_argument("--example", action="store_true", help="run on the synthetic transcript shipped with the tool")
    ap.add_argument("--steps", action="store_true", help="also show what entered before each response")
    ap.add_argument("--all", action="store_true", help="list every source, not only the top 20")
    ap.add_argument("--versions", action="store_true",
                    help="also show which git commit had each CLAUDE.md, rule and memory file exactly as the "
                         "session loaded it, and how today's file differs")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--budget", metavar="FILE",
                    help="check a repository against the limits in a TOML file: the CLAUDE.md, rules and "
                         "imports Claude Code loads from it, in estimated tokens; exit code 1 if a limit is "
                         "exceeded, 2 if the budget file or the command line is invalid; the FILE path is "
                         "from where you run it")
    ap.add_argument("--quiet", action="store_true",
                    help="with --budget: print only the verdict and the limits exceeded (for a git hook)")
    ap.add_argument("--version", action="version", version=f"claude-context-cost {__version__}")
    a = ap.parse_args(argv)
    out = sys.stdout
    if a.budget is not None:
        if not a.budget:
            ap.error("--budget needs a file name")
        if a.example or a.steps or a.all or a.versions:
            ap.error("--budget cannot be combined with --example, --steps, --all or --versions "
                     "(those read a transcript; --budget reads a repository)")
        root = Path(a.path or ".").expanduser()
        if not root.is_dir():
            ap.error(f"--budget needs a repository folder: {root}")
        return run_budget(Path(a.budget).expanduser(), root, out, a.json, a.quiet)
    if a.quiet:
        ap.error("--quiet is for --budget")
    if a.example:
        target = example_path()
    elif a.path:
        target = Path(a.path).expanduser()
    else:
        ap.error("give a transcript (.jsonl) or a folder from ~/.claude/projects, or try --example")
    if target.is_dir():
        if a.steps or a.versions:
            ap.error("--steps and --versions need one transcript, not a folder")
        return print_folder(target, 10 ** 9 if a.all else TOP, out, a.json)
    if not target.is_file():
        ap.error(f"no such file or folder: {target} (transcripts are in ~/.claude/projects/<project>/)")
    rep = analyze(target)
    vs = loaded_versions(target, rep.bytes_per_token) if a.versions else None
    if a.json:
        data = as_json(rep)
        if vs is not None:
            data["versions"] = [asdict(v) for v in vs]
        json.dump(data, out, indent=1)
        out.write("\n")
        return 0
    print_report(rep, len(rep.sources) if a.all else TOP, out)
    if a.steps:
        out.write("\n")
        print_steps(rep, out)
    if vs is not None:
        out.write("\n")
        print_versions(vs, out)
    return 0
