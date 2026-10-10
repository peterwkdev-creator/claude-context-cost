"""The Python examples in the README run as they are, each block on its own."""

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


if __name__ == "__main__":
    unittest.main()
