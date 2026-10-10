"""The installed package: every non-.py file it reads goes with it (the package-data)."""

import fnmatch
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "claude_context_cost"


class TestPackaging(unittest.TestCase):

    def test_package_files_in_package_data(self):
        # a data file passes in the checkout and silently goes missing after pip install
        cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        data = cfg.get("tool", {}).get("setuptools", {}).get("package-data", {})
        patterns = data.get(PACKAGE, []) + data.get("*", [])
        folder = ROOT / PACKAGE
        missing = [p.relative_to(folder).as_posix() for p in sorted(folder.rglob("*"))
                   if p.is_file() and p.suffix not in (".py", ".pyc") and "__pycache__" not in p.parts
                   and not any(fnmatch.fnmatch(p.relative_to(folder).as_posix(), g) for g in patterns)]
        self.assertEqual(missing, [], "not in [tool.setuptools.package-data]: not installed")


if __name__ == "__main__":
    unittest.main()
