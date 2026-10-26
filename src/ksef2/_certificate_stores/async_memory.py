"""In-memory signing-certificate store, kept for tests and short-lived processes."""

import threading
from typing import override

from ksef2._config import Environment
from ksef2._core import exceptions
from ksef2._domain.models.certificates import CertificateTypeValue
from ksef2._domain.models.signing_certificates import (
    SigningCertificate,
    SigningCertificateInfo,
    SigningCertificateRef,
)


class AsyncInMemorySigningCertificateStore:
    """Keep signing certificates in a dict for as long as the process lives.

    Meant for tests and for short-lived processes that load a pair once and sign with
    it. Nothing survives the process: a restart starts with an empty store, so use a
    persistent store for credentials you must keep.

    Records are held as the validated :class:`SigningCertificate` objects they were
    saved with, so ``load()`` hands back exactly what ``save()`` took. The repr shows
    only how many records are held, never a certificate, a key or a fingerprint.

    The adapter satisfies the signing-certificate store protocol structurally; it does
    not inherit from it.
    """

    __slots__ = ("_records", "_lock")

    def __init__(self) -> None:
        self._records: dict[SigningCertificateRef, SigningCertificate] = {}
        self._lock = threading.Lock()

    async def save(self, certificate: SigningCertificate) -> SigningCertificateInfo:
        """Store a pair in memory, keeping the first record of equal metadata.

        Args:
            certificate: The validated pair to keep, keyed by ``certificate.reference``.

        Returns:
            The metadata of the stored record.

        Raises:
            KSeFArgumentError: If ``certificate`` is not a ``SigningCertificate``.
            KSeFCertificateStoreConflictError: If a different record is already stored
                under this reference.
        """
        # The guard is for callers without runtime type checking; the annotation
        # above is what type checkers see.
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
            certificate, SigningCertificate
        ):
            raise exceptions.KSeFArgumentError(  # pyright: ignore[reportUnreachable]
                "save() needs a SigningCertificate.",
                hint="Wrap the XAdESCredentials in SigningCertificate(credentials, "
                "environment=...).",
            )
        with self._lock:
            reference = certificate.reference
            existing = self._records.get(reference)
            if existing is None:
                self._records[reference] = certificate
                return certificate.info
            if existing.info == certificate.info:
                return existing.info
            raise exceptions.KSeFCertificateStoreConflictError(
                "A different signing certificate record is already stored under "
                "this reference.",
                operation="save",
                reference=certificate.reference,
            )

    async def load(self, reference: SigningCertificateRef) -> SigningCertificate:
        """Return the pair stored under ``reference``.

        Args:
            reference: Environment and certificate fingerprint to read back.

        Returns:
            The stored pair, the very object that was saved.

        Raises:
            KSeFCertificateStoreNotFoundError: If nothing is stored under this reference.
        """
        with self._lock:
            stored = self._records.get(reference)
            if stored is None:
                raise exceptions.KSeFCertificateStoreNotFoundError(
                    "No signing certificate is stored under this reference.",
                    operation="load",
                    reference=reference,
                )
            return stored

    async def list(
        self,
        *,
        environment: Environment,
        certificate_type: CertificateTypeValue | None = None,
    ) -> tuple[SigningCertificateInfo, ...]:
        """Return the metadata of every record held for one environment.

        Args:
            environment: Environment whose records to return.
            certificate_type: When given, return only records of this KSeF certificate
                purpose.

        Returns:
            Metadata for every matching record, ordered by ``valid_from`` and then by
                ``fingerprint_sha256``.
        """
        with self._lock:
            matching = [
                record.info
                for record in self._records.values()
                if record.info.reference.environment is environment
                and (
                    certificate_type is None
                    or record.info.certificate_type == certificate_type
                )
            ]
        return tuple(
            sorted(
                matching,
                key=lambda info: (info.valid_from, info.reference.fingerprint_sha256),
            )
        )

    async def delete(self, reference: SigningCertificateRef) -> bool:
        """Drop the pair stored under ``reference``.

        Args:
            reference: Environment and certificate fingerprint to forget.

        Returns:
            ``True`` when a record was removed, ``False`` when there was none.
        """
        with self._lock:
            return self._records.pop(reference, None) is not None

    @override
    def __repr__(self) -> str:
        with self._lock:
            return f"{type(self).__name__}(records={len(self._records)})"
