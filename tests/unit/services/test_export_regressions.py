"""Public export regressions shared by the sync and async services."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from ksef2._clients.exported_invoices import ExportedInvoices
from ksef2._core.crypto import encrypt_invoice, sha256_b64
from ksef2._core.exceptions import KSeFValidationError
from ksef2._domain.models.invoices import (
    ExportHandle,
    ExportResumeState,
    InvoicePackage,
    InvoicesFilter,
)
from tests.unit.support.flavors import Flavor
from tests.unit.support.helpers import legacy_api

KEY, IV = b"k" * 32, b"i" * 16


def _handle() -> ExportHandle:
    return ExportHandle(reference_number="export-ref", aes_key=KEY, iv=IV)


def _empty_package() -> dict[str, object]:
    return {"invoiceCount": 0, "size": 0, "parts": [], "isTruncated": False}


def _ready(flavor: Flavor, package: dict[str, object]) -> None:
    flavor.transport.enqueue(
        {"status": {"code": 200, "description": "Completed"}, "package": package}
    )


@legacy_api
@pytest.mark.parametrize(
    "method", ["wait_for_export_package", "export_and_download", "wait", "download"]
)
def test_empty_export_finishes_on_first_status_without_sleeping(
    flavor: Flavor, method: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = flavor.invoices_service()
    _ready(flavor, _empty_package())
    # A completed export must return even when there is no time left to retry.
    if method == "wait_for_export_package":
        result = flavor.run(
            service.wait_for_export_package(reference_number="export-ref", timeout=0.0)
        )
        assert isinstance(result, InvoicePackage)
        assert result.invoice_count == 0
        assert result.parts == []
    elif method == "export_and_download":
        schedule = (
            AsyncMock(return_value=_handle())
            if flavor.is_async
            else Mock(return_value=_handle())
        )
        monkeypatch.setattr(service, "_schedule_export", schedule)
        result = flavor.run(
            service.export_and_download(
                filters=InvoicesFilter.for_seller(
                    date_from="2026-01-01T00:00:00Z", date_to="2026-01-02T00:00:00Z"
                ),
                timeout=0.0,
            )
        )
        assert result == []
    else:
        job = flavor.run(service.export(state=ExportResumeState.from_handle(_handle())))
        if method == "download":
            target = tmp_path / "empty.zip"
            result = flavor.run(job.download(target, timeout=0.0))
            assert target.read_bytes() == b""
        else:
            result = flavor.run(job.wait(timeout=0.0))
        assert isinstance(result, ExportedInvoices)
        assert result.archive == b""
        assert result.metadata == []
        assert list(result.invoices()) == []
    assert len(flavor.transport.calls) == 1
    assert flavor.transport.responses == []


@pytest.mark.parametrize("destination", ["memory", "disk", "legacy"])
@pytest.mark.parametrize(
    "mismatch",
    ["part_size", "part_hash", "encrypted_part_hash", "encrypted_part_size", None],
)
@legacy_api
def test_export_download_verifies_each_part(
    flavor: Flavor, destination: str, mismatch: str | None, tmp_path: Path
) -> None:
    plaintext = b"deterministic archive part"
    ciphertext = encrypt_invoice(plaintext, key=KEY, iv=IV)
    part: dict[str, object] = {
        "ordinalNumber": 1,
        "partName": "part-1.zip.aes",
        "method": "GET",
        "url": "https://storage.invalid/part-1",
        "partSize": len(plaintext),
        "partHash": sha256_b64(plaintext),
        "encryptedPartSize": len(ciphertext),
        "encryptedPartHash": sha256_b64(ciphertext),
        "expirationDate": datetime(2030, 1, 1, tzinfo=UTC).isoformat(),
    }
    if mismatch == "part_size":
        part["partSize"] = len(plaintext) + 1
    elif mismatch == "part_hash":
        part["partHash"] = sha256_b64(b"wrong plaintext")
    elif mismatch == "encrypted_part_hash":
        part["encryptedPartHash"] = sha256_b64(b"wrong ciphertext")
    elif mismatch == "encrypted_part_size":
        part["encryptedPartSize"] = len(ciphertext) + 1
    package: dict[str, object] = {
        "invoiceCount": 1,
        "size": len(plaintext),
        "parts": [part],
        "isTruncated": False,
    }
    service = flavor.invoices_service()
    _ready(flavor, package)
    flavor.transport.enqueue(content=ciphertext)
    job = flavor.run(service.export(state=ExportResumeState.from_handle(_handle())))
    target = tmp_path / "export.zip"
    target.write_bytes(b"previous archive")

    def download() -> bytes:
        if destination == "legacy":
            ready_package = flavor.run(
                service.wait_for_export_package(
                    reference_number="export-ref", timeout=0.0
                )
            )
            return b"".join(
                flavor.run(
                    service.fetch_package_bytes(package=ready_package, export=_handle())
                )
            )
        result = flavor.run(
            job.download(target, timeout=0.0)
            if destination == "disk"
            else job.wait(timeout=0.0)
        )
        assert isinstance(result, ExportedInvoices)
        return result.archive

    if mismatch is None:
        assert download() == plaintext
    else:
        label = "encrypted" if mismatch.startswith("encrypted") else "plaintext"
        with pytest.raises(
            KSeFValidationError,
            match=f"Export package part {label} size or hash mismatch",
        ):
            download()
        assert target.read_bytes() == b"previous archive"
        assert sorted(item.name for item in tmp_path.iterdir()) == ["export.zip"]
    assert len(flavor.transport.calls) == 2
    assert flavor.transport.responses == []


def _part_payload(
    ordinal_number: int, plaintext: bytes
) -> tuple[dict[str, object], bytes]:
    ciphertext = encrypt_invoice(plaintext, key=KEY, iv=IV)
    return (
        {
            "ordinalNumber": ordinal_number,
            "partName": f"part-{ordinal_number}.zip.aes",
            "method": "GET",
            "url": f"https://storage.invalid/part-{ordinal_number}",
            "partSize": len(plaintext),
            "partHash": sha256_b64(plaintext),
            "encryptedPartSize": len(ciphertext),
            "encryptedPartHash": sha256_b64(ciphertext),
            "expirationDate": datetime(2030, 1, 1, tzinfo=UTC).isoformat(),
        },
        ciphertext,
    )


def _malformed_package(kind: str) -> dict[str, object]:
    part_one, _ = _part_payload(1, b"first archive part bytes!!")
    part_two, _ = _part_payload(2, b"second archive part bytes!")
    if kind == "empty":
        parts: list[dict[str, object]] = []
        invoice_count = 1
    elif kind == "duplicate":
        parts = [part_one, dict(part_one)]
        invoice_count = 2
    elif kind == "gap":
        parts = [part_one, {**part_two, "ordinalNumber": 3}]
        invoice_count = 2
    else:  # starts_at_two
        parts = [{**part_one, "ordinalNumber": 2}]
        invoice_count = 1
    return {
        "invoiceCount": invoice_count,
        "size": 99,
        "parts": parts,
        "isTruncated": False,
    }


@legacy_api
@pytest.mark.parametrize(
    "method", ["wait_for_export_package", "export_and_download", "wait", "download"]
)
@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("empty", "at least one part"),
        ("duplicate", "must be unique"),
        ("gap", "consecutive starting at 1"),
        ("starts_at_two", "consecutive starting at 1"),
    ],
)
def test_invalid_package_manifest_fails_before_any_part_download(
    flavor: Flavor,
    method: str,
    kind: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = flavor.invoices_service()
    _ready(flavor, _malformed_package(kind))
    target = tmp_path / "export.zip"

    with pytest.raises(KSeFValidationError, match=message):
        if method == "wait_for_export_package":
            flavor.run(
                service.wait_for_export_package(
                    reference_number="export-ref", timeout=0.0
                )
            )
        elif method == "export_and_download":
            schedule = (
                AsyncMock(return_value=_handle())
                if flavor.is_async
                else Mock(return_value=_handle())
            )
            monkeypatch.setattr(service, "_schedule_export", schedule)
            flavor.run(
                service.export_and_download(
                    filters=InvoicesFilter.for_seller(
                        date_from="2026-01-01T00:00:00Z",
                        date_to="2026-01-02T00:00:00Z",
                    ),
                    timeout=0.0,
                )
            )
        else:
            job = flavor.run(
                service.export(state=ExportResumeState.from_handle(_handle()))
            )
            if method == "download":
                flavor.run(job.download(target, timeout=0.0))
            else:
                flavor.run(job.wait(timeout=0.0))

    if method == "download":
        assert not target.exists()
    # The status response is the only request; no presigned part URL was fetched.
    assert len(flavor.transport.calls) == 1
    assert "storage.invalid" not in flavor.transport.calls[0].path
    assert flavor.transport.responses == []


@legacy_api
@pytest.mark.parametrize("destination", ["memory", "disk", "legacy"])
def test_out_of_order_manifest_downloads_parts_in_ordinal_order(
    flavor: Flavor, destination: str, tmp_path: Path
) -> None:
    first = b"first archive part bytes!!"
    second = b"second archive part bytes!"
    part_one, cipher_one = _part_payload(1, first)
    part_two, cipher_two = _part_payload(2, second)
    package: dict[str, object] = {
        "invoiceCount": 2,
        "size": len(first) + len(second),
        # The server listed the parts out of order; the manifest is still valid.
        "parts": [part_two, part_one],
        "isTruncated": False,
    }
    service = flavor.invoices_service()
    _ready(flavor, package)
    # Downloads follow ordinal numbers, so part 1 must be requested before part 2.
    flavor.transport.enqueue(content=cipher_one)
    flavor.transport.enqueue(content=cipher_two)

    if destination == "legacy":
        ready_package = flavor.run(
            service.wait_for_export_package(reference_number="export-ref", timeout=0.0)
        )
        archive = b"".join(
            flavor.run(
                service.fetch_package_bytes(package=ready_package, export=_handle())
            )
        )
    else:
        job = flavor.run(service.export(state=ExportResumeState.from_handle(_handle())))
        result = flavor.run(
            job.download(tmp_path / "export.zip", timeout=0.0)
            if destination == "disk"
            else job.wait(timeout=0.0)
        )
        assert isinstance(result, ExportedInvoices)
        archive = result.archive
        if destination == "disk":
            assert (tmp_path / "export.zip").read_bytes() == first + second

    assert archive == first + second
    assert [call.path for call in flavor.transport.calls[1:]] == [
        "https://storage.invalid/part-1",
        "https://storage.invalid/part-2",
    ]
    assert flavor.transport.responses == []
