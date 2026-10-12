from io import BytesIO
from zipfile import ZipFile

import pytest

from ksef2._core.crypto import decrypt_aes_cbc
from ksef2._core.exceptions import KSeFValidationError
from ksef2._domain.models.batch import BatchInvoice
from ksef2._services.batch_preparation import prepare_batch_package


def test_prepare_batch_package_caps_encrypted_part_size() -> None:
    for max_part_size in (16, 31, 32, 33, 100_000_000):
        batch = prepare_batch_package(
            invoices=[BatchInvoice(file_name="a.xml", content=b"<Invoice/>")],
            aes_key=bytes(32),
            iv=bytes(16),
            encrypted_key=b"placeholder",
            max_part_size=max_part_size,
        )

        assert batch.parts
        for part, declared in zip(batch.parts, batch.batch_file.parts, strict=True):
            assert part.file_size == declared.file_size == len(part.content)
            assert part.file_size <= max_part_size
        archive_bytes = b"".join(
            decrypt_aes_cbc(part.content, key=bytes(32), iv=bytes(16))
            for part in batch.parts
        )
        with ZipFile(BytesIO(archive_bytes)) as archive:
            assert archive.read("a.xml") == b"<Invoice/>"

    for max_part_size in (0, 1, 15, 100_000_001):
        with pytest.raises(KSeFValidationError, match="max_part_size"):
            _ = prepare_batch_package(
                invoices=[BatchInvoice(file_name="a.xml", content=b"<Invoice/>")],
                aes_key=bytes(32),
                iv=bytes(16),
                encrypted_key=b"placeholder",
                max_part_size=max_part_size,
            )
