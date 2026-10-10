"""The showcase adapter shows the same numbers as the library, for the example and for a file."""
import importlib.util
import sys
import unittest
from pathlib import Path

from claude_context_cost import analyze, example_path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("vitrine_adapter", ROOT / "vitrine" / "vitrine.py")
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)
sys.path.remove(str(ROOT))


class TestShowcase(unittest.TestCase):

    def check(self, res, rep):
        self.assertIn(f"{len(rep.responses)} responses", res["resumo"])
        self.assertIn(f"{rep.total:,} input tokens", res["resumo"])
        rows = {r[0]: r for r in res["tabela"]["linhas"]}
        for s in rep.sources.values():
            row = rows[f"{s.kind}: {s.name}"]
            self.assertEqual(row[2:5], [f"{s.entered:,}", f"{s.responses:,}", f"{s.cost:,}"])

    def test_empty_input_runs_the_example(self):
        self.check(adapter.executar({"transcript": ""}), analyze(example_path()))

    def test_file_text_is_counted_as_the_file(self):
        lines = example_path().read_text(encoding="utf-8").splitlines(keepends=True)[:12]
        res = adapter.executar({"transcript": "".join(lines)})
        self.assertIn("3 responses", res["resumo"])
        self.assertNotIn("159,160", res["resumo"])

    def test_not_a_transcript(self):
        res = adapter.executar({"transcript": "not json\n"})
        self.assertEqual(set(res), {"resumo"})
        self.assertIn("No responses", res["resumo"])


if __name__ == "__main__":
    unittest.main()
