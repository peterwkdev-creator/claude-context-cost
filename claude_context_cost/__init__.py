"""How much each source costs in the context of a Claude Code session, counted from the usage."""
from pathlib import Path

from .attribute import Report, Source, analyze, attribute
from .summary import Summary, Total, summarize
from .transcript import read

__version__ = "1.3.0"
__all__ = ["Report", "Source", "analyze", "attribute", "example_path", "read", "Summary", "summarize",
           "Total", "__version__"]


def example_path():
    """A synthetic transcript shipped with the package, for trying the tool without a real one."""
    return Path(__file__).resolve().parent / "example.jsonl"
