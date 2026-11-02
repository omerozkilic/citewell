"""Citewell: citation-grounded document memory for AI assistants."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("citewell")
except PackageNotFoundError:  # pragma: no cover - running from a source tree without install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
