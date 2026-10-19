"""Locate bytes in bridge annotations and remove ambiguous string alternatives."""

import functools
import operator
import pathlib
import types
import typing
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, cast

from pydantic import AliasChoices, AliasPath, BaseModel, SecretBytes

from ksef2.bridge._errors import ManifestError
from ksef2.bridge._introspect import (
    alias_value,
    attribute_of,
    type_args,
    type_origin,
)


@dataclass(frozen=True)
class BytesLeaf:
    """Mark a position that carries bytes as standard Base64."""


BYTES: Final = BytesLeaf()


@dataclass(frozen=True)
class FieldsPlan:
    """Locate bytes in model fields, including explicitly excluded fields."""

    fields: Mapping[str, "Plan"]
    """Only fields whose annotations contain bytes, keyed by Python field name."""

    model: type[BaseModel] | None = field(default=None, compare=False, repr=False)
    """Model supplying validation and serialization aliases, when discovered."""


@dataclass(frozen=True)
class ItemsPlan:
    """Locate bytes in the items of a collection."""

    item: "Plan"
    """Plan shared by every item."""


@dataclass(frozen=True)
class ValuesPlan:
    """Locate bytes in the values of a mapping."""

    value: "Plan"
    """Plan shared by every value; keys never carry bytes."""


@dataclass(frozen=True)
class UnionPlan:
    """Locate bytes in alternatives distinguishable by their JSON shape."""

    alternatives: tuple["Plan", ...]
    """Plans selected by string, array or object shape."""


Plan = BytesLeaf | FieldsPlan | ItemsPlan | ValuesPlan | UnionPlan

_ITEMS: Final[frozenset[object]] = frozenset(
    {list, tuple, set, frozenset, Sequence, Iterable, Collection}
)
_VALUES: Final[frozenset[object]] = frozenset({dict, Mapping})
_UNION: Final = cast(object, typing.Union)  # pyright: ignore[reportDeprecated]


def bytes_plan(annotation: object) -> Plan | None:
    """Return where bytes sit inside a type, or ``None`` when it holds none.

    Args:
        annotation: Model, scalar or container annotation to inspect.

    Returns:
        A plan for every bytes position reachable without revisiting a model.

    Raises:
        ManifestError: Bytes-bearing union alternatives share a JSON shape.
    """
    try:
        _ = hash(annotation)
    except TypeError:
        return _plan(annotation, set())
    return _cached_plan(annotation)


@functools.cache
def _cached_plan(annotation: object) -> Plan | None:
    """Cache complete plans without caching truncated recursive branches."""
    return _plan(annotation, set())


def _plan(annotation: object, active: set[object]) -> Plan | None:
    """Walk an annotation, stopping at recursive model or alias references."""
    if annotation is bytes or annotation is bytearray or annotation is SecretBytes:
        return BYTES
    if isinstance(annotation, typing.TypeVar):
        return None
    if isinstance(annotation, typing.TypeAliasType):
        if annotation in active:
            return None
        return _plan(alias_value(annotation), active | {annotation})
    origin = type_origin(annotation)
    args = type_args(annotation)
    if origin is typing.Annotated:
        return _plan(args[0], active)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in active:
            return None
        fields: dict[str, Plan] = {}
        for name, field in annotation.model_fields.items():
            plan = _plan(cast("object", field.annotation), active | {annotation})
            if plan is not None:
                fields[name] = plan
        return FieldsPlan(fields, annotation) if fields else None
    if origin is types.UnionType or origin is _UNION:
        alternatives: list[Plan] = []
        for arg in args:
            plan = _plan(arg, active)
            if isinstance(plan, UnionPlan):
                alternatives.extend(plan.alternatives)
            elif plan is not None:
                alternatives.append(plan)
        plans = tuple(alternatives)
        if not plans:
            return None
        if len(plans) == 1:
            return plans[0]
        shapes = tuple(_shape(plan) for plan in plans)
        if len(set(shapes)) != len(shapes):
            raise ManifestError(
                f"bytes alternatives in {annotation!r} share a JSON shape"
            )
        return UnionPlan(plans)
    if origin in _ITEMS and args:
        plan = _plan(args[0], active)
        if origin is tuple and len(args) > 1 and args[1] is not Ellipsis:
            if any(_plan(arg, active) != plan for arg in args[1:]):
                return None
        return ItemsPlan(plan) if plan is not None else None
    if origin in _VALUES and len(args) == 2:
        plan = _plan(args[1], active)
        return ValuesPlan(plan) if plan is not None else None
    return None


def field_keys(
    model: type[BaseModel] | None, name: str, *, serialization: bool = False
) -> tuple[str, ...]:
    """Return a field's JSON keys, with the schema or serialization alias first."""
    if model is None:
        return (name,)
    field = model.model_fields[name]
    if serialization:
        return tuple(
            dict.fromkeys((field.serialization_alias or field.alias or name, name))
        )
    alias = field.validation_alias
    if isinstance(alias, str):
        aliases = [alias]
    elif isinstance(alias, AliasChoices):
        aliases = [
            path[0]
            for path in alias.convert_to_aliases()
            if len(path) == 1 and isinstance(path[0], str)
        ]
    elif isinstance(alias, AliasPath):
        path = alias.convert_to_aliases()
        aliases = [path[0]] if len(path) == 1 and isinstance(path[0], str) else []
    else:
        aliases = [field.alias or name]
    return tuple(dict.fromkeys((*aliases, name)))


def _shape(plan: Plan) -> str:
    """Name the JSON shape used to choose a union alternative."""
    if isinstance(plan, BytesLeaf):
        return "string"
    if isinstance(plan, ItemsPlan):
        return "array"
    return "object"


def without_text_alternative(annotation: object) -> object:
    """Drop text and path alternatives from bytes unions at any depth.

    Args:
        annotation: The declared annotation, possibly containing containers.

    Returns:
        The rebuilt annotation, or the identical object when nothing changed.
    """
    origin = type_origin(annotation)
    args = type_args(annotation)
    if not args:
        return annotation
    if origin is typing.Annotated:
        underlying = without_text_alternative(args[0])
        if underlying is args[0]:
            return annotation
        return _rebuild_alias(typing.Annotated, (underlying, *args[1:]))
    changed = tuple(without_text_alternative(arg) for arg in args)
    is_union = origin is types.UnionType or origin is _UNION
    if is_union and any(arg is bytes or arg is bytearray for arg in changed):
        changed = tuple(arg for arg in changed if arg is not str and not _is_path(arg))
    if len(args) == len(changed) and all(
        old is new for old, new in zip(args, changed, strict=True)
    ):
        return annotation
    if is_union:
        return cast("object", functools.reduce(operator.or_, changed))
    return _rebuild_alias(origin, changed)


def _is_path(annotation: object) -> bool:
    """Say whether an annotation names a pathlib path class."""
    return isinstance(annotation, type) and issubclass(annotation, pathlib.PurePath)


def _rebuild_alias(origin: object, args: tuple[object, ...]) -> object:
    """Subscribe a generic origin with its changed arguments."""
    subscribe = attribute_of(origin, "__class_getitem__") or attribute_of(
        origin, "__getitem__"
    )
    return cast("Callable[[tuple[object, ...]], object]", subscribe)(args)
