"""Which version of each CLAUDE.md, rule and memory file a session loaded, found in git.

The transcript holds the text Claude Code loaded, so the counting never reads
today's files. This answers the next questions: which commit had that text,
and is today's file still the same? A commit is reported only when its file,
rendered as Claude Code renders it (see `budget.render`), equals the loaded
text. On the author's machine (2026-10-11) only 290 of 2,863 distinct texts
loaded still matched today's file: the others had changed or were gone.

Git is only read (`log` and `cat-file`), with literal paths. Only `.md` files
named by the transcript are looked up.
"""
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .attribute import analyze
from .budget import render
from .transcript import USER_FILES, _norm, _subagent_only, short_path


@dataclass
class Version:
    kind: str           # "claude.md", "rule", "path rule" or "memory", as in the report
    name: str           # as in the report
    path: str           # as the transcript names it
    bytes: int          # of the text the session loaded
    tokens: int         # bytes / the transcript's ratio
    loads: int          # times this text was loaded in the session
    loaded: str         # when it was first loaded, ISO 8601 UTC
    git: bool           # the file is in a git repository
    commit: str = ""    # the commit whose file is this text; "" if none is
    commit_date: str = ""   # its commit date, YYYY-MM-DD
    committed_after: bool = False   # no commit before the load had it; the first one after does
    today: str = ""     # "same", "changed" or "not found"
    today_bytes: int = 0    # today's rendered file minus the loaded text, in bytes
    today_tokens: int = 0


def _kind(att_type, f, path):
    if att_type == "nested_memory":
        return "path rule" if f.get("globs") or "/.claude/rules/" in path else "claude.md"
    if f.get("type") == "AutoMem":
        return "memory"
    return "rule" if "/.claude/rules/" in path else "claude.md"


def loaded_files(path):
    """[(kind, name, path, text, start, unix time)] for every instruction file a session loaded."""
    out = []
    skip_side = not _subagent_only(path)
    cwd = ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"instructions"' not in line and '"nested_memory"' not in line:
                if '"cwd"' in line:
                    try:
                        cwd = json.loads(line).get("cwd") or cwd
                    except (ValueError, AttributeError):
                        pass
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict) or (skip_side and e.get("isSidechain")):
                continue
            cwd = e.get("cwd") or cwd
            a = e.get("attachment")
            if not e.get("rendered") or not isinstance(a, dict):
                continue
            try:
                when = datetime.fromisoformat(str(e.get("timestamp")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                when = None
            if a.get("type") == "instructions":
                files = [(f, f.get("content"), True) for f in a.get("files") or [] if isinstance(f, dict)]
            elif a.get("type") == "nested_memory":
                c = a.get("content") if isinstance(a.get("content"), dict) else {}
                files = [({"path": a.get("path") or c.get("path"), "globs": c.get("globs")},
                          c.get("content"), False)]
            else:
                continue
            for f, text, start in files:
                p = _norm(f.get("path"))
                if p and isinstance(text, str) and text:
                    out.append((_kind(a.get("type"), f, p), short_path(p, cwd, f.get("type") in USER_FILES),
                                p, text, start, when))
    return out


def _git(cwd, *args, stdin=None):
    try:
        # a user's log.showSignature would print signatures into the log's output
        r = subprocess.run(["git", "-c", "log.showSignature=false", "--literal-pathspecs", "-C", cwd, *args],
                           input=stdin,
                           capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _top(path):
    """The repository holding path (it may be deleted): (top folder, path relative to it) or None."""
    d = Path(path).parent
    while not d.is_dir():
        if d.parent == d:
            return None
        d = d.parent
    # git names the folder's place in the repository itself: comparing the path with the top folder
    # would fail where one path has two spellings (a Windows short name, RUNNER~1)
    out = _git(str(d), "rev-parse", "--show-toplevel", "--show-prefix")
    if not out:
        return None
    lines = out.decode("utf-8", "replace").splitlines()
    if len(lines) < 1 or not lines[0]:
        return None
    top, prefix = lines[0], lines[1] if len(lines) > 1 else ""
    rest = os.path.relpath(path, d).replace(os.sep, "/")   # d is path's own parent: same spelling
    return top, prefix + rest


def _history(top, rel):
    """[(commit, unix time, text)] of every commit that has the file, newest first."""
    log = _git(top, "log", "--format=%H %ct", "--", rel)
    if not log:
        return []
    commits = [ln.split() for ln in log.decode().splitlines() if ln.strip()]
    batch = _git(top, "cat-file", "--batch", stdin="".join(f"{h}:{rel}\n" for h, _ in commits).encode())
    out, i = [], 0
    for h, t in commits:
        if batch is None:
            break
        j = batch.find(b"\n", i)
        if j < 0:   # output cut short: keep what was read
            break
        head = batch[i:j].split()
        i = j + 1
        if len(head) == 3 and head[1] == b"blob":
            n = int(head[2])
            out.append((h, int(t), batch[i:i + n].decode("utf-8", "replace")))
            i += n + 1
    return out


def _same(a, b):
    # git may hold the file with LF while it was checked out with CRLF
    return a.replace("\r\n", "\n") == b.replace("\r\n", "\n")


def loaded_versions(path, bytes_per_token=None):
    """One `Version` per distinct text of each instruction file the session loaded, in load order."""
    if bytes_per_token is None:
        bytes_per_token = analyze(path).bytes_per_token
    seen, out, histories = {}, [], {}
    for kind, name, p, text, start, when in loaded_files(path):
        key = (p, text)
        if key in seen:
            seen[key].loads += 1
            continue
        b = len(text.encode("utf-8"))
        v = Version(kind, name, p, b, round(b / bytes_per_token), 1,
                    datetime.fromtimestamp(when, timezone.utc).isoformat() if when is not None else "", False)
        seen[key] = v
        out.append(v)
        if not p.lower().endswith(".md"):
            continue
        f = Path(p)
        if f.is_file():
            now = render(f.read_bytes().decode("utf-8", "replace"), start)
            v.today = "same" if now == text else "changed"
            v.today_bytes = len(now.encode("utf-8")) - b
            v.today_tokens = round(v.today_bytes / bytes_per_token)
        else:
            v.today = "not found"
        where = _top(p)
        if where is None:
            continue
        v.git = True
        if where not in histories:
            histories[where] = _history(*where)
        hits = [(h, t) for h, t, blob in histories[where] if _same(render(blob, start), text)]
        if not hits:
            continue
        before = [x for x in hits if when is None or x[1] <= when]
        h, t = before[0] if before else hits[-1]
        v.commit, v.committed_after = h, not before
        v.commit_date = datetime.fromtimestamp(t, timezone.utc).date().isoformat()
    return out
