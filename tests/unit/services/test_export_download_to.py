"""Integrity and cleanup behavior for disk-backed export downloads."""

import base64
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from ksef2._core.crypto import encrypt_invoice
from ksef2._core.exceptions import KSeFValidationError
from ksef2._domain.models.invoices import ExportHandle, InvoicePackage, PackagePart
from ksef2._services.invoices import InvoicesService


def _digest(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


@pytest.mark.parametrize(
    "mismatch", ["plain_hash", "plain_size", "encrypted_hash", "encrypted_size"]
)
def test_disk_download_rejects_part_integrity_mismatch_and_removes_partial(
    mismatch: str, tmp_path: Path
) -> None:
    plaintext = b"archive part bytes"
    key, iv = b"k" * 32, b"i" * 16
    ciphertext = encrypt_invoice(plaintext, key=key, iv=iv)
    part_values: dict[str, object] = {
        "ordinal_number": 1,
        "part_name": "part.zip.aes",
        "method": "GET",
        "url": "https://storage.invalid/signed-capability",
        "part_size": len(plaintext),
        "part_hash": _digest(plaintext),
        "encrypted_part_size": len(ciphertext),
        "encrypted_part_hash": _digest(ciphertext),
        "expiration_date": datetime(2030, 1, 1, tzinfo=UTC),
    }
    first_part = PackagePart.model_validate(part_values)
    if mismatch == "plain_hash":
        part_values["part_hash"] = _digest(b"wrong")
    elif mismatch == "plain_size":
        part_values["part_size"] = len(plaintext) + 1
    elif mismatch == "encrypted_hash":
        part_values["encrypted_part_hash"] = _digest(b"wrong")
    else:
        part_values["encrypted_part_size"] = len(ciphertext) + 1
    part_values["ordinal_number"] = 2
    part = PackagePart.model_validate(part_values)
    package = InvoicePackage.model_construct(
        compression_type="zip", parts=[first_part, part]
    )
    export = ExportHandle.model_construct(
        reference_number="export-ref", aes_key=key, iv=iv
    )
    service = object.__new__(InvoicesService)
    service._external_transfers = Mock()
    service._external_transfers.download_part.side_effect = [ciphertext, ciphertext]
    target = tmp_path / "export.zip"

    with pytest.raises(KSeFValidationError):
        service._download_package_to(package=package, export=export, path=target)

    assert not target.exists()
    assert not target.with_name(target.name + ".partial").exists()
