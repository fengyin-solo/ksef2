# Project Instructions

- Do not add `from __future__ import annotations` or other `__future__` imports. This project does not use future imports.

- Legacy `core`, `domain`, `infra` and `services` imports and deprecated SDK
  method names must keep working throughout 1.x. Deprecation messages must
  name a replacement and permit removal no earlier than 2.0.0, without promising removal in that
  release. Keep English/Polish migration guidance and release notes consistent
  with this boundary. On first legacy import, alias the whole canonical package
  tree and warn once per package family. Preserve module and class identity and
  resource access. Keep optional third-party dependencies lazy. Modern imports
  must not activate compatibility aliases.

- Sync/async parity discovery must inspect canonical implementation modules
  and check for missing counterparts in both directions. Compatibility files
  are outside that discovery. Check parity with runtime type checking both
  enabled and disabled.
