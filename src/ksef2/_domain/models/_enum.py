"""Shared coercion for public enum inputs."""

from enum import Enum
from importlib import import_module
from typing import Callable, TypeVar, cast

EnumT = TypeVar("EnumT", bound=Enum)


def _valid_value(member: Enum) -> str:
    value = cast(object, member.value)
    if not isinstance(value, str) or value == member.name:
        return member.name
    return f"{member.name} ({value})"


def coerce_enum(enum_type: type[EnumT], value: object) -> EnumT:
    """Match an enum member, name, or string value without regard to case."""
    if isinstance(value, enum_type):
        return value

    if isinstance(value, str):
        normalized = value.strip().casefold()
        for member in enum_type:
            if (
                member.name.casefold() == normalized
                or str(cast(object, member.value)).casefold() == normalized
            ):
                return member

    valid_values = ", ".join(_valid_value(member) for member in enum_type)
    argument_error = cast(
        Callable[..., Exception],
        getattr(import_module("ksef2._core.exceptions"), "KSeFArgumentError"),
    )
    raise argument_error(
        f"Invalid {enum_type.__name__} value {value!r}. Valid values are: {valid_values}.",
        hint="Pass one of the listed enum names or values.",
    )
