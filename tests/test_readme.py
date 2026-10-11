"""The README: the Python examples run as they are, and the install points at the current version."""

import contextlib
import io
import re
import unittest
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


class TestReadmeExamples(unittest.TestCase):

    def test_python_blocks_run(self):
        blocks = re.findall(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), re.S)
        self.assertGreaterEqual(len(blocks), 1)
        for i, block in enumerate(blocks, 1):
            # expected output and errors shown go in comments, never loose
            with self.subTest(block=i), contextlib.redirect_stdout(io.StringIO()):
                exec(compile(block, f"README, block {i}", "exec"), {})

    def test_install_from_the_current_version_tag(self):
        # a release must not ship with the README still pointing at the previous tag
        from claude_context_cost import __version__
        # the tag may appear more than once (pip and uv); a sentence's final period stays out
        tags = re.findall(r"claude-context-cost@v(\d+(?:\.\d+)*)", README.read_text(encoding="utf-8"))
        self.assertTrue(tags, "the README does not install from the tag")
        self.assertEqual(set(tags), {__version__})
        # the CI example pins the version from PyPI
        pins = re.findall(r"claude-context-cost==(\d+(?:\.\d+)*)", README.read_text(encoding="utf-8"))
        self.assertTrue(pins, "the README CI example does not pin the version")
        self.assertEqual(set(pins), {__version__})


if __name__ == "__main__":
    unittest.main()
