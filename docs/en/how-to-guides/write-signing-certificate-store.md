---
title: Write a signing-certificate store
description: Implement the signing-certificate store protocol over a keychain, secret manager, database, or other backend that holds your own certificate and private key.
---

A signing-certificate store keeps your own XAdES signing certificate together
with its private key, and hands the pair back as one validated record. The SDK
ships in-memory adapters; write your own when the pair has to live somewhere
durable.

This is not `CertificateStoreProtocol`, the cache of KSeF public encryption
certificates a root client holds as `certificate_store=`. The two are unrelated:
this store holds a private key, that one holds only public material. See
[Certificates](../concepts/certificates.md) for the difference.

## When to write one

Write an adapter when one of these is where your key actually lives:

- an OS keychain or keyring entry,
- a secret manager such as Vault or a cloud secrets store,
- a database row, ideally with the key encrypted by a key the row cannot read,
- a KMS-encrypted blob, as long as the KMS key is one you can export into the
  process.

Keys a device refuses to export are out of scope for this protocol. An HSM or
KMS key that never leaves the hardware cannot be handed over as a
`SigningCertificate`, because the record is a certificate and a private key the
process holds. Sign with those keys outside the SDK.

## The four methods

Implement `SigningCertificateStoreProtocol`, or
`AsyncSigningCertificateStoreProtocol` for async clients, and pass the object to
`client.authentication.with_stored_certificate()`. The adapter satisfies the
protocol structurally; do not inherit from it.

| Method | Contract |
| --- | --- |
| `save(certificate)` | Write the pair atomically, so a record is either complete or absent. Saving a record whose metadata equals the stored one changes nothing and returns the stored metadata. A record with different metadata under a stored reference is a conflict. |
| `load(reference)` | Return exactly the record stored under `reference`. Never pick a "latest" or "best" certificate, and return an expired one as stored. |
| `list(*, environment, certificate_type=None)` | Return metadata for every record of one environment, ordered by `valid_from` and then by `fingerprint_sha256`. Reading metadata never unlocks a private key and never contacts KSeF; expired records are included. |
| `delete(reference)` | Remove the local record and return whether one was there. The certificate stays valid in KSeF until it is revoked there. |

## Rebuild the record on load

Do not try to store a `SigningCertificate` object. Store whatever you need to
rebuild one — the key, the certificate, and the metadata you wrote — and rebuild
it on every `load()`:

1. Read and decrypt the stored key material.
2. Build `XAdESCredentials(certificate, private_key)`. This checks the private
   key belongs to the certificate, so a record that was saved with the wrong
   pairing fails at load instead of at authentication.
3. Build `SigningCertificate(credentials, environment=..., certificate_type=...,
   ksef_serial_number=...)`. The record derives its own reference, X.509 serial,
   public-key fingerprint and validity window from the certificate.
4. Compare the rebuilt record's `info` with the metadata you stored. If they
   differ, the backend returned someone else's material: raise
   `KSeFCertificateStoreMaterialError` for this `reference` instead of handing
   the record back.

## Which error to raise

Raise the errors the protocol documents, so callers can recover without reading
your adapter:

| Error | Raise it when |
| --- | --- |
| `KSeFCertificateStoreNotFoundError` | Nothing is stored under this reference. |
| `KSeFCertificateStoreConflictError` | `save()` found a different record, one whose metadata differs, under this reference. |
| `KSeFCertificateStoreAccessError` | The backend rejected the caller's credentials or permissions. |
| `KSeFCertificateStoreUnavailableError` | The backend could not be reached, or could not take the record. |
| `KSeFCertificateStoreMaterialError` | The stored record is corrupt, uses a format you cannot read, cannot be decrypted, or does not match its reference. |

Pass `operation=` the method that failed and `reference=` the record it was about
so the message names both. Set `outcome_ambiguous=True` when a write may have
taken effect and the caller cannot tell from the failure, which is the normal
case for a write whose response was lost: the caller then reads the record back
before repeating the write.

Keep the failure itself free of secrets. A message must not contain key
material, a password, a backend response body, or a connection URL that carries
credentials. When the backend error could contain any of those, raise your own
error with `from None` rather than chaining the original exception.

Do not turn a programming error into `KSeFCertificateStoreUnavailableError`. A
wrong argument, a broken query built from your own schema, or a missing method
should surface as the ordinary Python exception it is, so it is not mistaken for
a backend you can retry.

## Representation

`SigningCertificate` is a secret while it is in memory: it hides its credentials
in `repr()`, refuses to be pickled or copied, and has no serialization API. Your
adapter inherits that discipline:

- `repr()` of the store and of anything it returns shows counts or metadata only,
  never a certificate, a fingerprint, a key, or a row containing them.
- Do not serialize the record yourself. No `pickle`, no `model_dump`, no JSON of
  a `SigningCertificate`, and no log line containing one.
- Obtain key passwords when you need them and drop them afterwards. Do not keep a
  password on the adapter.

## Ownership

Your application creates the backend connection and closes it. An SDK client
never closes a store: closing a client leaves the store usable, and the same
store can serve several clients. If your adapter needs a connection per call,
open and close it inside the call; if it needs a pool, let the application own
the pool.

Import optional third-party libraries inside the adapter, in `__init__` or in the
method that needs them, not at module import time. A store that needs a keychain
client must not make the SDK depend on it for everyone else.

## Testing an adapter

Run the same contract on every adapter you write, sync and async alike:

1. `save()` then `load()` returns the same pair. Sign something with the loaded
   key and verify with the loaded certificate: a round trip that only compares
   metadata can pass while the key material is broken.
2. Saving an equal record twice keeps one record and returns the same metadata.
3. Saving a different record under a stored reference raises
   `KSeFCertificateStoreConflictError` and leaves the stored record readable.
4. Loading a reference that was never saved raises
   `KSeFCertificateStoreNotFoundError`.
5. `list()` returns only the records of the requested environment, filters by
   `certificate_type` when given one, orders by `valid_from` and then by
   `fingerprint_sha256`, and includes an expired record.
6. `delete()` returns `True` for a record that was there and `False` for one
   that was not, and the record is gone afterwards.
7. One certificate saved in two environments is two independent records.

## Minimal skeleton

The shape below is the smallest thing that satisfies the sync protocol. The
backend is a dict of bytes, so the interesting part is what `load()` has to
rebuild.

```python
from ksef2 import Environment
from ksef2.certificate_stores import (
    SigningCertificate,
    SigningCertificateInfo,
    SigningCertificateRef,
)
from ksef2.models import CertificateTypeValue
from ksef2.xades import XAdESCredentials

class BytesStore:
    """Hold signing certificates in a mapping of reference to stored bytes."""

    def __init__(self, rows: dict[bytes, bytes]) -> None:
        self._rows = rows

    def save(self, certificate: SigningCertificate) -> SigningCertificateInfo:
        """Store the pair under its own reference and return its metadata."""
        ...  # Encode the certificate and the key, write them atomically, return
        # the metadata, and raise KSeFCertificateStoreConflictError if the
        # reference already holds a record with different metadata.

    def load(self, reference: SigningCertificateRef) -> SigningCertificate:
        """Rebuild the record stored under ``reference``."""
        ...  # Read the stored bytes, raising KSeFCertificateStoreNotFoundError
        # when there are none, then decrypt the key and rebuild the record:
        # record = SigningCertificate(
        #     XAdESCredentials(certificate, private_key),
        #     environment=reference.environment,
        #     certificate_type=stored_certificate_type,
        #     ksef_serial_number=stored_ksef_serial_number,
        # )
        # if record.info.reference != reference:
        #     raise KSeFCertificateStoreMaterialError(
        #         "The stored record does not match its reference.",
        #         operation="load",
        #         reference=reference,
        #     )
        # return record

    def list(
        self,
        *,
        environment: Environment,
        certificate_type: CertificateTypeValue | None = None,
    ) -> tuple[SigningCertificateInfo, ...]:
        """Return the metadata of every record of one environment."""
        ...  # Filter by environment and, when given, by certificate_type, then
        # sort by valid_from and fingerprint_sha256. Never decrypt a key here.

    def delete(self, reference: SigningCertificateRef) -> bool:
        """Remove the local record and report whether one was there."""
        ...  # Return True when a record was removed and False when there was
        # none. Other backends' failures are KSeFCertificateStoreError.
```

For an async client, make each of the four methods a coroutine function. Passing
a sync store to an async client, or the reverse, raises `KSeFArgumentError`
before the client touches it.

## Related pages

- [Authenticate](authenticate.md): Authenticate with a stored certificate.
- [Manage certificates](manage-certificates.md): Store the certificate KSeF issued, next to its key.
- [Certificates](../concepts/certificates.md): Keep signing-certificate stores and the encryption-certificate cache apart.
- [Configure a certificate store](configure-certificate-store.md): Configure the cache of KSeF public encryption certificates.
