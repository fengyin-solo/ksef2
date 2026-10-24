import base64
import hashlib
from pathlib import Path
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ksef2._core.exceptions import (
    KSeFArgumentError,
    KSeFEncryptionError,
    KSeFValidationError,
)
from ksef2._domain.models.invoices import PackagePart


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


def require_path(value: object) -> Path:
    """Validate a path-only API input without accepting string filenames."""
    if not isinstance(value, Path):
        raise KSeFArgumentError("path must be a pathlib.Path.")
    return value


def decrypt_verified_part(
    ciphertext: bytes,
    *,
    part: PackagePart,
    key: bytes,
    iv: bytes,
    output: BinaryIO,
) -> None:
    """Decrypt one already-downloaded part to a file and verify KSeF digests."""
    encrypted_hash = base64.b64encode(hashlib.sha256(ciphertext).digest()).decode()
    if (
        len(ciphertext) != part.encrypted_part_size
        or encrypted_hash != part.encrypted_part_hash
    ):
        raise KSeFValidationError(
            "Export package part encrypted size or hash mismatch."
        )
    if len(ciphertext) == 0 or len(ciphertext) % 16:
        raise KSeFEncryptionError("AES-CBC ciphertext has an invalid block length.")

    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    digest = hashlib.sha256()
    plaintext_size = 0
    pending = b""
    for offset in range(0, len(ciphertext), 64 * 1024):
        pending += decryptor.update(ciphertext[offset : offset + 64 * 1024])
        if len(pending) > 16:
            chunk, pending = pending[:-16], pending[-16:]
            _ = output.write(chunk)
            digest.update(chunk)
            plaintext_size += len(chunk)
    pending += decryptor.finalize()
    padding_size = pending[-1] if pending else 0
    if (
        padding_size < 1
        or padding_size > 16
        or pending[-padding_size:] != bytes([padding_size]) * padding_size
    ):
        raise KSeFEncryptionError("AES-CBC decryption failed: invalid PKCS#7 padding.")
    final_chunk = pending[:-padding_size]
    _ = output.write(final_chunk)
    digest.update(final_chunk)
    plaintext_size += len(final_chunk)
    plaintext_hash = base64.b64encode(digest.digest()).decode()
    if plaintext_size != part.part_size or plaintext_hash != part.part_hash:
        raise KSeFValidationError(
            "Export package part plaintext size or hash mismatch."
        )
