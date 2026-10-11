"""Deprecated imports; use the public client, builder and renderer facades."""

from ksef2._legacy_imports import alias_package

alias_package(
    __name__, "ksef2._services", "ksef2.clients, ksef2.fa3 or ksef2.renderers"
)
