"""Showcase adapter: connects claude_context_cost to the page (vitrine/index.html).

Runs the same here and in the browser (Pyodide); `vitrine/montar.py` runs it
with the example before building. `executar(entradas)` gets
{"transcript": text of the chosen .jsonl, or "" for the synthetic example
shipped with the package} and returns the summary, the limit of the result
and the table of sources, in the format `montar.conferir_resultado` checks.
"""
import os
import tempfile

from claude_context_cost import analyze, example_path

TOP = 30
COLUMNS = ["Source", "How", "Entered", "In", "Cost", "Share", "Chars / 4", "Error"]


def _report(text):
    if not text.strip():
        return analyze(example_path())
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return analyze(path)
    finally:
        os.remove(path)


def _how(s):
    return ", ".join(k for k, _ in sorted(s.how.items(), key=lambda kv: -kv[1])) or "-"


def _row(s, total):
    est = s.estimate_div4
    err = f"{(est - s.entered) / s.entered:+.0%}" if est is not None and s.entered > 0 else "-"
    return [f"{s.kind}: {s.name}", _how(s), f"{s.entered:,}", f"{s.responses:,}", f"{s.cost:,}",
            f"{s.cost / total:.1%}", f"{est:,.0f}" if est is not None else "-", err]


def executar(entradas):
    rep = _report(entradas.get("transcript", ""))
    n = len(rep.responses)
    if not n:
        return {"resumo": "No responses with usage in this file: is it a Claude Code transcript (.jsonl)?"}
    total = rep.total or 1
    rows = sorted(rep.sources.values(), key=lambda s: -s.cost)
    comp = f"{rep.compactions} compaction" + ("" if rep.compactions == 1 else "s")
    named = [s for s in rows if s.kind not in ("unattributed", "output")] or rows
    top = named[0]
    linhas = [_row(s, total) for s in rows[:TOP]]
    if len(rows) > TOP:
        rest = sum(s.cost for s in rows[TOP:])
        linhas.append([f"{len(rows) - TOP} more sources", "-", "-", "-", f"{rest:,}",
                       f"{rest / total:.1%}", "-", "-"])
    ratio = (f"default {rep.bytes_per_token:.2f} (only {rep.ratio_pairs} text-only steps)"
             if rep.ratio_is_default else
             f"{rep.bytes_per_token:.2f}, median of {rep.ratio_pairs} text-only steps")
    skipped = f" Skipped {rep.bad_lines} line(s) that are not JSON." if rep.bad_lines else ""
    return {
        "resumo": (f"{n} responses, {comp}, {rep.total:,} input tokens over all responses; "
                   f"{len(rows)} sources, the costliest you can act on is {top.kind}: {top.name} "
                   f"({top.cost / total:.1%})."),
        "aviso": ("Entered = tokens the source brought into the context; in = responses it stayed "
                  "in; cost = tokens x responses; chars / 4 = the usual estimate, and its error. "
                  "Measured = the source entered alone between two responses; split = several "
                  "entered together and share the tokens by size; estimated = start of a session "
                  f"or after a compaction, by bytes per token ({ratio}).{skipped}"),
        "tabela": {"titulo": "Sources by cost", "colunas": COLUMNS, "linhas": linhas},
    }
