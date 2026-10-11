#!/usr/bin/env bash
# Builds the sdist and the wheel in dist/ and runs what pip installs, in a
# venv and outside the checkout (inside it, the import would pick up the
# local copy). Runs in testes.yml on every push (job "pacote") and in
# pypi.yml before publishing.
set -euo pipefail
python -m pip install --quiet "build==1.6.1"
python -m build
venv="$RUNNER_TEMP/instalado"
python -m venv "$venv"
"$venv/bin/pip" install --quiet dist/*.whl
cd "$RUNNER_TEMP"
# the version pip installed is __version__ (the CLI answers --version)
v=$("$venv/bin/python" -I -c 'import claude_context_cost as p; print(p.__version__)')
"$venv/bin/python" -I -m claude_context_cost --version | grep -F "$v"
# Values from the README, through what pip installed: the command with the
# synthetic example (package data: it is in the wheel only if listed in
# [tool.setuptools.package-data]), and the same example from Python.
"$venv/bin/claude-context-cost" --example | grep -F "7 responses, 1 compaction, 159,160 input tokens"
"$venv/bin/claude-context-cost" --example | grep -E "^ +10,400 +6\.5% +3,200 +4 +2,000 +-38% .*tool: Read$"
"$venv/bin/python" -I -c '
from claude_context_cost import analyze, example_path
report = analyze(example_path())
read = report.sources[("tool", "Read")]
assert (report.total, read.entered, read.responses, read.cost) == (159160, 3200, 4, 10400), report.total
print("installed package: README example OK")
'
