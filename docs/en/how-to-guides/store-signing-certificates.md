---
title: Store signing certificates
description: Keep XAdES signing certificates and their private keys in an in-memory or encrypted filesystem signing-certificate store.
---

A signing-certificate store keeps the certificate-and-key pairs you sign KSeF
requests with. It takes a `SigningCertificate` record, hands back the same pair
when you ask for it by reference, and lets you list what you hold without
unlocking a single key. `client.authentication.with_xades()` still does the
signing; the store only decides where the pair lives between calls.

This is **not** the certificate store you pass to a client as
`certificate_store=`. That one, `ksef2.CertificateStore`, caches the KSeF public
*encryption* certificates the SDK downloads to encrypt invoice and export
key material, and it never holds a private key. The stores on this page live in
`ksef2.certificate_stores` and hold your own signing keys.

Keys a device refuses to export, such as an HSM or a KMS key, are out of scope:
these stores exchange pairs whose private key your process can hold.

## Wrap the pair in a record

`SigningCertificate` binds loaded `XAdESCredentials` to the environment you sign
in, and derives the metadata a store records from the certificate itself.

```python
from pathlib import Path

from ksef2 import Environment
from ksef2.certificate_stores import SigningCertificate
from ksef2.xades import XAdESCredentials

credentials = XAdESCredentials.from_pem(
    Path("company.pem").read_bytes(),
    Path("company.key").read_bytes(),
    key_password=b"key-file-password",
)

record = SigningCertificate(
    credentials,
    environment=Environment.DEMO,
    certificate_type="authentication",
)

print(record.info.reference)
print(record.info.valid_to)
```

`certificate_type` and `ksef_serial_number` are optional: leave them out for a
certificate KSeF knows nothing about, or for one you generated yourself. The
record hides its credentials in `repr()`, refuses to be pickled or copied, and
has no JSON serialization API, so the only supported way to persist it is
`save()`.

## Keep records in memory

`InMemorySigningCertificateStore` and `AsyncInMemorySigningCertificateStore`
hold records for as long as the process lives. Nothing survives a restart, which
is exactly what you want in a test and rarely what you want in production.

```python
from ksef2 import Environment
from ksef2.certificate_stores import (
    AsyncInMemorySigningCertificateStore,
    InMemorySigningCertificateStore,
)

store = InMemorySigningCertificateStore()
store.save(record)

held = store.list(environment=Environment.DEMO)
loaded = store.load(held[0].reference)
```

## Keep records on disk

`FilesystemSigningCertificateStore` writes one JSON record per certificate to
`<root>/<environment>/<fingerprint>.json`. The record holds the certificate and
its private key as PKCS#8 encrypted with a password you supply. There is no
plaintext mode.

The password provider is a plain callable from a reference to password bytes. It
is called on every `load()` and on every `save()` that writes a new record, and
the store keeps neither the password nor the record.

```python
import os
from pathlib import Path

from ksef2 import Environment
from ksef2.certificate_stores import FilesystemSigningCertificateStore

store = FilesystemSigningCertificateStore(
    Path("~/.local/share/myapp/ksef-signing").expanduser(),
    password_provider=lambda ref: os.environ["MYAPP_KSEF_STORE_PASSWORD"].encode(),
)

info = store.save(record)

for held in store.list(environment=Environment.DEMO):
    print(held.reference.fingerprint_sha256, held.valid_to)

record = store.load(info.reference)
```

`list()` reads the certificate only, so it never asks for a password. That is
what makes a startup check or an admin screen cheap: you can show what you hold
and let the operator decide before anything is unlocked.

Deleting a record removes the local file and nothing else:

```python
removed = store.delete(info.reference)
```

The async adapter offers the same four operations with `await`, and runs the
file and key work, including your password provider, in a worker thread:

```python
from ksef2.certificate_stores import AsyncFilesystemSigningCertificateStore

store = AsyncFilesystemSigningCertificateStore(
    Path("~/.local/share/myapp/ksef-signing").expanduser(),
    password_provider=lambda ref: os.environ["MYAPP_KSEF_STORE_PASSWORD"].encode(),
)

info = await store.save(record)
held = await store.list(environment=Environment.DEMO)
record = await store.load(info.reference)
```

A cancelled `await store.save(...)` may still have written the record: a write
either lands complete or is absent, and repeating the same `save()` is safe and
returns the stored metadata.

## Pick a certificate by its reference

A store never picks a "latest" or "best" certificate for you: `load()` returns
exactly the reference you name, an expired record included. That is deliberate,
because a silent upgrade of a signing key is the failure mode you least want to
debug at 2 a.m.

So store the reference in your own configuration, next to the NIP and the
environment you already keep there:

```python
from ksef2 import Client, Environment
from ksef2.certificate_stores import SigningCertificateRef

reference = SigningCertificateRef(
    environment=Environment.PRODUCTION,
    fingerprint_sha256="8f14e45fceea167a5a36dedd4bea2543a9012d45ded2b8f0b13c8e0a5c0b23c1",
)

with Client(Environment.PRODUCTION) as client:
    record = store.load(reference)
    auth = client.authentication.with_xades(
        nip=os.environ["KSEF2_NIP"],
        credentials=record.credentials,
    )
```

`info.reference` is two short strings and holds no key material, so it is safe
to log, to put in a config file and to compare. When a certificate is renewed you
get a new fingerprint, which means a new reference: verify the new pair, then
switch your configuration over. Both records can sit in the store at the same
time, which is how you keep the old one available until the switchover.

## Persist a generated TEST certificate

`generate_test_certificate()` builds a self-signed RSA pair for the TEST
environment. It returns bare cryptography objects and keeps nothing itself, so a
generated pair is gone when the process ends unless you put it in a store:

```python
from ksef2 import Environment
from ksef2.certificate_stores import SigningCertificate
from ksef2.xades import XAdESCredentials, generate_test_certificate

certificate, private_key = generate_test_certificate(nip="5261040828")

store.save(
    SigningCertificate(
        XAdESCredentials(certificate, private_key),
        environment=Environment.TEST,
    )
)
```

The record is now reusable across restarts, and `list(environment=Environment.TEST)`
shows it without a password.

## Security notes

- On POSIX, records are created `0600` and directories `0700`, and an existing
  `root` keeps the permissions you gave it. On Windows a file inherits the access
  control list of its directory, so restrict `root` yourself before you store
  anything in it.
- The password is asked for on every `load()` and every `save()` that writes a
  new record, and is never kept: not on the store, not in the repr, not between
  calls. `list()` needs no password at
  all.
- A loaded private key is an ordinary in-memory object. The store caches nothing,
  but it also promises no zeroization of the memory the key occupied. Treat the
  returned `SigningCertificate` as a secret and drop it when you are done.
- The store refuses to follow a symbolic link left where a record belongs, and
  it never rewrites a record it cannot read, so an
  unsupported record version stays on disk untouched.
- Deleting a record does not revoke anything in KSeF. The certificate stays valid
  there until you revoke it, and a pair already loaded in memory keeps signing.

## Errors

Every failure is a `KSeFCertificateStoreError`, and each one says which operation
failed and which record it was about. See
[Error Reference](../reference/errors.md) for the whole hierarchy.

| Error | When the filesystem store raises it |
| --- | --- |
| `KSeFArgumentError` | `root` was not a `Path`, the password provider was not callable, or a value the method needs was of the wrong kind. |
| `KSeFCertificateStoreNotFoundError` | `load()` was asked for a reference with no record. |
| `KSeFCertificateStoreConflictError` | `save()` was given a record whose metadata differs from the one already stored under that reference. |
| `KSeFCertificateStoreAccessError` | The files are not readable by this process, a symbolic link is in the way, or the password provider returned an empty password. |
| `KSeFCertificateStoreMaterialError` | The record is corrupt, in an unsupported format, undecryptable, or does not match the reference it is stored under. |
| `KSeFCertificateStoreUnavailableError` | The storage could not take the write or the read, for example a full disk. |

Anything your own password provider raises comes back unchanged: a provider that
cannot reach its secret store is a deployment fault, not a damaged record.
