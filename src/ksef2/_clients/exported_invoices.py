"""Decrypted invoice export, ready to read or save."""

import io
import os
import json
import re
import stat
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Self, cast, final

from ksef2._core import exceptions
from ksef2._core.paths import require_path
from ksef2._domain.models.compression import CompressionType, normalize_compression_type
from ksef2._domain.models.invoices import (
    InvoiceMetadata,
    InvoicePackage,
)
from ksef2._infra.mappers.invoices import from_spec
from ksef2._infra.schema.api import spec


METADATA_FILE_NAME = "_metadata.json"
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


@final
class ExportedInvoices:
    """Decrypted result of an invoice export.

    The decrypted package parts are joined into one ZIP or TarGz archive, which holds one
    ``<ksef_number>.xml`` file per invoice and a ``_metadata.json`` file. The archive is
    opened lazily; use ``ExportJob.wait()`` or ``from_archive()``. An export that
    matched no invoices has an empty archive.

    Persist ``archive`` as plain bytes and restore it with ``from_archive()``.
    Invoice metadata is read from the archive only when requested.
    """

    def __init__(
        self,
        parts: list[bytes],
        *,
        package: InvoicePackage | None = None,
    ) -> None:
        """Create the export result.

        Args:
            parts: Decrypted package parts in ordinal order; concatenated they form the ZIP or TarGz archive.
            package: Package metadata from the export status, if known.
        """
        self._archive = b"".join(parts)
        self._archive_path: Path | None = None
        self._package = package
        self._compression: CompressionType = "zip"
        self._metadata: list[InvoiceMetadata] | None = None
        self._metadata_loaded = False

    @property
    def archive(self) -> bytes:
        """Get the raw ZIP or TarGz archive.

        Returns:
            The decrypted and joined package parts, exactly as KSeF built the archive.
        """
        if self._archive_path is not None:
            return self._archive_path.read_bytes()
        return self._archive

    @property
    def package(self) -> InvoicePackage | None:
        """Get the package metadata reported by the export status.

        Returns:
            Invoice count, size, truncation flag and the dates for continuing a truncated export; ``None`` if unknown.
        """
        return self._package

    @property
    def metadata(self) -> list[InvoiceMetadata] | None:
        """Get the invoice metadata stored in the package.

        Returns:
            The parsed ``invoices`` list of ``_metadata.json``, an empty list if
            the package reports zero invoices, or ``None`` if metadata is unavailable.

        Raises:
            KSeFResponseValidationError: If ``_metadata.json`` is not valid metadata.
            zipfile.BadZipFile: If a ZIP archive is invalid.
            tarfile.TarError: If a TarGz archive is invalid.
            ValueError: If an archive contains links or special files.
        """
        if not self._metadata_loaded:
            self._metadata = self._read_metadata()
            self._metadata_loaded = True
        return self._metadata

    def invoices(self) -> Iterator[tuple[str, bytes]]:
        """Iterate over the invoices in the package.

        Yields:
            A ``(ksef_number, xml)`` pair for each invoice file, in archive order.

        Raises:
            zipfile.BadZipFile: If a ZIP archive is invalid.
            tarfile.TarError: If a TarGz archive is invalid.
            ValueError: If an archive contains links or special files.
        """
        if self._is_empty():
            return
        with self._open() as archive:
            for filename, is_directory, info in _archive_entries(archive):
                name = PurePosixPath(filename)
                if is_directory or name.suffix.lower() != ".xml":
                    continue
                if name.name.startswith("_"):
                    continue
                yield name.stem, _read_entry(archive, info)

    def save(self, directory: Path | str) -> list[Path]:
        """Extract the package into a directory.

        Every entry path is validated first, and nothing is written if one is
        unsafe: absolute paths, ``..`` segments, backslashes, drive letters and NUL
        bytes are refused. Links and special files are also refused.

        Args:
            directory: Directory to extract into; created if missing.

        Returns:
            The paths of the written files.

        Raises:
            ValueError: If an archive entry path would escape ``directory``.
            zipfile.BadZipFile: If a ZIP archive is invalid.
            tarfile.TarError: If a TarGz archive is invalid.
            ValueError: If an archive contains links or special files.
            OSError: If a file or directory cannot be written.
        """
        root = Path(directory)
        if self._is_empty():
            root.mkdir(parents=True, exist_ok=True)
            return []
        with self._open() as archive:
            targets: list[tuple[zipfile.ZipInfo | tarfile.TarInfo, bool, Path]] = []
            resolved_root = root.resolve()
            for filename, is_directory, info in _archive_entries(archive):
                _reject_unsafe_entry(filename)
                target = root.joinpath(*PurePosixPath(filename).parts)
                if not target.resolve().is_relative_to(resolved_root):
                    raise ValueError(f"Unsafe archive entry path: {filename!r}")
                targets.append((info, is_directory, target))

            root.mkdir(parents=True, exist_ok=True)
            written: list[Path] = []
            for info, is_directory, target in targets:
                if is_directory:
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                _ = target.write_bytes(_read_entry(archive, info))
                written.append(target)
        return written

    @classmethod
    def from_archive(
        cls, archive: bytes, *, compression: CompressionType = "zip"
    ) -> Self:
        """Read a previously saved, decrypted invoice archive.

        Construction is lazy: the archive and its metadata are opened only when
        reading invoices, requesting metadata or extracting files. No network
        access or encryption keys are needed.

        Args:
            archive: Plain ZIP or TarGz bytes, as returned by ``archive``.
            compression: Archive format, ``"zip"`` by default or ``"tar_gz"``.

        Returns:
            An export result with no package status or download URLs. Invoice
            metadata is derived from the archive on first access.

        Raises:
            ValueError: If the compression type is unsupported.
        """
        compression = normalize_compression_type(compression)
        result = cls([archive])
        result._compression = compression
        return result

    @classmethod
    def from_path(
        cls,
        path: os.PathLike[str],
        *,
        compression: CompressionType = "zip",
        package: InvoicePackage | None = None,
    ) -> Self:
        """Open a decrypted ZIP or TarGz package from disk without loading it.

        Invoice entries are read only as the iterator reaches them. The returned
        object keeps the path, so the file must remain available while it is used.

        Args:
            path: Path to the decrypted archive file, as any ``os.PathLike``.
            compression: Archive format, inferred as TarGz for ``.tar.gz`` or
                ``.tgz`` paths and ZIP otherwise.
            package: Optional export status metadata associated with the archive.

        Returns:
            An export result backed by the archive file.

        Raises:
            KSeFArgumentError: If ``path`` is a ``str``, ``bytes`` or not ``os.PathLike``.
        """
        result = cls([])
        result._archive_path = require_path(path)
        if compression == "zip" and result._archive_path.name.lower().endswith(
            (".tar.gz", ".tgz")
        ):
            compression = "tar_gz"
        result._compression = normalize_compression_type(compression)
        result._package = package
        return result

    def _is_empty(self) -> bool:
        return self._archive_path is None and not self._archive

    def _open(self) -> zipfile.ZipFile | tarfile.TarFile:
        compression = (
            self._package.compression_type
            if self._package is not None
            else self._compression
        )
        if compression == "tar_gz":
            if self._archive_path is not None:
                return tarfile.open(self._archive_path, mode="r:gz")
            return tarfile.open(fileobj=io.BytesIO(self._archive), mode="r:gz")
        if self._archive_path is not None:
            return zipfile.ZipFile(self._archive_path, "r")
        return zipfile.ZipFile(io.BytesIO(self._archive), "r")

    def _read_metadata(self) -> list[InvoiceMetadata] | None:
        if self._is_empty():
            return (
                []
                if self._package is not None and self._package.invoice_count == 0
                else None
            )
        with self._open() as archive:
            for filename, is_directory, info in _archive_entries(archive):
                if is_directory or PurePosixPath(filename).name != METADATA_FILE_NAME:
                    continue
                try:
                    payload = cast(
                        dict[str, list[object]], json.loads(_read_entry(archive, info))
                    )
                    return [
                        from_spec(spec.InvoiceMetadata.model_validate(item))
                        for item in payload["invoices"]
                    ]
                except (ValueError, KeyError, TypeError) as exc:
                    raise exceptions.KSeFResponseValidationError(
                        f"Export package has an invalid {METADATA_FILE_NAME}: {exc}"
                    ) from exc
        return None


def _reject_unsafe_entry(name: str) -> None:
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or _DRIVE_RE.match(name)
        or ".." in PurePosixPath(name).parts
    ):
        raise ValueError(f"Unsafe archive entry path: {name!r}")


def _archive_entries(
    archive: zipfile.ZipFile | tarfile.TarFile,
) -> Iterator[tuple[str, bool, zipfile.ZipInfo | tarfile.TarInfo]]:
    if isinstance(archive, zipfile.ZipFile):
        for info in archive.infolist():
            file_type = stat.S_IFMT(info.external_attr >> 16)
            if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(f"Unsafe archive entry type: {info.filename!r}")
            yield info.filename, info.is_dir(), info
    else:
        for member in archive:
            if not member.isfile() and not member.isdir():
                raise ValueError(f"Unsafe archive entry type: {member.name!r}")
            yield member.name, member.isdir(), member


def _read_entry(
    archive: zipfile.ZipFile | tarfile.TarFile,
    entry: zipfile.ZipInfo | tarfile.TarInfo,
) -> bytes:
    if isinstance(archive, zipfile.ZipFile) and isinstance(entry, zipfile.ZipInfo):
        return archive.read(entry)
    if isinstance(archive, tarfile.TarFile) and isinstance(entry, tarfile.TarInfo):
        stream = archive.extractfile(entry)
        if stream is None:
            raise ValueError(f"Archive entry is not a file: {entry.name!r}")
        with stream:
            return stream.read()
    raise TypeError("Archive entry does not match its archive type")
