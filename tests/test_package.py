"""The installed package: every non-.py file it reads goes with it (the package-data), and its metadata."""

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "claude_context_cost"


def _setuptools():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return cfg.get("tool", {}).get("setuptools", {})


class TestPackaging(unittest.TestCase):

    def test_metadata_fits_github_about_and_topics(self):
        # PyPI and GitHub show the same description and keywords: GitHub takes at most
        # 20 topics, each lowercase letters, digits and hyphens, and 350 characters of About
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        keywords = project["keywords"]
        self.assertLessEqual(len(keywords), 20)
        self.assertEqual(len(set(keywords)), len(keywords))
        for k in keywords:
            self.assertRegex(k, r"^[a-z0-9][a-z0-9-]{0,49}$")
        self.assertLessEqual(len(project["description"]), 350)
        for name, url in project["urls"].items():
            self.assertTrue(url.startswith("https://"), name)

    def test_package_files_in_package_data(self):
        # a data file passes in the checkout and silently goes missing after pip install
        data = _setuptools().get("package-data", {})
        patterns = data.get(PACKAGE, []) + data.get("*", [])
        folder = ROOT / PACKAGE
        # Path.glob, like setuptools: with fnmatch, "*.jsonl" also matched a subfolder
        covered = {p for g in patterns for p in folder.glob(g)}
        missing = [p.relative_to(folder).as_posix() for p in sorted(folder.rglob("*"))
                   if p.is_file() and p.suffix not in (".py", ".pyc") and "__pycache__" not in p.parts
                   and p not in covered]
        self.assertEqual(missing, [], "not in [tool.setuptools.package-data]: not installed")

    def test_subpackages_in_packages(self):
        # packages = ["claude_context_cost"] leaves out a subfolder with .py files:
        # the import breaks only after pip install
        packages = _setuptools().get("packages", [])
        if not isinstance(packages, list):
            return  # packages.find picks up subpackages by itself
        folder = ROOT / PACKAGE
        subs = sorted({".".join((PACKAGE,) + p.parent.relative_to(folder).parts)
                       for p in folder.rglob("*.py") if "__pycache__" not in p.parts})
        self.assertEqual([s for s in subs if s not in packages], [],
                         "not in [tool.setuptools] packages: not installed")


if __name__ == "__main__":
    unittest.main()
