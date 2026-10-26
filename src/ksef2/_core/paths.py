"""Validation of file paths and filename-like content inputs."""

import os
import re
from pathlib import Path
from typing import cast

from ksef2._core.exceptions import KSeFArgumentError

_HINT = "Wrap the file name in pathlib.Path; str and bytes are treated as content."


def require_path(value: object, *, name: str = "path") -> Path:
    """Return ``value`` as a ``Path`` when it names a file location.

    The SDK treats ``str`` and ``bytes`` as content, never as file names, so
    only ``os.PathLike`` objects are accepted here.

    Args:
        value: The caller's argument.
        name: Argument name used in the error message.

    Returns:
        ``value`` normalized with ``Path(value)``.

    Raises:
        KSeFArgumentError: If ``value`` is not an ``os.PathLike`` object that
            resolves to a text path.
    """
    if isinstance(value, (str, bytes)):
        raise KSeFArgumentError(
            f"{name} must be a path, not {type(value).__name__}; pass Path(...).",
            hint=_HINT,
        )
    if not isinstance(value, os.PathLike):
        raise KSeFArgumentError(
            f"{name} must be an os.PathLike object, got {type(value).__name__}; "
            + "pass Path(...).",
            hint=_HINT,
        )
    try:
        # os.PathLike is not generic at runtime; a bytes path raises TypeError here.
        return Path(cast("os.PathLike[str]", value))
    except TypeError as exc:
        raise KSeFArgumentError(
            f"{name} must resolve to a text path; pass Path(...).",
            hint=_HINT,
        ) from exc


def reject_path_like_content(
    value: str, *, content_type: str, missing_file: bool = False
) -> None:
    """Reject short filename-like text without disclosing any input content.

    PEM headers, XML markup, multiline text and long content bypass the hint.
    File existence and legacy string-path handling remain the caller's concern.
    """
    if (
        len(value) > 255
        or "\n" in value
        or "\r" in value
        or "-----BEGIN" in value
        or "<" in value
    ):
        return
    value = value.strip()
    if not value or not (
        "/" in value or "\\" in value or re.search(r"\.[a-zA-Z0-9]{1,10}$", value)
    ):
        return
    reason = " but no such file exists" if missing_file else ""
    raise KSeFArgumentError(
        f"Input looks like a file path{reason}; str and bytes are treated as content.",
        hint=(
            f"Pass Path(...) to read a file, or pass the {content_type} content."
            if content_type == "PEM or PKCS#12"
            else "Read the file with Path(...).read_bytes(), or pass the XML content."
        ),
    )
