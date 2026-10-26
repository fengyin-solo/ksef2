"""Stores that persist XAdES signing certificates with their private keys.

Not to be confused with ``ksef2.CertificateStore``, the store passed to a client as
``certificate_store=``: that one caches the KSeF public encryption certificates the
SDK downloads, and holds no private key.
"""

from ksef2._certificate_stores.async_memory import AsyncInMemorySigningCertificateStore
from ksef2._certificate_stores.async_protocols import (
    AsyncSigningCertificateStoreProtocol,
)
from ksef2._certificate_stores.memory import InMemorySigningCertificateStore
from ksef2._certificate_stores.protocols import SigningCertificateStoreProtocol
from ksef2._domain.models.signing_certificates import (
    SigningCertificate,
    SigningCertificateFingerprint,
    SigningCertificateInfo,
    SigningCertificateRef,
)

__all__ = [
    "AsyncInMemorySigningCertificateStore",
    "AsyncSigningCertificateStoreProtocol",
    "InMemorySigningCertificateStore",
    "SigningCertificate",
    "SigningCertificateFingerprint",
    "SigningCertificateInfo",
    "SigningCertificateRef",
    "SigningCertificateStoreProtocol",
]
