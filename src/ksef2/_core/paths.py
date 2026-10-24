"""Validation of path-only SDK inputs."""

import os
from pathlib import Path
from typing import cast

from ksef2._core.exceptions import KSeFArgumentError


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
            f"{name} must be a path, not {type(value).__name__}; pass Path(...)."
        )
    if not isinstance(value, os.PathLike):
        raise KSeFArgumentError(
            f"{name} must be an os.PathLike object, got {type(value).__name__}; "
            + "pass Path(...)."
        )
    try:
        # os.PathLike is not generic at runtime; a bytes path raises TypeError here.
        return Path(cast("os.PathLike[str]", value))
    except TypeError as exc:
        raise KSeFArgumentError(
            f"{name} must resolve to a text path; pass Path(...)."
        ) from exc
