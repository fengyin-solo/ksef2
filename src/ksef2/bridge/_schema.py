"""JSON Schema generation for the bridge manifest.

Every schema comes from pydantic, so the manifest describes the same types the
SDK validates at runtime. One pydantic generation pass covers the whole public
sync API: each operation's parameters and each requested value are placed in a
wrapper model, all wrappers are generated together, and the shared ``$defs``
registry pydantic builds is reused as the manifest's own. Named pydantic models
and named ``Literal`` aliases therefore appear once each in ``$defs`` and are
referenced by ``$ref`` everywhere else, which is what lets a binding generator
emit one named type per definition.
"""

import collections.abc
import datetime
import decimal
import enum
import inspect
import pathlib
import types
import typing
import uuid
import warnings
from dataclasses import dataclass
from typing import Protocol, Self, cast

from pydantic import BaseModel, ConfigDict, TypeAdapter, create_model
from pydantic_core import PydanticUndefined

from ksef2.bridge._data import (
    JsonObject,
    as_object,
    collect_refs,
    encode_bytes_schemas,
    require_json,
    without_titles,
)

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
"""Dialect of every schema the manifest emits."""

DEF_PREFIX = "#/$defs/"
"""Prefix of every pointer the manifest emits."""

TYPE_PARAMETER = "T"
"""Name of the ``$defs`` entry that stands in for an unresolved item type."""

_PARAMS_KIND = "params"
_VALUE_KIND = "value"
_WRAPPER = "_Bridge"
_TYPE_PARAMETER_DESCRIPTION = (
    "Item type of the collection. The operation that returned the pager fixes"
    " it and records it in its own ``item`` schema, so this placeholder stays"
    " deliberately unconstrained."
)

_SCALAR_TYPES: frozenset[object] = frozenset(
    {
        bool,
        bytes,
        datetime.date,
        datetime.datetime,
        datetime.time,
        datetime.timedelta,
        decimal.Decimal,
        float,
        int,
        pathlib.Path,
        str,
        type(None),
        uuid.UUID,
    }
)
"""Types pydantic describes with a JSON scalar, plus ``bytes`` and local paths."""

_SEQUENCE_ORIGINS: frozenset[object] = frozenset(
    {
        collections.abc.Collection,
        collections.abc.Iterable,
        collections.abc.MutableSequence,
        collections.abc.Sequence,
        collections.abc.Set,
        frozenset,
        list,
        set,
        tuple,
    }
)
"""Container origins the manifest describes as a JSON array."""

_MAPPING_ORIGINS: frozenset[object] = frozenset(
    {collections.abc.Mapping, collections.abc.MutableMapping, dict}
)
"""Container origins the manifest describes as a JSON object."""

_ITERATION_ORIGINS: frozenset[object] = frozenset(
    {
        collections.abc.AsyncIterable,
        collections.abc.AsyncIterator,
        collections.abc.Generator,
        collections.abc.Iterator,
    }
)
"""Python iteration protocols, which are behaviour rather than data."""


class _SupportsSubscript(Protocol):
    """Typing construct that accepts a tuple of type arguments."""

    def __getitem__(self, key: object) -> object: ...


class UndescribableType(Exception):
    """Raised for a Python type the manifest cannot turn into JSON Schema.

    Args:
        detail: What was found, phrased for the ``excluded`` reason of the member
            that carries it.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class T(BaseModel):
    """Stand-in for the item type of a generic pager.

    Pydantic publishes it in ``$defs`` under the name ``T`` and the builder
    rewrites that definition into an unconstrained schema, so ``Page[T]`` keeps
    the real page shape while its items stay open.
    """

    model_config = ConfigDict(extra="allow")


@dataclass(frozen=True)
class ParameterSchema:
    """One parameter of an operation, as generated from its signature.

    Attributes:
        name: Name the Python API uses.
        required: Whether a caller must pass it.
        schema: JSON Schema of the accepted values.
        default: JSON form of the default value, as pydantic serialized it.
        has_default: Whether the signature declares a default at all.
    """

    name: str
    required: bool
    schema: JsonObject
    default: object
    has_default: bool


@dataclass(frozen=True)
class Schemas:
    """Generated schemas, ready for the manifest to place in its sections.

    Attributes:
        definitions: Shared ``$defs`` registry with one entry per named type.
        values: Schema of each requested value, keyed by request key.
        parameters: Parameters of each requested signature, keyed by request key.
    """

    definitions: JsonObject
    values: dict[str, JsonObject]
    parameters: dict[str, list[ParameterSchema]]


def resolve_type(annotation: object, item: object | None = None) -> object:
    """Return ``annotation`` when the manifest can describe it as JSON Schema.

    Type variables are replaced by ``item``, the type that stands in for them.
    Named aliases are passed through as they are, so pydantic publishes them under
    their own name instead of inlining their members, which is what makes a
    ``Literal`` alias a named enum.

    Args:
        annotation: Annotation of a parameter or of a return value.
        item: Type that stands in for a type variable, or ``None`` when the
            annotated member declares none.

    Returns:
        The annotation, ready for pydantic.

    Raises:
        UndescribableType: If no JSON Schema describes the annotation.
    """
    if annotation is inspect.Parameter.empty:
        raise UndescribableType("a parameter without a type annotation")
    if annotation is Self:
        raise UndescribableType("the type of the receiving object")
    annotation = _close_type_arguments(annotation, item)
    if annotation is typing.Any or annotation is object:
        raise UndescribableType("a value typed as Any")
    if _is_scalar(annotation):
        return annotation
    if isinstance(annotation, typing.TypeAliasType):
        value = cast("object", annotation.__value__)
        _ = resolve_type(value, item=item)
        return annotation
    if isinstance(annotation, type):
        return _resolve_class(annotation)
    origin = cast("object | None", typing.get_origin(annotation))
    if origin is None:
        raise UndescribableType(_name_of(annotation))
    arguments = _arguments_of(annotation)
    if origin is typing.Annotated:
        return resolve_type(arguments[0], item=item)
    if origin is typing.Literal:
        return annotation
    if origin is typing.Union or origin is types.UnionType:  # pyright: ignore[reportDeprecated]
        for argument in arguments:
            _ = resolve_type(argument, item=item)
        return annotation
    if origin in _ITERATION_ORIGINS:
        raise UndescribableType(
            f"{_name_of(annotation)}, which is Python iteration rather than data"
        )
    if origin in _SEQUENCE_ORIGINS:
        if not arguments and (
            origin is collections.abc.Iterable or origin is collections.abc.Sequence
        ):
            raise UndescribableType(
                f"{_name_of(annotation)}, which does not say what it holds"
            )
        for argument in arguments:
            _ = resolve_type(argument, item=item)
        return annotation
    if origin in _MAPPING_ORIGINS:
        if len(arguments) != 2 or arguments[0] is not str:
            raise UndescribableType(
                f"{_name_of(annotation)}, whose keys are not plain strings"
            )
        _ = resolve_type(arguments[1], item=item)
        return annotation
    raise UndescribableType(_name_of(annotation))


def generic_arguments(annotation: object) -> tuple[object, ...]:
    """Return the type arguments an annotation carries.

    A parametrized pydantic model is a real class rather than a typing alias, so
    ``typing.get_args`` sees nothing; its own metadata says what parametrized it.

    Args:
        annotation: Annotation to inspect.

    Returns:
        Its type arguments, empty when it has none.
    """
    recorded = _generic_metadata(annotation).get("args")
    if isinstance(recorded, tuple):
        return cast("tuple[object, ...]", recorded)
    return _arguments_of(annotation)


def _generic_metadata(annotation: object) -> dict[str, object]:
    """Return the generic metadata pydantic keeps on a parametrized model.

    Args:
        annotation: Annotation to inspect.

    Returns:
        Its ``__pydantic_generic_metadata__``, or an empty mapping when the
        annotation is not a parametrized pydantic model.
    """
    metadata = getattr(annotation, "__pydantic_generic_metadata__", None)
    if isinstance(metadata, dict):
        return cast("dict[str, object]", metadata)
    return {}


def _arguments_of(annotation: object) -> tuple[object, ...]:
    """Return the typing arguments of an annotation.

    ``typing.get_args`` is typed loosely because a typing construct can hold
    anything, so the result is narrowed here once instead of at every use.

    Args:
        annotation: Annotation to inspect.

    Returns:
        Its arguments as plain objects.
    """
    return cast("tuple[object, ...]", tuple(typing.get_args(annotation)))


def _is_open_item(annotation: object) -> bool:
    """Report whether an annotation is a type variable that is still open.

    Args:
        annotation: Annotation or type argument to test.

    Returns:
        ``True`` for a type variable, including the ``typing.TypeVar`` class a
        parametrized pydantic model reports for its own parameters.
    """
    return isinstance(annotation, typing.TypeVar) or annotation is typing.TypeVar


def _close_type_arguments(annotation: object, item: object | None) -> object:
    """Replace the open type arguments of an annotation with ``item``.

    A pager reports its item type as a type variable, which has no JSON Schema.
    The unit that owns the member says what stands in for it, so the substitution
    happens here and pydantic then describes a concrete type.

    Args:
        annotation: Annotation to close.
        item: Type that stands in for an open argument.

    Returns:
        The annotation with every open argument replaced, or itself when it has
        none.

    Raises:
        UndescribableType: If an argument is open and nothing stands in for it.
    """
    if _is_open_item(annotation):
        if item is None:
            raise UndescribableType(f"the unresolved type variable {annotation}")
        return item
    arguments = generic_arguments(annotation)
    if not arguments:
        return annotation
    closed = tuple(_close_type_arguments(argument, item) for argument in arguments)
    if closed == arguments:
        return annotation
    origin = _generic_origin(annotation)
    if origin is None:
        return annotation
    if origin is types.UnionType or origin is typing.Union:  # pyright: ignore[reportDeprecated]
        # ``X | Y`` rebuilds to the same schema as ``Union[X, Y]``, and only the
        # latter can be subscripted with a computed tuple of arguments.
        return _subscript(typing.Union, closed)  # pyright: ignore[reportDeprecated]
    return _subscript(origin, closed)


def _subscript(origin: object, arguments: tuple[object, ...]) -> object:
    """Parametrize a generic with ``arguments``.

    Args:
        origin: Class or typing construct that takes the arguments.
        arguments: Type arguments to apply.

    Returns:
        The parametrized annotation, or ``origin`` itself when it refuses the
        subscript, which happens for typing constructs that only accept values.
    """
    subscriptable = cast("_SupportsSubscript", origin)
    try:
        return subscriptable[arguments]
    except TypeError:
        return origin


def _generic_origin(annotation: object) -> object | None:
    """Return what an annotation is built from.

    Args:
        annotation: Annotation to inspect.

    Returns:
        The parametrized class of a pydantic generic model, the origin of a
        typing alias, or ``None``.
    """
    origin = _generic_metadata(annotation).get("origin")
    if origin is not None:
        return origin
    return cast("object | None", typing.get_origin(annotation))


def item_type_of(annotation: object) -> object | None:
    """Return the item type of a parametrized generic annotation.

    Args:
        annotation: Annotation of a pager or of another single-argument generic.

    Returns:
        Its single type argument, or ``None`` when it carries none.
    """
    arguments = generic_arguments(annotation)
    return arguments[0] if len(arguments) == 1 else None


def reference_to(name: str) -> JsonObject:
    """Return the schema that points at a definition.

    Args:
        name: Key of the ``$defs`` entry.

    Returns:
        A schema holding only the pointer to that definition.
    """
    return {"$ref": f"{DEF_PREFIX}{name}"}


class SchemaBuilder:
    """Collects the types of the public API and generates their schemas once.

    A request adds a wrapper model to the pending generation pass; :meth:`build`
    runs that pass and hands back the schema of each request together with the
    definitions they share.
    """

    def __init__(self) -> None:
        """Create a builder with no pending requests."""
        self._models: dict[str, type[BaseModel]] = {}
        self._kinds: dict[str, str] = {}
        self._counter = 0

    def add_parameters(
        self, key: str, fields: dict[str, tuple[object, object]]
    ) -> None:
        """Request the schemas of one operation signature.

        Args:
            key: Key the caller reads the parameters back from.
            fields: Parameter name mapped to its annotation and its default,
                where :data:`inspect.Parameter.empty` marks a required parameter.
                The order of the mapping is the signature order.
        """
        model = _wrapper_model(
            self._next_name("Params"),
            {
                name: (fields[name][0], _pydantic_default(fields[name][1]))
                for name in fields
            },
        )
        self._register(key, _PARAMS_KIND, model)

    def add_value(self, key: str, annotation: object) -> None:
        """Request the schema of one value, typically a return annotation.

        Args:
            key: Key the caller reads the schema back from.
            annotation: Type of the value, already accepted by
                :func:`resolve_type`.
        """
        model = _wrapper_model(
            self._next_name("Value"), {"result": (annotation, PydanticUndefined)}
        )
        self._register(key, _VALUE_KIND, model)

    def build(self) -> Schemas:
        """Generate every requested schema in a single pydantic pass.

        Returns:
            The shared definitions and the schema of each request key, every list
            and mapping ordered by name so two runs emit the same document.

        Raises:
            KSeFException: If pydantic returns something that is not JSON data.
        """
        if not self._models:
            return Schemas(definitions={}, values={}, parameters={})
        bundle = _wrapper_model(
            f"{_WRAPPER}Bundle",
            {
                f"member_{index}": (model, PydanticUndefined)
                for index, model in enumerate(self._models.values())
            },
        )
        document = as_object(
            cast(
                "object",
                TypeAdapter(bundle).json_schema(
                    mode="validation", ref_template=f"{DEF_PREFIX}{{model}}"
                ),
            )
        )
        document = _readable_definition_names(document)
        definitions = as_object(document.get("$defs"))
        wrappers = {key: model.__name__ for key, model in self._models.items()}
        values: dict[str, JsonObject] = {}
        parameters: dict[str, list[ParameterSchema]] = {}
        for key, wrapper in wrappers.items():
            schema = as_object(definitions.pop(wrapper, {}))
            properties = as_object(schema.get("properties", {}))
            if self._kinds[key] == _PARAMS_KIND:
                parameters[key] = _signature(schema, properties)
            else:
                values[key] = as_object(properties["result"])
        _ = definitions.pop(T.__name__, None)
        if f"{DEF_PREFIX}{T.__name__}" in collect_refs(definitions, set()):
            definitions[T.__name__] = {"description": _TYPE_PARAMETER_DESCRIPTION}
        return Schemas(
            definitions=_encoded_mapping(definitions),
            values={key: _encoded(values[key]) for key in sorted(values)},
            parameters={
                key: _encoded_list(parameters[key]) for key in sorted(parameters)
            },
        )

    def _next_name(self, kind: str) -> str:
        """Return an unused wrapper model name.

        Args:
            kind: Section of the manifest the wrapper belongs to.

        Returns:
            A name no SDK model can collide with.
        """
        self._counter += 1
        return f"{_WRAPPER}{kind}_{self._counter:04d}"

    def _register(self, key: str, kind: str, model: type[BaseModel]) -> None:
        """Remember a wrapper model under its request key.

        Args:
            key: Key the caller reads the result back from.
            kind: Whether the wrapper holds a signature or a single value.
            model: Wrapper model pydantic generates.
        """
        self._models[key] = model
        self._kinds[key] = kind


def _wrapper_model(
    name: str, fields: dict[str, tuple[object, object]]
) -> type[BaseModel]:
    """Build the pydantic model a manifest request is generated from.

    The field annotations of the public API are arbitrary typing constructs, so
    they cannot be typed as pydantic field definitions; they are checked by
    :func:`resolve_type` before they reach this function.

    Args:
        name: Model name, which becomes its key in the generated definitions.
        fields: Field name mapped to its annotation and default value.

    Returns:
        A pydantic model with those fields, in the given order.
    """
    built: object = create_model(  # pyright: ignore[reportCallIssue, reportUnknownVariableType]
        name,
        __config__=ConfigDict(protected_namespaces=(), validate_default=False),
        **fields,  # pyright: ignore[reportArgumentType]
    )
    return cast("type[BaseModel]", built)


def _signature(schema: JsonObject, properties: JsonObject) -> list[ParameterSchema]:
    """Return the parameters a wrapper model generated.

    Args:
        schema: Generated schema of the wrapper model.
        properties: Properties of that schema, in signature order.

    Returns:
        One entry per parameter, keeping the signature order.
    """
    generated = frozenset(str(name) for name in _as_list(schema.get("required")))
    parameters: list[ParameterSchema] = []
    for name in properties:
        property_schema = as_object(properties[name])
        has_default = "default" in property_schema
        parameters.append(
            ParameterSchema(
                name=name,
                required=name in generated,
                schema=property_schema,
                default=property_schema.get("default"),
                has_default=has_default,
            )
        )
    return parameters


def _resolve_class(annotation: type[object]) -> object:
    """Return a class annotation the manifest can describe.

    Args:
        annotation: Class used directly as an annotation.

    Returns:
        The class, ready for pydantic.

    Raises:
        UndescribableType: If no JSON Schema describes the class.
    """
    if issubclass(annotation, BaseModel):
        return annotation
    if issubclass(annotation, enum.Enum):
        if _describes_enum(annotation):
            return annotation
        raise UndescribableType(
            f"{_name_of(annotation)}, which pydantic does not describe as a JSON"
            " enumeration"
        )
    if annotation in _SCALAR_TYPES:
        return annotation
    raise UndescribableType(_name_of(annotation))


def _describes_enum(annotation: type[enum.Enum]) -> bool:
    """Report whether pydantic describes an enum as a JSON enumeration.

    An enum can carry values that are not JSON data at all, as ``FormSchema``
    does with its tuples, and still declare a core schema that writes member
    names. Asking pydantic is the only honest way to know, and the answer is a
    named ``$defs`` entry either way.

    Args:
        annotation: Enum class used as an annotation.

    Returns:
        ``True`` when its schema is a JSON enumeration of scalars.
    """
    try:
        with warnings.catch_warnings():
            _ = warnings.simplefilter("error")
            schema = as_object(TypeAdapter(annotation).json_schema(mode="validation"))
    except Exception:
        return False
    values = schema.get("enum")
    if not isinstance(values, list) or not values:
        return False
    entries = cast("list[object]", values)
    return all(isinstance(value, str | int | float | bool) for value in entries)


def _is_scalar(annotation: object) -> bool:
    """Report whether ``annotation`` is one of the scalar types.

    Args:
        annotation: Annotation to test.

    Returns:
        ``True`` when pydantic describes it with a JSON scalar.
    """
    try:
        return annotation in _SCALAR_TYPES
    except TypeError:
        return False


def _readable_definition_names(document: JsonObject) -> JsonObject:
    """Return ``document`` with pydantic's module-qualified names renamed.

    When two models share a short name, pydantic publishes them under their whole
    module path, such as
    ``ksef2___domain__models__certificates__IdentifierType``. The manifest names
    such a type after the module it belongs to and its own name, so a generated
    binding emits ``CertificatesIdentifierType`` beside ``TestdataIdentifierType``
    instead of a path. Every reference to the old name is rewritten with it.

    Args:
        document: Generated document holding the definitions and their references.

    Returns:
        The same document, with readable definition names. A name that would clash
        with a definition the SDK wrote is left as pydantic generated it.
    """
    definitions = as_object(document.get("$defs"))
    renamed: dict[str, str] = {}
    for name in sorted(definitions):
        candidate = _qualified_short_name(name)
        if (
            candidate is not None
            and candidate not in definitions
            and candidate not in renamed.values()
        ):
            renamed[name] = candidate
    if not renamed:
        return document
    updated = as_object(_rewritten(document, renamed))
    generated = as_object(updated.get("$defs"))
    updated["$defs"] = {
        renamed.get(name, name): generated[name] for name in sorted(generated)
    }
    return updated


def _rewritten(value: object, renamed: dict[str, str]) -> object:
    """Return ``value`` with every renamed reference rewritten.

    Args:
        value: Document subtree to walk.
        renamed: Old definition name to new one.

    Returns:
        Copies of the data with the rewritten references.
    """
    if isinstance(value, dict):
        entries = cast("collections.abc.Mapping[str, object]", value)
        result = {key: _rewritten(item, renamed) for key, item in entries.items()}
        reference = result.get("$ref")
        if isinstance(reference, str) and reference.startswith(DEF_PREFIX):
            old = reference[len(DEF_PREFIX) :]
            if old in renamed:
                result["$ref"] = f"{DEF_PREFIX}{renamed[old]}"
        return result
    if isinstance(value, list):
        return [_rewritten(item, renamed) for item in cast("list[object]", value)]
    return value


def _qualified_short_name(name: str) -> str | None:
    """Return the readable name of a definition pydantic qualified by module.

    Args:
        name: Definition name written by pydantic.

    Returns:
        The last two parts of a module-qualified name joined as ``ModuleType``, or
        ``None`` when the name is not qualified.
    """
    if "__" not in name:
        return None
    parts = [part for part in name.split("__") if part]
    if len(parts) < 2:
        return None
    module = parts[-2].lstrip("_")
    if not module.isidentifier():
        return None
    return f"{module[:1].upper()}{module[1:]}{parts[-1]}"


def _name_of(annotation: object) -> str:
    """Return a readable name of an annotation.

    Args:
        annotation: Annotation to name.

    Returns:
        Its qualified name, or its representation for typing constructs.
    """
    module = getattr(annotation, "__module__", None)
    qualifier = getattr(annotation, "__qualname__", None)
    if isinstance(qualifier, str) and isinstance(module, str):
        return qualifier if module == "builtins" else f"{module}.{qualifier}"
    return repr(annotation)


def _pydantic_default(default: object) -> object:
    """Return the pydantic marker for a signature default.

    Args:
        default: Value taken from :func:`inspect.signature`.

    Returns:
        :data:`~pydantic.fields.PydanticUndefined` for a required parameter,
        otherwise the value itself.
    """
    return PydanticUndefined if default is inspect.Parameter.empty else default


def _encoded(value: object) -> JsonObject:
    """Return a schema with binary strings announced as base64.

    Args:
        value: Schema to encode.

    Returns:
        The schema as JSON data with ``bytes`` annotations replaced.

    Raises:
        KSeFException: If the schema holds something that is not JSON data.
    """
    return as_object(encode_bytes_schemas(without_titles(value)))


def _encoded_mapping(definitions: JsonObject) -> JsonObject:
    """Return ``definitions`` ordered by name and with bytes announced.

    Args:
        definitions: Generated definitions, in pydantic's order.

    Returns:
        The same definitions sorted by name.
    """
    return {name: _encoded(definitions[name]) for name in sorted(definitions)}


def _encoded_list(parameters: list[ParameterSchema]) -> list[ParameterSchema]:
    """Return ``parameters`` with bytes announced in every schema.

    Args:
        parameters: Parameters generated for one signature.

    Returns:
        Copies whose schemas and defaults are JSON data.
    """
    return [
        ParameterSchema(
            name=parameter.name,
            required=parameter.required,
            schema=_encoded(parameter.schema),
            default=(
                parameter.default
                if not parameter.has_default
                else require_json(parameter.default)
            ),
            has_default=parameter.has_default,
        )
        for parameter in parameters
    ]


def _as_list(value: object) -> list[object]:
    """Return ``value`` as a list, or an empty list when it is absent.

    Args:
        value: Value read from a generated schema.

    Returns:
        The list, or ``[]`` for a missing key.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return cast("list[object]", value)
    return [value]
