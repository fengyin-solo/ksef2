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

    Every record is one JSON document at ``<root>/<environment>/<fingerprint>.json``
    holding the certificate and its private key as PKCS#8 encrypted with a password,
    plus the metadata that identifies the record. There is no plaintext mode: a
    record always carries an encrypted key, and a record whose format or version this
    store does not know is refused and left exactly as it is on disk.

    ``list()`` reads metadata from the certificate alone and never asks for a
    password. ``password_provider(reference) -> bytes`` is called on each ``save()``
    and ``load()`` and its result is never kept: nothing here holds a password, a key
    or a record between calls, so the repr names only the directory.

    File and crypto work blocks. The ``async`` flavour of this store runs it in a
    worker thread, and calls the password provider in that thread too, so a slow disk
    or a key derivation never stalls the event loop.

    A record reaches its final name through a temporary file and a link, so a record
    is either complete or absent, and two writers of one record never overwrite each
    other: the loser compares the winner's record and either returns it or reports a
    conflict. That also means a cancelled ``await save()`` may have published the
    record after all; repeating the same ``save()`` is the way to find out, and is
    safe.

    Files are created owner-only (0600) and directories owner-only (0700) on POSIX.
    On Windows a file inherits the access control list of its directory, so restrict
    ``root`` yourself before storing anything in it. A symbolic link left where a
    record or an environment directory belongs is refused rather than followed.

    Loaded keys are ordinary in-memory secrets: the store keeps no cache of them and
    promises no zeroization of the memory they occupy.

    The adapter satisfies the signing-certificate store protocol structurally; it
    does not inherit from it.

    Args:
        root: Directory this store owns. It is created when missing.
        password_provider: Returns the password protecting the record of the
            reference it is given.

    Raises:
        KSeFArgumentError: If ``root`` is not a ``Path``, or ``password_provider`` is
            not callable.
        KSeFCertificateStoreAccessError: If a file under ``root`` is not readable by
            this process.
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
                exc, operation="open", reference=None
            ) from exc
        self._password_provider = password_provider

    async def save(self, certificate: SigningCertificate) -> SigningCertificateInfo:
        """Write this certificate's record and return its metadata.

        A record already stored under the same reference with equal metadata is left
        in place and its metadata returned, so repeating a save costs nothing and the
        password provider is not called for it. The record is written to a temporary
        file in the environment directory, flushed, and linked into place.

        Args:
            certificate: The validated pair to persist, keyed by ``certificate.reference``.

        Returns:
            The metadata of the stored record, which is the given one for a new record
                and the stored one for an equal repeat.

        Raises:
            KSeFArgumentError: If ``certificate`` is not a ``SigningCertificate``.
            KSeFCertificateStoreConflictError: If a different record is stored under
                this reference.
            KSeFCertificateStoreAccessError: If a file is not accessible to this
                process, a symbolic link is in the way, or the password provider
                returned an empty password.
            KSeFCertificateStoreMaterialError: If the record already stored under this
                reference cannot be read.
            KSeFCertificateStoreUnavailableError: If the record could not be written.
                When its ``outcome_ambiguous`` is true the record may be on disk
                anyway; save it again to find out.
        """
        return await asyncio.to_thread(
            _filesystem_ops.save, self._root, self._password_provider, certificate
        )

    async def load(self, reference: SigningCertificateRef) -> SigningCertificate:
        """Read and decrypt the record stored under ``reference``.

        The password is asked for only once the stored envelope parsed, so a damaged
        record is reported without unlocking anything.

        Args:
            reference: Environment and certificate fingerprint to read back.

        Returns:
            The stored pair, ready to sign with.

        Raises:
            KSeFArgumentError: If ``reference`` is not a ``SigningCertificateRef``.
            KSeFCertificateStoreNotFoundError: If no record is stored under it.
            KSeFCertificateStoreMaterialError: If the record is corrupt, cannot be
                decrypted, or does not match this reference.
            KSeFCertificateStoreAccessError: If a file is not accessible to this
                process, a symbolic link is in the way, or the password provider
                returned an empty password.
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

        The private key of a record is never decrypted here, so the password provider
        is not called. Expired records are listed as stored, and a record that cannot
        be read is an error rather than a gap in the listing. Temporary files of
        interrupted writes, and any name that is not a fingerprint, are skipped.

        Args:
            environment: Environment whose records to return.
            certificate_type: When given, return only records of this KSeF certificate
                purpose.

        Returns:
            Metadata for every matching record, ordered by ``valid_from`` and then by
                ``fingerprint_sha256``. An empty tuple when the environment has no
                directory yet.

        Raises:
            KSeFCertificateStoreMaterialError: If a stored record cannot be read.
            KSeFCertificateStoreAccessError: If a symbolic link stands in place of the
                environment directory.
            KSeFCertificateStoreUnavailableError: If the directory could not be read.
        """
        return await asyncio.to_thread(
            _filesystem_ops.list_records, self._root, environment, certificate_type
        )

    async def delete(self, reference: SigningCertificateRef) -> bool:
        """Remove the record stored under ``reference`` from the filesystem.

        Only the local file goes away. The certificate stays valid in KSeF, which
        takes a revocation, and a pair already loaded into memory keeps signing.

        Args:
            reference: Environment and certificate fingerprint to remove.

        Returns:
            ``True`` when a record was removed, ``False`` when there was none.

        Raises:
            KSeFArgumentError: If ``reference`` is not a ``SigningCertificateRef``.
            KSeFCertificateStoreAccessError: If a symbolic link stands in place of the
                environment directory.
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
