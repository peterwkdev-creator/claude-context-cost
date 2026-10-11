"""How much each source costs in the context of a Claude Code session, counted from the usage."""
from pathlib import Path

from .attribute import Report, Source, analyze, attribute
from .transcript import read

__version__ = "1.1.0"
__all__ = ["Report", "Source", "analyze", "attribute", "example_path", "read", "__version__"]


def example_path():
    """A synthetic transcript shipped with the package, for trying the tool without a real one."""
    return Path(__file__).resolve().parent / "example.jsonl"
