import io
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import final
from collections.abc import Iterator

from ksef2._core import exceptions

_KNOWN_NON_INVOICE_FILES = frozenset(
    {
        "manifest.xml",
        "metadata.xml",
        "signature.xml",
    }
)

MAX_ENTRY_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
"""Largest decompressed size this SDK takes from a single archive entry.

KSeF caps an invoice at 10 MB, so this leaves real packages a wide margin and
only refuses entries built to exhaust the caller's memory or disk by inflating a
few archived kilobytes into gigabytes.
"""

_READ_CHUNK_SIZE = 64 * 1024


def read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Read one archive entry into memory, refusing to pass the limit.

    Args:
        archive: Archive the entry belongs to.
        info: Entry to read.

    Returns:
        The decompressed entry.

    Raises:
        KSeFValidationError: If the entry is larger than
            ``MAX_ENTRY_UNCOMPRESSED_BYTES``, either as its header declares it or
            as the bytes arrive.
    """
    check_entry_size(info)
    chunks: list[bytes] = []
    decompressed = 0
    with archive.open(info, "r") as entry:
        while chunk := entry.read(_READ_CHUNK_SIZE):
            decompressed += len(chunk)
            if decompressed > MAX_ENTRY_UNCOMPRESSED_BYTES:
                raise _entry_too_large(info)
            chunks.append(chunk)
    return b"".join(chunks)


def write_entry(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: Path
) -> None:
    """Stream one archive entry to ``destination``, refusing to pass the limit.

    No partial file is left behind when the entry is refused or the write fails.

    Args:
        archive: Archive the entry belongs to.
        info: Entry to write.
        destination: File to write the decompressed entry to.

    Raises:
        KSeFValidationError: If the entry is larger than
            ``MAX_ENTRY_UNCOMPRESSED_BYTES``, either as its header declares it or
            as the bytes arrive.
        OSError: If ``destination`` cannot be written.
    """
    check_entry_size(info)
    decompressed = 0
    try:
        with archive.open(info, "r") as entry, destination.open("wb") as target:
            while chunk := entry.read(_READ_CHUNK_SIZE):
                decompressed += len(chunk)
                if decompressed > MAX_ENTRY_UNCOMPRESSED_BYTES:
                    raise _entry_too_large(info)
                _ = target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def check_entry_size(info: zipfile.ZipInfo) -> None:
    """Refuse an entry whose header already declares more than the limit.

    Args:
        info: Entry to check.

    Raises:
        KSeFValidationError: If the declared size exceeds the limit. Checking the
            decompressed bytes as they come is what catches an entry that lies.
    """
    if info.file_size > MAX_ENTRY_UNCOMPRESSED_BYTES:
        raise _entry_too_large(info)


def _entry_too_large(info: zipfile.ZipInfo) -> exceptions.KSeFValidationError:
    return exceptions.KSeFValidationError(
        f"Archive entry {info.filename!r} decompresses to more than "
        f"{MAX_ENTRY_UNCOMPRESSED_BYTES} bytes.",
        hint=(
            "The package holds an entry bigger than the SDK extracts. Extract a "
            "package you trust with an archive tool instead."
        ),
        entry=info.filename,
        max_uncompressed_bytes=MAX_ENTRY_UNCOMPRESSED_BYTES,
    )


@dataclass(frozen=True, slots=True)
class PackageInvoice:
    name: str
    xml: bytes


@final
class PackageReader:
    def __init__(self, zip_parts: list[bytes] | bytes) -> None:
        if isinstance(zip_parts, bytes):
            zip_parts = [zip_parts]
        self._parts = zip_parts

    def __iter__(self) -> Iterator[PackageInvoice]:
        return self.invoices()

    def invoices(self) -> Iterator[PackageInvoice]:
        """Iterate over the invoices in the package.

        Yields:
            Each invoice entry with its XML.

        Raises:
            KSeFValidationError: If an entry decompresses past the 64 MiB entry
                limit.
        """
        for part in self._parts:
            with zipfile.ZipFile(io.BytesIO(part), "r") as zf:
                for info in zf.infolist():
                    if not info.filename.lower().endswith(".xml"):
                        continue
                    if (
                        PurePosixPath(info.filename).name.lower()
                        in _KNOWN_NON_INVOICE_FILES
                    ):
                        continue
                    yield PackageInvoice(name=info.filename, xml=read_entry(zf, info))
