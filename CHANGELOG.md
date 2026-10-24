# Changelog

The version follows `claude_context_cost.__version__`; each one has a `vX.Y.Z` tag on
the commit that released it.

## 1.7.0 — 2026-10-23

- A folder sum counts each response once: a resumed or forked session
  repeats the responses it came from in its own file, and those were counted
  twice. Its line says how many were already counted; `--json` adds
  `"repeated"`.
- A response with no `message.id` counts: its request id, its line's `uuid`
  or its line number takes the id's place. Before, only the first of them
  counted.
- A file in a format this version does not know (no `type`, or assistant
  lines with no `usage.input_tokens`) prints a warning, instead of counting
  zero in silence. A field of the wrong type is skipped, not a traceback.
- `--budget` lists a rule or `CLAUDE.md` that is a link to a file outside
  the repository, and does not read it.
- `--versions` runs git with `core.fsmonitor` off, and looks up only
  absolute local paths: a relative path read another repository from the
  current folder, and a UNC path (`//host/share`) reached another machine.
  README and SECURITY say to read only your own transcripts with it.
- Tests for a cut last line, an empty file, bytes that are not UTF-8, `git`
  missing from the `PATH` and a repository with no commit.
- A folder of many projects is summed faster, with the same output.
- The demo page source (`vitrine/montar.py`, its test and `index.html`) is
  in English.

## 1.6.4 — 2026-10-21

- The demo page build also rejects an empty or non-text title, description
  or language, builds the page before creating the output folder, and keeps
  CRLF line endings in the HTML.
- The Pages workflow jobs stop after 10 minutes.
- No change in the library.

## 1.6.3 — 2026-10-11

- The demo page is built with its language (English), title and description
  in the HTML itself, so screen readers and search engines get them before
  any script runs. No change in the library.

## 1.6.2 — 2026-10-11

- A file with no responses (not a transcript, or the wrong file) prints what
  to give instead and exits with 1, instead of an empty table.
- A folder given as the budget file, or a file that cannot be read, is an
  error message with exit code 2, not a traceback.
- `--example` with a path and `--budget --quiet --json` are errors instead of
  silently ignoring an option.
- Clearer output: the legend says what `unattributed` is; `--versions` says
  `tokens` is of one load; the bytes-per-token line and the `skipped` line
  say what they mean.
- README: a shorter start (what it is, try it in a minute); "as Claude Code
  loads it" instead of "renders"; where a relative budget path starts.
- Issue templates, the pull request template and CONTRIBUTING agree on where
  a missing case goes; `claude-context-cost --version` in the templates.

## 1.6.1 — 2026-10-11

- README: badges for the PyPI version, the Python versions and the license,
  beside the tests badge, so PyPI shows them too.

## 1.6.0 — 2026-10-11

From a first use in another project's git hook:

- `--budget --quiet`: only the verdict and the limits exceeded, for a hook.
- `--budget` names the repository it measured, and says what a session also
  loads that it does not count: your `~/.claude/CLAUDE.md`, memory and any
  `CLAUDE.md` above the repository. The README says which folder is measured
  and where the budget file's path starts.
- The `how` column widens when a source has three ways, so the `source`
  column stays aligned.

## 1.5.1 — 2026-10-11

- Clearer output: the legend explains every column (`share`, `in`, `chars/4`,
  `error`, `how`) and every `today` value of `--versions`; `--steps` says
  "start of the session or after a compaction" instead of "segment start".
- `--help` ends with examples, where the transcripts are and a link to the
  README; error messages say what to give instead.
- The README explains each kind of source and each `how`.
- PyPI links as on GitHub: Homepage is the page, Source the repository.

## 1.5.0 — 2026-10-11

- `--versions`: for one transcript, which git commit of each `CLAUDE.md`,
  rule and memory file the session loaded (the newest commit before the load
  with exactly that text, or the first one after it, marked `(later)`), and
  how today's file differs. Git is only read. `--json` adds `versions`;
  `loaded_versions` and `Version` in the API.
- On the author's machine: of 2,863 distinct texts loaded, only 290 are the
  same on disk today; 811 were in git and the commit was found for 798 (the
  other 13 were never committed); none of the 212 texts equal today and in
  `HEAD` was missed (`tests/test_corpus.py`).
- Budget fixes: `nan` and `inf` are not a ratio or a limit; a budget file
  that is missing or not UTF-8 exits with 2 and a message, not a traceback;
  every message names the budget file; an unquoted dotted pattern
  (`CLAUDE.md = 1`) is named whole; an import inside a `~~~` block is not
  followed; a Windows junction is not followed; `--budget ""` is an error.
- Clearer output: "2 limits exceeded" instead of "passed", and a space after
  the `loaded` column.
- The README's links, section links and image are absolute, so they work on
  PyPI too, and it shows the CI badge; the PyPI page links the demo and this
  changelog, and its description and keywords are the GitHub About and topics.
- `SECURITY.md`: how to report a vulnerability privately, and what the tool
  does not do (no network, no writes). The CI's actions are pinned by commit.
- Mutation: 51 mutants (24 in the budget, 10 in `--versions`); the tests
  catch all 51.

## 1.4.0 — 2026-10-11

- Context budget for CI: `claude-context-cost --budget context-budget.toml
  [repository]` measures every `CLAUDE.md`, rule and `@import` Claude Code
  loads from a repository, as Claude Code renders them, and exits with 1 when
  a declared limit is passed (per file by glob pattern, and for the start-up
  total), with 2 when the budget file is invalid. `--json` works with it.
- `check_budget`, `Budget` and `BudgetError` in the API.
- On the author's machine the files found are the ones Claude Code loaded in
  257 of 257 start-ups and 252 of 252 on-demand loads, with the same bytes in
  268 of 268 files (`tests/test_corpus.py`).
- Mutation: 36 mutants, 19 of them in the budget; the tests catch all 36.
- CI checks the budget through the installed package too.

## 1.3.1 — 2026-10-11

- Published on PyPI: `pip install claude-context-cost`. Each Release publishes
  through trusted publishing (OIDC), with no stored token, after the tests and
  a check of the installed package.
- CI builds the package on every push, installs the wheel outside the checkout
  and runs the README example through the command and the API.
- No change in the library.

## 1.3.0 — 2026-10-11

- A folder is summed: a project's folder with its sessions and their subagents,
  or `~/.claude/projects` with every project. The costliest sources come first,
  each with the number of transcripts it was in; then one line per session
  (with its subagents) or per project. `--all` works on a folder.
- Tools and the user's own `~/.claude/...` files add up across projects; a
  project's `CLAUDE.md` and rules keep their project, since the same name in two
  projects is two files.
- `summarize(folder)` in the API, with `Summary` and `Total`.
- `--json` on a folder keeps `folder`, `version` and `transcripts` (now only the
  sessions, each with its `project`) and adds `responses`, `total`, `projects`,
  `subagents` and `sources`.
- On the author's machine: 27 projects, 459 transcripts, every one in the sum.

## 1.2.0 — 2026-10-10

- A subagent's own transcript (`<session-id>/subagents/agent-<id>.jsonl`) is read; it
  showed 0 responses, because all its lines are marked as a sidechain. Inside a
  session's transcript, sidechain lines are still skipped.
- The corpus test also checks subagent transcripts: 382 on the author's machine,
  0 where the sources differ from the `usage`.
- README: the characters / 4 error measured in one English-language session (−40%).

## 1.1.0 — 2026-10-10

- Fix: two instruction files with the same content, or one inside another, were
  each counted in full; now each byte of the rendered text counts once. It did not
  happen in the 1,233 instruction and skill attachments of the author's 74
  transcripts, so their numbers do not change.
- `--json` on a folder prints one object per transcript (it printed text);
  `--steps` and `--all` on a folder now stop with an error instead of being ignored.
- `--json` gains `bad_lines`, the lines skipped because they are not JSON.
- The showcase build and its tests follow the updated template; the Pages
  workflow builds read-only and deploys in a separate job; Dependabot keeps the
  workflow actions current.

## 1.0.0 — 2026-10-10

- Stable API: the names in `claude_context_cost.__all__` (`analyze`, `read`,
  `attribute`, `Report`, `Source`, `example_path`, `__version__`) and the keys of
  `--json` change incompatibly only in a new major version (see Compatibility in the
  README). The counting is the same as in 0.1.0.
- Package metadata: classifiers for the supported Python versions and status.
- Tests: the README check runs its examples without printing to the test output.

## 0.1.0 — 2026-10-10

- First public release: `claude-context-cost <transcript.jsonl | folder>`.
- Context of every response from the API `usage`, one response per `message.id`.
- Each source's tokens: measured when it entered alone, split by bytes when it
  entered with others, estimated with the transcript's own bytes-per-token ratio
  at the start of a segment; the rest is unattributed, so every response adds up.
- Rules with `paths:` count only from the `nested_memory` that loaded them.
- A characters / 4 column beside each source, with its error.
- `--steps`, `--json`, `--example`.
