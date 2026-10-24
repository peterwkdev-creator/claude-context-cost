"""Context budget for a repository: what Claude Code loads from it, held to declared ceilings.

There is no transcript in CI, so the files are measured as Claude Code renders
them: frontmatter and HTML comment blocks taken out, blank ends stripped (only
the start for a file loaded on demand), line ends kept unless a comment was
taken out. On the author's transcripts (tests/test_corpus.py) the files found
were the ones Claude Code loaded in 257 of 257 start-ups and 252 of 252
on-demand loads, with the same bytes in 268 of 268 files. Bytes become tokens
by a ratio: the one declared in the budget, or 2.25 bytes per token.

Loaded at start-up: CLAUDE.md, .claude/CLAUDE.md, CLAUDE.local.md, rules in
.claude/rules without `paths:`, and the files they import with `@path`. Loaded
on demand: rules with `paths:` and the CLAUDE.md of a subfolder, with their
imports.
"""
import math
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .attribute import DEFAULT_BYTES_PER_TOKEN

FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
# a comment that starts a line is an HTML block: it goes with the blank lines after it
COMMENT_BLOCK = re.compile(r"(?ms)^[ \t]*<!--.*?-->[ \t]*(?:\n|\Z)(?:[ \t]*\n)*")
PATHS_KEY = re.compile(r"(?m)^paths[ \t]*:")
IMPORT = re.compile(r"(?<![\w`])@((?:~|\.{1,2})?[\w./~-]*[\w-])")
CODE_BLOCK = re.compile(r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1")
CODE_SPAN = re.compile(r"`[^`\n]*`")
MAX_IMPORT_DEPTH = 5
START_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")
KEYS = {"bytes_per_token", "startup", "limits"}


class BudgetError(ValueError):
    """The budget file cannot be used: bad TOML, unknown key, bad limit, or a pattern that matches no file."""


@dataclass
class File:
    kind: str           # "claude.md", "rule" or "path rule", as in a transcript
    name: str           # path relative to the repository, with /
    bytes: int
    tokens: int
    start: bool         # loaded at start-up (else on demand)
    imported_by: str = ""
    limit: int = None   # the smallest limit among the patterns that match it


@dataclass
class Over:
    name: str
    kind: str
    tokens: int
    limit: int
    pattern: str        # "" for the start-up total


@dataclass
class Budget:
    root: str
    budget_file: str
    bytes_per_token: float
    ratio_is_default: bool
    files: list = field(default_factory=list)
    start_tokens: int = 0
    start_limit: int = None
    over: list = field(default_factory=list)
    outside: list = field(default_factory=list)   # imports and links that resolve outside the repository

    @property
    def ok(self):
        return not self.over


def render(text, start=True):
    """The text Claude Code sends for an instruction file, loaded at start-up or on demand."""
    t = text.replace("\r\n", "\n")
    t = FRONTMATTER.sub("", t, 1)
    comments = "<!--" in t
    t = COMMENT_BLOCK.sub("", t)
    # at start-up both ends are stripped; on demand only the start
    t = t.strip() if start else t.lstrip()
    # the file's own line ends are kept (\r is a byte too), unless comments were taken out
    return t.replace("\n", "\r\n") if "\r\n" in text and not comments else t


def _has_paths(text):
    m = FRONTMATTER.match(text.replace("\r\n", "\n"))
    return bool(m and PATHS_KEY.search(m.group(1)))


def _kind(name, text):
    if name.startswith(".claude/rules/"):
        return "path rule" if _has_paths(text) else "rule"
    return "claude.md"


def _read(path):
    # bytes, so that the line ends stay as they are
    return path.read_bytes().decode("utf-8", errors="replace")


def _is_junction(p):
    # a Windows junction is not a symlink, and one pointing up would loop
    return getattr(p, "is_junction", lambda: False)()


def _subfolders_claude_md(root):
    """CLAUDE.md of each subfolder, skipping hidden folders and node_modules."""
    found, stack = [], [root]
    while stack:
        here = stack.pop()
        for p in sorted(here.iterdir()):
            if p.is_dir() and not p.is_symlink() and not _is_junction(p):
                if not p.name.startswith(".") and p.name != "node_modules":
                    stack.append(p)
            elif p.name in ("CLAUDE.md", "CLAUDE.local.md") and here != root:
                found.append(p)
    return found


def _imports(text):
    text = CODE_SPAN.sub("", CODE_BLOCK.sub("", text))
    return [m.group(1) for m in IMPORT.finditer(text)]


def scan(root, bytes_per_token=DEFAULT_BYTES_PER_TOKEN):
    """Every instruction file Claude Code loads from the repository, with imports; and imports outside it."""
    root = Path(root).resolve()
    files, outside = {}, []

    def add(path, start, imported_by=""):
        name = path.relative_to(root).as_posix()
        if name in files:   # start-up files come first: a file is never moved to start-up later
            return None
        text = _read(path)
        body = render(text, start)
        n = len(body.encode("utf-8"))
        files[name] = File(_kind(name, text), name, n, round(n / bytes_per_token), start, imported_by)
        return text

    def follow(path, text, start, depth):
        if depth > MAX_IMPORT_DEPTH:
            return
        for target in _imports(render(text)):
            if target.startswith("~"):
                outside.append(target)
                continue
            p = (path.parent / target).resolve()
            if not p.is_file():
                continue
            if not p.is_relative_to(root):
                outside.append(target)
                continue
            sub = add(p, start, path.relative_to(root).as_posix())
            if sub is not None:
                follow(p, sub, start, depth + 1)

    def inside(path):
        # a link to a file outside the repository is listed, never read
        if path.resolve().is_relative_to(root):
            return True
        outside.append(path.relative_to(root).as_posix())
        return False

    found = [(root / n, True) for n in START_FILES if (root / n).is_file() and inside(root / n)]
    rules = root / ".claude" / "rules"
    if rules.is_dir():
        found += [(p, not _has_paths(_read(p))) for p in sorted(rules.rglob("*.md")) if p.is_file() and inside(p)]
    found += [(p, False) for p in _subfolders_claude_md(root) if inside(p)]
    for start in (True, False):   # start-up files first: what they import loads at start-up
        for path, is_start in found:
            if is_start == start:
                text = add(path, start)
                if text is not None:
                    follow(path, text, start, 1)
    return list(files.values()), outside


def _glob(pattern):
    """A glob on the relative path: * and ? stay inside one folder, **/ is any number of folders.

    Every other character, [ and ] included, is itself.
    """
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def _positive(value, what, budget_file, number=int):
    ok = isinstance(value, (int, float) if number is float else int) and not isinstance(value, bool)
    if not ok or not math.isfinite(value) or value <= 0:
        raise BudgetError(f"{budget_file}: {what} must be a positive "
                          f"{'number' if number is float else 'integer'}, not {value!r}")
    return value


def load(budget_file):
    """The budget file as (bytes_per_token or None, start limit or None, {pattern: limit})."""
    if Path(budget_file).is_dir():
        raise BudgetError(f"{budget_file}: a folder, not a budget file")
    try:
        with open(budget_file, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        raise BudgetError(f"budget file not found: {budget_file}") from None
    except UnicodeDecodeError:
        raise BudgetError(f"{budget_file}: not UTF-8 text") from None
    except tomllib.TOMLDecodeError as e:
        raise BudgetError(f"{budget_file}: not valid TOML: {e}") from None
    unknown = sorted(set(data) - KEYS)
    if unknown:
        raise BudgetError(f"{budget_file}: unknown key(s) {', '.join(unknown)}; "
                          f"the keys are {', '.join(sorted(KEYS))}")
    ratio = data.get("bytes_per_token")
    if ratio is not None:
        _positive(ratio, "bytes_per_token", budget_file, float)
    start = data.get("startup")
    if start is not None:
        _positive(start, "startup", budget_file)
    limits = data.get("limits", {})
    if not isinstance(limits, dict):
        raise BudgetError(f"{budget_file}: [limits] must be a table of \"pattern\" = tokens")
    for pattern, limit in limits.items():
        if isinstance(limit, dict):
            while isinstance(limit, dict) and limit:   # CLAUDE.md = 10 reads as {"CLAUDE": {"md": 10}}
                key, limit = next(iter(limit.items()))
                pattern += "." + key
            raise BudgetError(f"{budget_file}: quote the pattern \"{pattern}\" (a dot outside quotes "
                              f"makes a TOML table)")
        _positive(limit, f"the limit for \"{pattern}\"", budget_file)
    if start is None and not limits:
        raise BudgetError(f"{budget_file}: no limit declared (startup or [limits])")
    return ratio, start, limits


def check_budget(root, budget_file):
    """Measure the repository at `root` and hold it to the limits in `budget_file` (TOML)."""
    ratio, start, limits = load(budget_file)
    files, outside = scan(root, ratio or DEFAULT_BYTES_PER_TOKEN)
    b = Budget(str(Path(root).resolve()), str(budget_file), ratio or DEFAULT_BYTES_PER_TOKEN, ratio is None,
               sorted(files, key=lambda f: (not f.start, f.name)), start_limit=start, outside=outside)
    for pattern, limit in limits.items():
        rx = _glob(pattern)
        hits = [f for f in b.files if rx.fullmatch(f.name)]
        if not hits:
            raise BudgetError(f"{budget_file}: \"{pattern}\" matches no instruction file "
                              f"(a typo would leave a file without its limit)")
        for f in hits:
            f.limit = limit if f.limit is None else min(f.limit, limit)
            if f.tokens > limit:
                b.over.append(Over(f.name, f.kind, f.tokens, limit, pattern))
    b.start_tokens = sum(f.tokens for f in b.files if f.start)
    if start is not None and b.start_tokens > start:
        b.over.append(Over("start-up total", "", b.start_tokens, start, ""))
    return b
