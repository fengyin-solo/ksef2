from pathlib import Path

from ksef2._core import exceptions
from ksef2._core.crypto import sha256_b64
from ksef2._domain.models.invoices import PackagePart


def verify_encrypted_part(encrypted_part: bytes, *, part: PackagePart) -> None:
    """Check downloaded ciphertext against the metadata KSeF reported for it.

    Args:
        encrypted_part: Bytes returned by the external storage download.
        part: Package part metadata carrying the expected encrypted size and hash.

    Raises:
        KSeFEncryptionError: If the size or hash does not match ``part``.
    """
    _verify_part(
        data=encrypted_part,
        label="encrypted export package part",
        part=part,
        expected_size=part.encrypted_part_size,
        expected_hash=part.encrypted_part_hash,
    )


def verify_decrypted_part(decrypted_part: bytes, *, part: PackagePart) -> None:
    """Check decrypted bytes against the metadata KSeF reported for the part.

    Args:
        decrypted_part: Plaintext bytes obtained after decrypting the download.
        part: Package part metadata carrying the expected plaintext size and hash.

    Raises:
        KSeFEncryptionError: If the size or hash does not match ``part``.
    """
    _verify_part(
        data=decrypted_part,
        label="decrypted export package part",
        part=part,
        expected_size=part.part_size,
        expected_hash=part.part_hash,
    )


def _verify_part(
    *,
    data: bytes,
    label: str,
    part: PackagePart,
    expected_size: int,
    expected_hash: str,
) -> None:
    if len(data) != expected_size:
        raise exceptions.KSeFEncryptionError(
            f"Downloaded {label} has the wrong size: part "
            f"{part.ordinal_number} ({part.part_name!r}) reported "
            f"{expected_size} bytes but {len(data)} bytes were received."
        )
    if sha256_b64(data) != expected_hash:
        raise exceptions.KSeFEncryptionError(
            f"Downloaded {label} has the wrong hash: part "
            f"{part.ordinal_number} ({part.part_name!r}) reported "
            f"{expected_hash!r}."
        )


def safe_part_filename(part_name: str) -> str:
    """Return a sanitized local filename for an export package part.

    Raises:
        ValueError: If ``part_name`` is unsafe or cannot produce a local filename.
    """
    sanitized_part_name = Path(part_name.replace("\\", "/")).name
    output_filename = sanitized_part_name.removesuffix(".aes")
    if (
        "\x00" in output_filename
        or output_filename.startswith(".")
        or output_filename in {"", ".", ".."}
    ):
        raise ValueError(f"Invalid export package part name: {part_name!r}")
    return output_filename
