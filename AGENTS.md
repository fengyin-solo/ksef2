# Project Instructions

- Do not add `from __future__ import annotations` or other `__future__` imports. This project does not use future imports.

- Legacy imports renamed for 1.0 and deprecated SDK method names must keep
  working throughout 1.x. Deprecation messages must name a replacement and
  permit removal no earlier than 2.0.0, without promising removal in that
  release. Keep English/Polish migration guidance and release notes consistent
  with this boundary. Compatibility files must reuse canonical classes and
  leaf modules, without eagerly loading optional dependencies. Package shims retain their own
  namespace so Python can discover nested compatibility files through normal
  imports; forward package attributes to the canonical implementation.

- Sync/async parity discovery must inspect canonical implementation modules
  and check for missing counterparts in both directions. Compatibility files
  are outside that discovery.
