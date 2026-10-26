import io
import os
import tempfile
from pathlib import Path

from ksef2._core.crypto import BytesWriter, decrypt_aes_cbc_to, sha256_b64
from ksef2._core.exceptions import KSeFValidationError
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


def create_partial_file(target: Path) -> tuple[Path, io.BufferedWriter]:
    """Exclusively create a uniquely named temporary file beside ``target``.

    The file is created with ``O_CREAT | O_EXCL``, so an existing file or symlink
    is never opened, truncated or followed. Writing beside ``target`` keeps the
    final ``os.replace()`` on one filesystem, which makes it atomic.

    Args:
        target: Destination the finished file will replace.

    Returns:
        The temporary path and a binary writer open on it.

    Raises:
        OSError: If the directory or the temporary file cannot be created.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".partial"
    )
    try:
        return Path(name), os.fdopen(descriptor, "wb")
    except BaseException:
        os.close(descriptor)
        Path(name).unlink(missing_ok=True)
        raise


def decrypt_verified_part(
    ciphertext: bytes,
    *,
    part: PackagePart,
    key: bytes,
    iv: bytes,
    output: BytesWriter,
) -> None:
    """Decrypt one downloaded export part to ``output`` and verify its digests.

    Args:
        ciphertext: Encrypted part bytes as downloaded.
        part: Package part metadata carrying the expected sizes and hashes.
        key: AES-256 key of the export.
        iv: Initialization vector of the export.
        output: Binary stream receiving the plaintext.

    Raises:
        KSeFValidationError: If the encrypted or plaintext size or hash differs.
        KSeFEncryptionError: If the part cannot be decrypted.
    """
    _verify_digest(
        "encrypted",
        len(ciphertext),
        sha256_b64(ciphertext),
        part.encrypted_part_size,
        part.encrypted_part_hash,
    )
    size, digest = decrypt_aes_cbc_to(ciphertext, key, iv, output)
    _verify_digest("plaintext", size, digest, part.part_size, part.part_hash)


def _verify_digest(
    label: str, size: int, digest: str, expected_size: int, expected_hash: str
) -> None:
    if size != expected_size or digest != expected_hash:
        raise KSeFValidationError(f"Export package part {label} size or hash mismatch.")
