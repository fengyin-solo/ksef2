"""Protocols for stores that persist XAdES signing certificates and private keys."""

from typing import Protocol, runtime_checkable

from ksef2._config import Environment
from ksef2._domain.models.certificates import CertificateTypeValue
from ksef2._domain.models.signing_certificates import (
    SigningCertificate,
    SigningCertificateInfo,
    SigningCertificateRef,
)


@runtime_checkable
class AsyncSigningCertificateStoreProtocol(Protocol):
    """Structural contract for stores of XAdES signing certificates and their keys.

    A store hands out :class:`SigningCertificate` records, each a validated certificate
    and private key with the metadata that identifies it, and takes the same records
    back. Adapters decide how a record is encoded, encrypted, unlocked and reached on
    a backend; applications decide which adapter to use and pass the loaded pair to
    ``with_xades()``.

    The application owns the backend's lifecycle: closing an SDK client does not close
    a store, and a store keeps working across clients. This is not the
    ``CertificateStoreProtocol`` passed as ``certificate_store=`` to a client, which
    caches the KSeF public encryption certificates the SDK downloads.

    Keys a device refuses to export, such as an HSM or KMS key, are out of scope for
    this protocol: it exchanges pairs whose private key the process holds.
    """

    async def save(self, certificate: SigningCertificate) -> SigningCertificateInfo:
        """Persist one complete certificate and key pair and return its metadata.

        The pair is written atomically, so a record is either complete or absent.
        Saving a record whose metadata equals the stored one changes nothing and
        returns the stored metadata.

        Args:
            certificate: The validated pair to persist, keyed by ``certificate.reference``.

        Returns:
            The metadata of the stored record, which is the given one for a new record
                and the stored one for an equal repeat.

        Raises:
            KSeFCertificateStoreConflictError: If a different record, one whose metadata
                differs, is already stored under this reference.
            KSeFCertificateStoreAccessError: If the store's credentials or permissions
                do not allow writing.
            KSeFCertificateStoreUnavailableError: If the backend could not be reached or
                could not take the record.
        """
        ...

    async def load(self, reference: SigningCertificateRef) -> SigningCertificate:
        """Return exactly the record stored under ``reference``.

        A store never picks a "latest" or "best" certificate: the caller names the
        record, and an expired one is returned as stored.

        Args:
            reference: Environment and certificate fingerprint to load.

        Returns:
            The stored pair, ready to sign with.

        Raises:
            KSeFCertificateStoreNotFoundError: If nothing is stored under this reference.
            KSeFCertificateStoreMaterialError: If the stored record is corrupt, cannot be
                decrypted, or does not match this reference.
            KSeFCertificateStoreAccessError: If the store's credentials or permissions do
                not allow reading.
            KSeFCertificateStoreUnavailableError: If the backend could not be reached.
        """
        ...

    async def list(
        self,
        *,
        environment: Environment,
        certificate_type: CertificateTypeValue | None = None,
    ) -> tuple[SigningCertificateInfo, ...]:
        """Return the metadata of every record held for one environment.

        Reading metadata never unlocks a private key and never contacts KSeF, and it
        reports expired certificates too: the metadata says what the certificate
        claims, not what KSeF currently accepts.

        Args:
            environment: Environment whose records to return.
            certificate_type: When given, return only records of this KSeF certificate
                purpose.

        Returns:
            Metadata for every matching record, ordered by ``valid_from`` and then by
                ``fingerprint_sha256``.
        """
        ...

    async def delete(self, reference: SigningCertificateRef) -> bool:
        """Remove the local record stored under ``reference``.

        Only the local copy goes away. The certificate stays valid in KSeF, which
        takes a revocation, and a pair already loaded into memory keeps signing.

        Args:
            reference: Environment and certificate fingerprint to remove.

        Returns:
            ``True`` when a record was removed, ``False`` when there was none.

        Raises:
            KSeFCertificateStoreAccessError: If the store's credentials or permissions do
                not allow removing the record.
            KSeFCertificateStoreUnavailableError: If the backend could not be reached.
        """
        ...
