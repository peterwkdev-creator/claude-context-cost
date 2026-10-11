"""Sums many transcripts: a project folder with its subagents, or every project.

A source is the same across transcripts when its kind and name are: `tool: Read`
everywhere, the user's own `~/.claude/CLAUDE.md` in every project. A project's
own file (`CLAUDE.md`, `.claude/rules/x.md`) is named relative to the project
folder, so the same name in two projects is two files: those keep their project.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .attribute import analyze

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
    for project, s, a in projects:
        for f, is_subagent in [(f, False) for f in s] + [(f, True) for f in a]:
            rep = analyze(f)
            top = max(rep.sources.values(), key=lambda x: x.cost, default=None)
            summary.rows.append(Row(f.name, project, f.parent.parent.name if is_subagent else "",
                                    len(rep.responses), rep.compactions, rep.total, top))
            for src in rep.sources.values():
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
