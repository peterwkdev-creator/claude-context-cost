# Changelog

The version follows `claude_context_cost.__version__`; each one has a `vX.Y.Z` tag on
the commit that released it.

## 0.1.0 — 2026-10-10

- First public release: `claude-context-cost <transcript.jsonl | folder>`.
- Context of every response from the API `usage`, one response per `message.id`.
- Each source's tokens: measured when it entered alone, split by bytes when it
  entered with others, estimated with the transcript's own bytes-per-token ratio
  at the start of a segment; the rest is unattributed, so every response adds up.
- Rules with `paths:` count only from the `nested_memory` that loaded them.
- A characters / 4 column beside each source, with its error.
- `--steps`, `--json`, `--example`.
