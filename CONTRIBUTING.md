# Contributing

Wrong result or a missing case: open an issue with the "Unexpected result"
template. To send code:

- Tests run from the checkout, with nothing to install:

  ```bash
  python -m unittest
  ```

- Standard library only: no dependencies.
- Every counting rule has a case in a synthetic transcript under `tests/`, with the
  expected tokens worked out by hand, and a mutant in `tests/mutate.py` that the
  tests catch (`python tests/mutate.py`).
- Never commit or paste a real transcript: it holds paths, file contents and
  sometimes secrets. Fixtures are synthetic, written for the test.
- Every new case has a test, with the expected result written by hand in
  the test itself.
- Examples and tests use made-up data only: no real data about any person
  or company.
- Code, messages and documentation in English.
- Behavior changes go into [CHANGELOG.md](CHANGELOG.md).
- Your own code only: do not bring code copied from another project, even
  under a free license. What you contribute is released under the project's
  [MIT license](LICENSE).
