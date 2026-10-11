"""Deprecated imports; see the 1.0 migration guide for schema replacements."""

from ksef2._legacy_imports import alias_package

alias_package(__name__, "ksef2._infra", "ksef2.raw or ksef2.fa3")
