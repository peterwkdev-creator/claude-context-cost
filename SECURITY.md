# Security

## How to report

Do not open a public issue for a security problem: use GitHub's private
report, at [Security → Report a vulnerability](https://github.com/peterwkdev-creator/claude-context-cost/security/advisories/new).
Include the version, the steps to reproduce and the impact.

## What to expect

- First reply within 14 days.
- The fix ships in the latest published version; older versions are not
  patched.
- Credit in the [CHANGELOG.md](CHANGELOG.md) and in the advisory, if you want it.

## What is not a security problem

A wrong result (a value, a rule, a missing case) is a regular issue, through
the "Unexpected result" template.

The tool only reads: the transcripts you pass it, and with `--budget` or
`--versions` the files of a repository and its git history (`git log` and
`git cat-file`, never a command that writes). It has no dependencies, makes no
network request and writes no file. The page in the browser runs the same
library in Pyodide; the file you choose is never uploaded.
