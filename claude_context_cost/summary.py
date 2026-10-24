"""Sums many transcripts: a project folder with its subagents, or every project.

A source is the same across transcripts when its kind and name are: `tool: Read`
everywhere, the user's own `~/.claude/CLAUDE.md` in every project. A project's
own file (`CLAUDE.md`, `.claude/rules/x.md`) is named relative to the project
folder, so the same name in two projects is two files: those keep their project.

A resumed or forked session starts its own file with the responses of the one
it came from, under the same `message.id`: each response is summed once, in
the first transcript read (oldest first) that has it.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .attribute import Source, analyze

LOCAL_KINDS = ("claude.md", "rule", "path rule")


@dataclass
class Total:
    """One source summed over many transcripts."""
    kind: str
    name: str
    project: str = ""    # set only for a project's own file
    cost: int = 0        # tokens x responses it stayed in, summed
    entered: int = 0
    chars: int = 0
    opaque: int = 0
    transcripts: int = 0  # transcripts it appeared in

    @property
    def estimate_div4(self):
        """What a characters / 4 estimate would say it entered, or None if it has no text."""
        return self.chars / 4 if self.chars and not self.opaque else None


@dataclass
class Row:
    """One transcript of the sum."""
    file: str
    project: str
    session: str         # for a subagent, the session it belongs to; "" for a session
    responses: int
    compactions: int
    total: int
    top: object = None   # its costliest Source, or None
    repeated: int = 0    # responses left out: already summed from another transcript


@dataclass
class Summary:
    path: str
    projects: list       # project folder names
    rows: list           # project by project: its sessions oldest first, then its subagents
    sources: dict = field(default_factory=dict)   # (kind, name, project) -> Total

    @property
    def total(self):
        return sum(r.total for r in self.rows)

    @property
    def responses(self):
        return sum(r.responses for r in self.rows)


def _is_local(kind, name):
    return kind in LOCAL_KINDS and not name.startswith(("~", "/")) and not re.match(r"[A-Za-z]:/", name)


def _transcripts(folder):
    """The sessions of one project folder and their subagents, each oldest first."""
    by_time = lambda p: p.stat().st_mtime
    return (sorted(folder.glob("*.jsonl"), key=by_time),
            sorted(folder.glob("*/subagents/*.jsonl"), key=by_time))


def _key(path, r):
    # an id made from the line number (no message.id, request id or uuid) is only unique in its file
    return (str(path), r.id) if r.id.startswith("line ") else r.id


def _sources_of(rep, keep):
    """The sources of only the responses in keep, summed as `attribute` sums a whole transcript."""
    out, prev = {}, None

    def source(k):
        if k not in out:
            out[k] = Source(*k)
        return out[k]

    for r in rep.responses:
        before = {} if (r.segment_start or prev is None) else prev.ledger
        prev = r
        if id(r) not in keep:
            continue
        for k in set(r.ledger) | set(before):   # each ledger is the previous one plus what entered
            source(k).entered += r.ledger.get(k, 0) - before.get(k, 0)
        for k, v in r.ledger.items():
            source(k).cost += v
            source(k).responses += 1
        for i in r.entered:
            s = source(i.key)
            s.bytes += i.bytes
            s.chars += i.chars
            s.opaque += i.opaque
            s.how[i.how] = s.how.get(i.how, 0) + 1
    return {k: s for k, s in out.items() if s.entered or s.cost}


def summarize(path):
    """Sum every transcript in a project folder, or in each project of a folder of projects.

    A project folder is one of `~/.claude/projects/<project>`: its sessions and
    the subagents under `<session-id>/subagents/`. Any other folder is read as a
    folder of projects, like `~/.claude/projects` itself.
    """
    folder = Path(path)
    sessions, subagents = _transcripts(folder)
    if sessions or subagents:
        projects = [(folder.name, sessions, subagents)]
    else:
        projects = []
        for d in sorted(p for p in folder.iterdir() if p.is_dir()):
            s, a = _transcripts(d)
            if s or a:
                projects.append((d.name, s, a))
    summary = Summary(str(folder), [p for p, _, _ in projects], [])
    seen = set()   # every response summed so far
    for project, s, a in projects:
        for f, is_subagent in [(f, False) for f in s] + [(f, True) for f in a]:
            rep = analyze(f)
            keys = [_key(f, r) for r in rep.responses]
            counted = [r for r, k in zip(rep.responses, keys) if k not in seen]
            seen.update(keys)
            repeated = len(rep.responses) - len(counted)
            sources = _sources_of(rep, {id(r) for r in counted}) if repeated else rep.sources
            top = max(sources.values(), key=lambda x: x.cost, default=None)
            summary.rows.append(Row(f.name, project, f.parent.parent.name if is_subagent else "",
                                    len(counted), rep.compactions, sum(r.context for r in counted), top,
                                    repeated))
            for src in sources.values():
                key = (src.kind, src.name, project if _is_local(src.kind, src.name) else "")
                t = summary.sources.get(key)
                if t is None:
                    t = summary.sources[key] = Total(*key)
                t.cost += src.cost
                t.entered += src.entered
                t.chars += src.chars
                t.opaque += src.opaque
                t.transcripts += 1
    return summary
