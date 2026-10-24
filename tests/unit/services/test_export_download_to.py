"""Integrity and cleanup behavior for disk-backed export downloads."""

import asyncio
import base64
import os
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ksef2._core.crypto import encrypt_invoice
from ksef2._core.exceptions import (
    KSeFArgumentError,
    KSeFEncryptionError,
    KSeFValidationError,
)
from ksef2._domain.models.invoices import (
    ExportHandle,
    ExportResumeState,
    InvoicePackage,
    PackagePart,
)
from ksef2._services.async_invoices import AsyncInvoicesService
from ksef2._services.async_invoices import AsyncExportJob
from ksef2._services.invoices import ExportJob, InvoicesService

requires_unchecked_types = pytest.mark.skipif(
    bool(os.environ.get("KSEF2_RUNTIME_CHECKS")),
    reason="beartype rejects the out-of-contract value before the guard runs",
)


KEY, IV = b"k" * 32, b"i" * 16


def _digest(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def _part(ordinal: int, plaintext: bytes, ciphertext: bytes) -> dict[str, object]:
    return {
        "ordinal_number": ordinal,
        "part_name": f"part-{ordinal}.zip.aes",
        "method": "GET",
        "url": "https://storage.invalid/signed-capability",
        "part_size": len(plaintext),
        "part_hash": _digest(plaintext),
        "encrypted_part_size": len(ciphertext),
        "encrypted_part_hash": _digest(ciphertext),
        "expiration_date": datetime(2030, 1, 1, tzinfo=UTC),
    }


def _package(parts: list[dict[str, object]]) -> InvoicePackage:
    return InvoicePackage.model_construct(
        compression_type="zip",
        parts=[PackagePart.model_validate(part) for part in parts],
    )


def _export() -> ExportHandle:
    return ExportHandle.model_construct(
        reference_number="export-ref", aes_key=KEY, iv=IV
    )


def _download(
    is_async: bool, package: InvoicePackage, side_effect: list[object], target: Path
) -> None:
    if is_async:
        async_service = object.__new__(AsyncInvoicesService)
        async_service._external_transfers = Mock()
        async_service._external_transfers.download_part = AsyncMock(
            side_effect=side_effect
        )
        _ = asyncio.run(
            async_service._download_package_to(
                package=package, export=_export(), path=target
            )
        )
        return
    service = object.__new__(InvoicesService)
    service._external_transfers = Mock()
    service._external_transfers.download_part.side_effect = side_effect
    _ = service._download_package_to(package=package, export=_export(), path=target)


def _assert_no_output(target: Path) -> None:
    assert not target.exists()
    assert not target.with_name(target.name + ".partial").exists()


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
def test_disk_download_joins_parts_in_ordinal_order(
    is_async: bool, tmp_path: Path
) -> None:
    # Large enough to cross the 64 KiB decryption chunk boundary.
    chunks = [bytes([n]) * (70 * 1024 + n) for n in range(3)]
    encrypted = [encrypt_invoice(chunk, key=KEY, iv=IV) for chunk in chunks]
    # Parts listed out of order; download must follow ordinal numbers.
    package = _package([_part(n + 1, chunks[n], encrypted[n]) for n in (2, 0, 1)])
    target = tmp_path / "nested" / "export.zip"

    _download(is_async, package, list(encrypted), target)

    assert target.read_bytes() == b"".join(chunks)
    assert not target.with_name(target.name + ".partial").exists()


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    "mismatch", ["plain_hash", "plain_size", "encrypted_hash", "encrypted_size"]
)
def test_disk_download_rejects_part_integrity_mismatch_and_removes_partial(
    mismatch: str, is_async: bool, tmp_path: Path
) -> None:
    plaintext = b"archive part bytes"
    ciphertext = encrypt_invoice(plaintext, key=KEY, iv=IV)
    first_part = _part(1, plaintext, ciphertext)
    second_part = _part(2, plaintext, ciphertext)
    if mismatch == "plain_hash":
        second_part["part_hash"] = _digest(b"wrong")
    elif mismatch == "plain_size":
        second_part["part_size"] = len(plaintext) + 1
    elif mismatch == "encrypted_hash":
        second_part["encrypted_part_hash"] = _digest(b"wrong")
    else:
        second_part["encrypted_part_size"] = len(ciphertext) + 1
    target = tmp_path / "export.zip"

    with pytest.raises(KSeFValidationError):
        _download(
            is_async,
            _package([first_part, second_part]),
            [ciphertext, ciphertext],
            target,
        )

    _assert_no_output(target)


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
def test_disk_download_rejects_invalid_padding_and_removes_partial(
    is_async: bool, tmp_path: Path
) -> None:
    # Deterministic: plaintext block ending in 0x00 is never valid PKCS#7.
    encryptor = Cipher(algorithms.AES(KEY), modes.CBC(IV)).encryptor()
    ciphertext = encryptor.update(b"\x00" * 16) + encryptor.finalize()
    part = _part(1, b"", ciphertext)
    target = tmp_path / "export.zip"

    with pytest.raises(KSeFEncryptionError):
        _download(is_async, _package([part]), [ciphertext], target)

    _assert_no_output(target)


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
def test_interrupted_download_removes_partial_and_keeps_existing_target(
    is_async: bool, tmp_path: Path
) -> None:
    plaintext = b"archive part bytes"
    ciphertext = encrypt_invoice(plaintext, key=KEY, iv=IV)
    package = _package(
        [_part(1, plaintext, ciphertext), _part(2, plaintext, ciphertext)]
    )
    target = tmp_path / "export.zip"
    target.write_bytes(b"previous archive")

    with pytest.raises(ConnectionError):
        _download(is_async, package, [ciphertext, ConnectionError("reset")], target)

    assert target.read_bytes() == b"previous archive"
    assert not target.with_name(target.name + ".partial").exists()


@requires_unchecked_types
@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
def test_job_download_rejects_string_paths_before_polling(is_async: bool) -> None:
    get_status = Mock()
    download_to = Mock()
    state = ExportResumeState.model_construct(
        reference_number="export-ref", aes_key=KEY, iv=IV
    )
    job_class = AsyncExportJob if is_async else ExportJob
    job = job_class(
        state,
        get_status=get_status,
        download_parts=Mock(),
        download_to=download_to,
    )

    with pytest.raises(KSeFArgumentError):
        if is_async:
            asyncio.run(job.download("export.zip"))  # pyright: ignore[reportArgumentType]
        else:
            _ = job.download("export.zip")  # pyright: ignore[reportArgumentType]

    get_status.assert_not_called()
    download_to.assert_not_called()
