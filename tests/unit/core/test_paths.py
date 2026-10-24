"""``require_path``: only ``os.PathLike`` values name files."""

import os
from pathlib import Path, PurePosixPath

import pytest

from ksef2._core.exceptions import KSeFArgumentError
from ksef2._core.paths import require_path


class _CustomPath:
    def __init__(self, value: str) -> None:
        self._value = value

    def __fspath__(self) -> str:
        return self._value


class _BytesPath:
    def __fspath__(self) -> bytes:
        return b"export.zip"


def test_path_is_returned_as_path() -> None:
    assert require_path(Path("export.zip")) == Path("export.zip")


def test_custom_pathlike_is_normalized_to_path() -> None:
    value = _CustomPath("exports/export.zip")
    assert isinstance(value, os.PathLike)

    result = require_path(value)

    assert type(result) is type(Path())
    assert result == Path("exports/export.zip")


def test_pure_path_is_accepted() -> None:
    assert require_path(PurePosixPath("export.zip")) == Path("export.zip")


@pytest.mark.parametrize("value", ["export.zip", b"export.zip", None, 1, _BytesPath()])
def test_non_path_values_are_rejected_with_a_path_hint(value: object) -> None:
    with pytest.raises(KSeFArgumentError, match=r"pass Path\(\.\.\.\)"):
        _ = require_path(value)


def test_error_names_the_argument() -> None:
    with pytest.raises(KSeFArgumentError, match="^destination must be a path"):
        _ = require_path("export.zip", name="destination")
