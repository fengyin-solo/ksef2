"""Compression choices accepted by invoice export and batch payloads."""

from enum import StrEnum
from typing import Literal

from ksef2._domain.models._enum import coerce_enum

type CompressionType = Literal["zip", "tar_gz"]
type CompressionTypeSpecValue = Literal["Zip", "TarGz"]


class CompressionTypeEnum(StrEnum):
    """Runtime enum for KSeF compression values."""

    ZIP = "Zip"
    TAR_GZ = "TarGz"


type CompressionTypeInput = CompressionType | CompressionTypeEnum | str


_COMPRESSION_TYPE_TO_SPEC: dict[CompressionType, CompressionTypeSpecValue] = {
    "zip": "Zip",
    "tar_gz": "TarGz",
}
_COMPRESSION_TYPE_FROM_SPEC: dict[CompressionTypeSpecValue, CompressionType] = {
    value: key for key, value in _COMPRESSION_TYPE_TO_SPEC.items()
}


def normalize_compression_type(value: object) -> CompressionType:
    """Normalize SDK or OpenAPI compression values to SDK literals.

    Args:
        value: SDK literal, OpenAPI enum value, or enum member.

    Returns:
        Normalized SDK compression literal.

    Raises:
        KSeFArgumentError: If ``value`` is not a supported compression type.
    """
    if isinstance(value, str) and value.strip().casefold() in {"zip", "tar_gz"}:
        return value.strip().casefold()  # pyright: ignore[reportReturnType]
    member = coerce_enum(CompressionTypeEnum, value)
    return _COMPRESSION_TYPE_FROM_SPEC[member.value]


def compression_type_to_spec(
    value: CompressionTypeInput,
) -> CompressionTypeSpecValue:
    """Convert a compression value to the OpenAPI representation."""
    return _COMPRESSION_TYPE_TO_SPEC[normalize_compression_type(value)]
