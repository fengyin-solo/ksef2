"""Lazy compatibility imports for applications written before the 1.0 rename.

Aliases reuse the canonical module, including its classes and resource paths.
They remain supported throughout 1.x and may be removed no earlier than 2.0.
"""

import sys
import warnings
from collections.abc import Sequence
from importlib import import_module
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from importlib.util import find_spec
from types import ModuleType
from typing import override


_LEGACY_ROOTS = {
    "core": ("_core", "ksef2, ksef2.xades or ksef2.raw"),
    "domain": ("_domain", "ksef2.models or ksef2.fa3"),
    "infra": ("_infra", "ksef2.raw, ksef2.raw.mappers or ksef2.renderers"),
    "endpoints": ("_endpoints", "ksef2.raw"),
    "services": ("_services", "ksef2.clients, ksef2.fa3 or ksef2.renderers"),
    "config": ("_config", "ksef2"),
    "logging": ("_logging", "standard logging or structlog configuration"),
}


class _LegacyLoader(Loader):
    def __init__(self, target: str, replacement: str) -> None:
        self.target = target
        self.replacement = replacement

    @override
    def create_module(self, spec: ModuleSpec) -> ModuleType | None:
        return None

    @override
    def exec_module(self, module: ModuleType) -> None:
        warnings.warn(
            f"`{module.__name__}` is deprecated and will be removed no earlier "
            f"than ksef2 2.0.0; use `{self.replacement}` instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        sys.modules[module.__name__] = import_module(self.target)


class LegacyImportFinder(MetaPathFinder):
    """Resolve only the packages renamed in 1.0, without loading them eagerly."""

    @override
    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        parts = fullname.split(".")
        if len(parts) < 2 or parts[0] != "ksef2":
            return None
        if parts[1] == "clients" and len(parts) > 2:
            canonical = "ksef2._clients." + ".".join(parts[2:])
            replacement = "ksef2.clients"
        elif parts[1] in _LEGACY_ROOTS:
            root, replacement = _LEGACY_ROOTS[parts[1]]
            canonical = ".".join(("ksef2", root, *parts[2:]))
        else:
            return None
        if fullname == "ksef2.core.exceptions":
            replacement = "ksef2"
        elif fullname == "ksef2.core.xades":
            replacement = "ksef2.xades"
        elif fullname.startswith("ksef2.domain.models.fa3"):
            replacement = "ksef2.fa3"
        elif fullname.startswith("ksef2.domain.models"):
            replacement = "ksef2.models"
        elif fullname.startswith("ksef2.infra.mappers"):
            replacement = "ksef2.raw.mappers"
        elif fullname.startswith("ksef2.infra.schema.api.spec"):
            replacement = "ksef2.raw.spec"
        elif fullname.startswith("ksef2.infra.schema.api.supp"):
            replacement = "ksef2.raw.supp"
        elif fullname.startswith("ksef2.infra.schema.fa3"):
            replacement = "ksef2.fa3 for invoice construction; retain this alias for generated XSD classes"
        elif fullname.startswith("ksef2.services.builders"):
            replacement = "ksef2.fa3"
        elif fullname.startswith("ksef2.services.renderers"):
            replacement = "ksef2.renderers"
        canonical_spec = find_spec(canonical)
        if canonical_spec is None:
            return None
        return ModuleSpec(
            fullname,
            _LegacyLoader(canonical, replacement),
            is_package=canonical_spec.submodule_search_locations is not None,
        )
