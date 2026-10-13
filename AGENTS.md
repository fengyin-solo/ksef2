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

- Cryptographic rejection tests must use deterministic inputs with known
  invalid padding or block lengths. A random wrong AES-CBC key can produce
  valid PKCS#7 padding and does not guarantee a decryption error.

- The legacy compatibility gate is `just check-legacy-compat`, run by
  `.github/workflows/legacy-compat.yml`. Its consumer application
  (`tests/compat/`), snapshot driver (`scripts/check_legacy_compat.py`),
  allowlist (`tests/compat/legacy_compat_allowlist.toml`) and workflow must not
  be deleted, skipped or loosened without a stated reason in the pull request.
  Every allowlist entry justifies the removal it approves. `BASELINE_VERSIONS`
  gains an entry when a 1.x release is published and never loses one during 1.x.

- Batch upload recovery must be tested through the public API after a local
  storage failure. Resume the same session with its exact original prepared
  payload, including batches prepared internally by convenience submission.
  Reject mismatched payloads before upload and keep keys, payload bytes and
  presigned URLs out of generic repr and serialization.
