"""Filesystem signing-certificate store: one encrypted JSON record per certificate."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import override

from ksef2._certificate_stores import _filesystem_ops
from ksef2._config import Environment
from ksef2._core import exceptions
from ksef2._domain.models.certificates import CertificateTypeValue
from ksef2._domain.models.signing_certificates import (
    SigningCertificate,
    SigningCertificateInfo,
    SigningCertificateRef,
)


class AsyncFilesystemSigningCertificateStore:
    """Keep signing certificates as files, one encrypted record per certificate.

    Each record is a JSON file at ``<root>/<environment>/<fingerprint>.json`` holding
    the certificate and its private key as PKCS#8 encrypted with a password. There is
    no plaintext mode. ``password_provider(reference) -> bytes`` is called on each
    ``save()`` that writes a record and on each ``load()``; its result is never kept.
    ``list()`` reads only certificates and needs no password.

    A record is written to a temporary file and linked into place, so it is complete
    or absent, and concurrent writers never overwrite each other. Files are 0600 and
    directories 0700 on POSIX; on Windows, restrict ``root`` yourself. File and crypto
    work runs in a worker thread, so it never blocks the event loop.

    The adapter satisfies the signing-certificate store protocol structurally; it
    does not inherit from it.

    Args:
        root: Directory this store owns. It is created when missing.
        password_provider: Returns the password protecting the record of the
            reference it is given.

    Raises:
        KSeFArgumentError: If ``root`` is not a ``Path``, or ``password_provider`` is
            not callable.
        KSeFCertificateStoreAccessError: If ``root`` is not accessible.
        KSeFCertificateStoreUnavailableError: If ``root`` could not be created.
    """

    __slots__ = ("_root", "_password_provider")

    def __init__(
        self,
        root: Path,
        *,
        password_provider: Callable[[SigningCertificateRef], bytes],
    ) -> None:
        # The guards are for callers without runtime type checking; the annotations
        # above are what type checkers see.
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
            root, Path
        ):
            raise exceptions.KSeFArgumentError(  # pyright: ignore[reportUnreachable]
                "root must be a pathlib.Path.",
                hint="Pass Path(...) for the store directory.",
            )
        if not callable(password_provider):
            raise exceptions.KSeFArgumentError(  # pyright: ignore[reportUnreachable]
                "password_provider must be callable.",
                hint="Pass a function that takes a SigningCertificateRef and returns "
                "the password bytes, for example lambda ref: os.environ[...].encode().",
            )
        try:
            self._root = _filesystem_ops.prepare_root(root)
        except OSError as exc:
            raise _filesystem_ops._os_error(  # pyright: ignore[reportPrivateUsage]
                exc, "open", None
            ) from exc
        self._password_provider = password_provider

    async def save(self, certificate: SigningCertificate) -> SigningCertificateInfo:
        """Write this certificate's record and return its metadata.

        An equal record already stored is left in place and its metadata returned,
        without calling the password provider.

        Args:
            certificate: The validated pair to persist, keyed by ``certificate.reference``.

        Returns:
            The metadata of the stored record.

        Raises:
            KSeFArgumentError: If ``certificate`` is not a ``SigningCertificate``.
            KSeFCertificateStoreConflictError: If a different record is stored under
                this reference.
            KSeFCertificateStoreAccessError: If a file is not accessible, a symbolic
                link stands where the record belongs, or the password is empty.
            KSeFCertificateStoreMaterialError: If the stored record cannot be read.
            KSeFCertificateStoreUnavailableError: If the record could not be written.
        """
        return await asyncio.to_thread(
            _filesystem_ops.save, self._root, self._password_provider, certificate
        )

    async def load(self, reference: SigningCertificateRef) -> SigningCertificate:
        """Read and decrypt the record stored under ``reference``.

        Args:
            reference: Environment and certificate fingerprint to read back.

        Returns:
            The stored pair, ready to sign with.

        Raises:
            KSeFArgumentError: If ``reference`` is not a ``SigningCertificateRef``.
            KSeFCertificateStoreNotFoundError: If no record is stored under it.
            KSeFCertificateStoreMaterialError: If the record is corrupt, cannot be
                decrypted, or does not match this reference.
            KSeFCertificateStoreAccessError: If a file is not accessible, a symbolic
                link stands where the record belongs, or the password is empty.
            KSeFCertificateStoreUnavailableError: If the record could not be read.
        """
        return await asyncio.to_thread(
            _filesystem_ops.load, self._root, self._password_provider, reference
        )

    async def list(
        self,
        *,
        environment: Environment,
        certificate_type: CertificateTypeValue | None = None,
    ) -> tuple[SigningCertificateInfo, ...]:
        """Return the metadata of every record stored for one environment.

        No private key is decrypted, so the password provider is not called.

        Args:
            environment: Environment whose records to return.
            certificate_type: When given, return only records of this purpose.

        Returns:
            Matching metadata, ordered by ``valid_from`` and then by
                ``fingerprint_sha256``.

        Raises:
            KSeFCertificateStoreMaterialError: If a stored record cannot be read.
            KSeFCertificateStoreAccessError: If a file is not accessible.
            KSeFCertificateStoreUnavailableError: If the directory could not be read.
        """
        return await asyncio.to_thread(
            _filesystem_ops.list_records, self._root, environment, certificate_type
        )

    async def delete(self, reference: SigningCertificateRef) -> bool:
        """Remove the record stored under ``reference``.

        Only the local file goes away: the certificate stays valid in KSeF until it
        is revoked.

        Args:
            reference: Environment and certificate fingerprint to remove.

        Returns:
            ``True`` when a record was removed, ``False`` when there was none.

        Raises:
            KSeFArgumentError: If ``reference`` is not a ``SigningCertificateRef``.
            KSeFCertificateStoreAccessError: If the file is not accessible.
            KSeFCertificateStoreUnavailableError: If the record could not be removed.
        """
        return await asyncio.to_thread(_filesystem_ops.delete, self._root, reference)

    @property
    def root(self) -> Path:
        """Return the directory this store keeps its records in.

        Returns:
            The ``root`` accepted at construction, created if it was missing.
        """
        return self._root

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}(root={str(self._root)!r})"
