"""Keep renamed package trees importable throughout 1.x."""

import sys
import warnings
from importlib import import_module
from pkgutil import walk_packages


def alias_package(legacy: str, canonical: str, replacement: str) -> None:
    """Load a canonical tree once, then reuse its modules under the old names."""
    warnings.warn(
        f"`{legacy}` and its submodules are deprecated; use {replacement} instead. "
        "Removal may happen no earlier than ksef2 2.0.0.",
        DeprecationWarning,
        stacklevel=3,
    )
    package = import_module(canonical)
    modules = [package]
    for entry in walk_packages(package.__path__, canonical + "."):
        modules.append(import_module(entry.name))
    for module in modules:
        sys.modules[legacy + module.__name__[len(canonical) :]] = module
