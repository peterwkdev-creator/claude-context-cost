"""How much each source costs in the context of a Claude Code session, counted from the usage."""
from pathlib import Path

from .attribute import Report, Source, analyze, attribute
from .budget import Budget, BudgetError, check_budget
from .summary import Summary, Total, summarize
from .transcript import read
from .versions import Version, loaded_versions

__version__ = "1.6.0"
__all__ = ["Budget", "BudgetError", "Report", "Source", "analyze", "attribute", "check_budget", "example_path",
           "loaded_versions", "read", "Summary", "summarize", "Total", "Version", "__version__"]


def example_path():
    """A synthetic transcript shipped with the package, for trying the tool without a real one."""
    return Path(__file__).resolve().parent / "example.jsonl"
