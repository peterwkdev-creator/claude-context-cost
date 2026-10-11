# Changelog

The version follows `claude_context_cost.__version__`; each one has a `vX.Y.Z` tag on
the commit that released it.

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
