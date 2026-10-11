# claude-context-cost

How much each source (your `CLAUDE.md`, rules, skills, memory, tool results)
costs in the context of a Claude Code session, counted from the API `usage`
recorded in its transcript, not estimated from characters.

![The page counts the synthetic example, then a transcript file](docs/demo.gif)

**[Try it in the browser](https://peterwkdev-creator.github.io/claude-context-cost/)**:
choose one of your transcripts, or run the synthetic example. The library runs
in the page (Pyodide); your file is never uploaded.

In CI, [`--budget`](#context-budget-in-ci) fails a pull request that makes a
`CLAUDE.md`, a rule or an import pass the limit you declared.

The usual estimate, characters / 4, **undercounts by 40 to 45%**: −45% over
5,365 steps of the author's sessions, mostly in Portuguese, and −40% in an
English-language session (2026-10-10). Here every response adds up to its
`usage` exactly, in all 457 transcripts tested.

> Reads only the transcripts under `~/.claude/projects` on your machine.
> Nothing is sent anywhere. The numbers are tokens, not dollars.

## Install

```bash
pip install claude-context-cost
```

Python 3.11 or newer, no dependencies. To install a tagged version straight
from GitHub instead:

```bash
pip install "git+https://github.com/peterwkdev-creator/claude-context-cost@v1.4.0"
```

## Usage

```bash
claude-context-cost --example
```

```bash
claude-context-cost ~/.claude/projects/<project-folder>/<session-id>.jsonl
```

The newest `.jsonl` in a project's folder is its latest session (on Windows,
`~` is `%USERPROFILE%`). A subagent has its own transcript,
`<session-id>/subagents/agent-<id>.jsonl`.

Pass a project's folder instead of a file to sum its sessions and their
subagents: the costliest sources first, then one line per session. Pass
`~/.claude/projects` itself to sum every project. Tools and your own
`~/.claude/...` files add up across projects; a project's `CLAUDE.md` and
rules stay apart, marked with the project.

`--steps` shows what entered before each response, `--all` lists every
source, `--json` is for scripts (for a folder too). On the synthetic example
shipped with the package:

```text
        cost  share   entered    in    chars/4  error  how                  source
     128,240  80.6%    36,640     7          -      -  -                    unattributed: system prompt, tools, overhead
      10,400   6.5%     3,200     4      2,000   -38%  measured, split      tool: Read
       5,600   3.5%     1,600     7      1,000   -38%  estimated            claude.md: CLAUDE.md
       1,600   1.0%       800     4        500   -38%  split, estimated     path rule: .claude/rules/python.md
```

- **cost**: tokens × the responses the source stayed in context, until a
  compaction removed it. This is what you pay for over the session.
- **entered**: the tokens it brought in; **in**: the responses it stayed for.
- **chars/4** and **error**: what the usual estimate would say, beside it.

From Python:

```python
from claude_context_cost import analyze, example_path

report = analyze(example_path())  # or the path of any .jsonl transcript
print(report.total)  # 159160: input tokens summed over the 7 responses
read = report.sources[("tool", "Read")]
print(read.entered, read.responses, read.cost)  # 3200 4 10400
print(read.estimate_div4)  # 2000.0: characters / 4 for the same text
```

`summarize(folder)` returns the same sum as a folder on the command line:
`.sources` maps `(kind, name, project)` to the totals, with `project` set only
for a project's own files.

## Context budget in CI

There is no transcript in CI, so `--budget` measures the repository itself:
every `CLAUDE.md`, rule and `@import` Claude Code would load from it, as
Claude Code renders them (frontmatter and HTML comment blocks out), held to the
limits you declare. It exits with 1 when a limit is passed, so a pull request
that bloats the context fails.

```toml
# context-budget.toml, at the root of the repository
startup = 3000                  # everything loaded when a session starts

[limits]                        # per file; a file is held to every pattern that matches it
"CLAUDE.md" = 2000
".claude/rules/*.md" = 1500     # * stays in one folder, **/ is any number of folders
"**/CLAUDE.md" = 2000
```

```bash
claude-context-cost --budget context-budget.toml
```

```text
context budget: 5 instruction files, 2.25 bytes per token (default)

   tokens     limit  loaded    file
      622     1,500  start-up  rule: .claude/rules/style.md
    1,705     2,000  start-up  claude.md: CLAUDE.md
    1,066         -  start-up  claude.md: docs/architecture.md (imported by CLAUDE.md)
    1,813     1,500  on demand path rule: .claude/rules/api.md  OVER
      427     2,000  on demand claude.md: web/CLAUDE.md
    3,393     3,000  start-up total  OVER

over budget: 2 limits passed
  path rule: .claude/rules/api.md: 1,813 tokens > 1,500 (limit ".claude/rules/*.md")
  start-up total: 3,393 tokens > 3,000 (limit startup)
```

- **Start-up**: `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, rules in
  `.claude/rules/` without `paths:`, and what they import. **On demand**:
  rules with `paths:` and the `CLAUDE.md` of a subfolder, with their imports.
  Hidden folders and `node_modules` are skipped. Your own
  `~/.claude/CLAUDE.md` and any `CLAUDE.md` above the repository are not in
  it, so they are not counted.
- **Tokens are bytes / a ratio**: 2.25 bytes per token by default, or
  `bytes_per_token = ...` in the budget. Running the tool on one of your
  transcripts prints the ratio measured in it.
- **An invalid budget exits with 2**, never passes: a typo in a key, a limit
  that is not a positive integer, or a pattern that matches no file (it would
  leave a file without its limit). An import that resolves outside the
  repository is listed, not counted.

In a GitHub Actions workflow:

```yaml
- uses: actions/setup-python@v7
  with:
    python-version: "3.x"
- run: pip install claude-context-cost==1.4.0
- run: claude-context-cost --budget context-budget.toml
```

`--json` gives the same result for scripts; from Python,
`check_budget(repository, budget_file)` returns it, and raises `BudgetError`
for an invalid budget.

## Why

[claude-devtools](https://github.com/matt1398/claude-devtools) already shows
the context by source. Read in its code at commit `1486f20` (the latest on
2026-10-10):

- Each source's tokens are characters / 4 (`src/main/utils/tokenizer.ts`);
  only the turn total comes from the `usage`.
- Rules in `.claude/rules/` are listed as global sources without reading
  their `paths:`, so a rule that never loaded still counts. Issue
  [#224](https://github.com/matt1398/claude-devtools/issues/224), open since
  2026-07-17.
- `CLAUDE.md` and rules are read from disk today, not as they were during the
  session.

This tool fixes the first two from the transcript alone.

## What it counts

- **One response per `message.id`.** A response is written over several
  lines with the same `usage`; it counts once.
- **Context = `input_tokens` + `cache_read_input_tokens` +
  `cache_creation_input_tokens`.**
- **What entered** between two responses is the context growth minus the
  previous response's output. When a single source entered, its tokens are
  **measured**. When several did, the growth is **split** by their size.
- **At the start of the session and after each compaction** the context
  jumps at once: each source is **estimated** with the bytes-per-token ratio
  measured in the same transcript (median of its text-only steps; 2.25 when
  it has fewer than 3), and the rest is **unattributed** (system prompt,
  tool definitions). So every response adds up to its `usage`.
- **Rules with `paths:`** count only from the response where Claude Code
  loaded them (`nested_memory`), never before.
- **Only what Claude Code rendered** into the context counts; bookkeeping
  lines in the transcript do not.
- **A compaction** removes everything; messages it keeps count as "kept by
  compaction", not as new responses.

## How it is tested

- A synthetic transcript with known values (`tests/fixtures/build_example.py`)
  where every source's tokens are worked out by hand: each one comes out
  exact, every response adds up to its `usage`, a `paths:` rule that never
  loaded counts 0, a response written over several lines counts once.
- The budget is tested on synthetic repositories (`tests/test_budget.py`):
  what loads at start-up and on demand, imports, rendering, limits, invalid
  budgets.
- `python tests/mutate.py` breaks each of those rules in a copy of the code
  (36 mutants, 19 of them in the budget); the tests catch all 36.
- On the author's machine (2026-10-10): 75 session transcripts and 382
  subagent transcripts, 91,347 responses, 0 where the sources differ from the
  `usage`, 0 where the response count differs from an independent count, and
  the sum over every project takes every transcript. For the budget
  (2026-10-11): the files found are the ones Claude Code loaded in 257 of
  257 start-ups and 252 of 252 on-demand loads, with the same bytes in 268
  of 268 files (loads whose files changed afterwards are left out). The
  ratio was measured in 50 of the 73 sessions with responses, median 2.22
  bytes per token. Run it on yours with
  `CLAUDE_CONTEXT_COST_CORPUS=1 python -m unittest tests.test_corpus -v`
  (it prints only counts).

## Limits

- **Split and estimated tokens are not measured.** The `how` column says
  which is which. Many steps bring a tool result together with a small
  reminder, so splitting is common.
- **Output includes thinking.** Thinking may leave the context later, so
  the previous output can be overcounted; the remainder then shows as
  negative unattributed tokens (191 of 91,347 responses).
- **A session's total does not include its subagents**; the sum of its
  project's folder does.
- **English was measured in one session** (2026-10-10): 8 file reads, a
  license, release notes, two READMEs, three Python modules and a git log;
  median −40%, from −29% to −47%. The other numbers come from one person's
  sessions, mostly in Portuguese.
- **The budget counts bytes, not the tokenizer**: its tokens are as good as
  the ratio. And it counts every `@import` that resolves to a file: on the
  author's machine Claude Code loaded 32 of 35 such imports, with no rule
  found for the other 3, so the budget may count more than loads, never less.
- The transcript format is not documented and changes between versions.

## Compatibility

Transcripts of Claude Code 2.1 (the synthetic fixture follows 2.1.293).
Python 3.11 to 3.14, tested on Linux and Windows.

Versions follow [Semantic Versioning](https://semver.org/): the names in
`claude_context_cost.__all__` and the keys of `--json` change incompatibly only
in a new major version. The transcript format is Claude Code's and changes
without notice; when it does, a fix keeps the API and ships as a minor or
patch version.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Never paste a real transcript in an
issue or pull request: it holds paths, file contents and sometimes secrets.

## License

[MIT](LICENSE)
