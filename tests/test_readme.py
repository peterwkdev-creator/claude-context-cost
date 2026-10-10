"""The README: the Python examples run as they are, and the install points at the current version."""

import re
import unittest
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


class TestExemplosDoReadme(unittest.TestCase):

    def test_blocos_python_rodam(self):
        blocos = re.findall(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), re.S)
        self.assertGreaterEqual(len(blocos), 1)
        for i, bloco in enumerate(blocos, 1):
            # expected output and errors shown go in comments, never loose
            with self.subTest(bloco=i):
                exec(compile(bloco, f"README, bloco {i}", "exec"), {})

    def test_install_from_the_current_version_tag(self):
        # a release must not ship with the README still pointing at the previous tag
        from claude_context_cost import __version__
        tags = re.findall(r"claude-context-cost@v([\d.]+)", README.read_text(encoding="utf-8"))
        self.assertEqual(tags, [__version__])


if __name__ == "__main__":
    unittest.main()
