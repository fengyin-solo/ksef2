"""Turn the public sync signatures into JSON Schema draft 2020-12 documents.

The schemas come from the same Pydantic models the SDK validates with, so a
binding reads the contract the SDK enforces. Live objects are described by the
data a caller saves and hands back, never by the object itself, and anything that
cannot cross a JSON boundary raises instead of being quietly invented.
"""

import copy
import datetime
import decimal
import enum
import importlib
import pathlib
import pkgutil
import types
import typing
import uuid
from collections.abc import Collection, Iterable, Iterator, Mapping, MutableMapping
from collections.abc import MutableSequence, Sequence, Set as AbstractSet
from types import ModuleType
from typing import Final, cast

from pydantic import (
    BaseModel,
    PydanticSchemaGenerationError,
    SecretBytes,
    SecretStr,
    TypeAdapter,
)
from ksef2.bridge._catalog import (
    GENERATED_TOKEN_CLASS,
    GENERATED_TOKEN_FIELD,
    GENERATED_TOKEN_STATE_MODEL,
    is_client_class,
    is_pager,
    pager_item_type,
    resume_state_for,
)
from ksef2.bridge._errors import (
    HandsBackAnotherClient,
    ManifestError,
    UnsupportedSignature,
)
from ksef2.bridge._introspect import (
    alias_value,
    attribute_of,
    members_of,
    module_of,
    name_of,
    type_args,
    type_origin,
)
from ksef2.models import Page

Schema = dict[str, object]
"""One JSON Schema document, kept as plain data so it survives ``json.dumps``."""

REF_PREFIX: Final = "#/$defs/"

#: ``bytes`` crosses the boundary as standard Base64 with ``=`` padding. This is
#: deliberately not the URL-safe spelling the export archive uses for its own
#: archive field, which stays described by its own model.
BASE64_STRING: Final[Schema] = {"type": "string", "contentEncoding": "base64"}

#: An unbound type variable: the item type belongs to the caller, so any JSON
#: value is accepted rather than inventing a model the SDK never names.
ANY_VALUE: Final[Schema] = {}

NULL: Final[Schema] = {"type": "null"}

#: Public modules the literal aliases are discovered from. Optional extras are
#: skipped when their third-party dependency is absent.
MODEL_MODULES: Final[tuple[str, ...]] = (
    "ksef2.models",
    "ksef2.profiles",
    "ksef2.testdata",
    "ksef2.xades",
    "ksef2.renderers",
    "ksef2.fa3",
)

#: Modules that define the models, scanned to name the object behind a schema key
#: when two schemas would otherwise share one.
DEFINING_MODULES: Final[tuple[str, ...]] = (
    "ksef2._domain.models",
    "ksef2._domain.types",
)

_SCALAR_SCHEMAS: Final[Mapping[type[object], Schema]] = {
    bool: {"type": "boolean"},
    bytes: BASE64_STRING,
    bytearray: BASE64_STRING,
    datetime.date: {"type": "string", "format": "date"},
    datetime.datetime: {"type": "string", "format": "date-time"},
    datetime.time: {"type": "string", "format": "time"},
    datetime.timedelta: {"type": "string", "format": "duration"},
    decimal.Decimal: {"type": ["number", "string"]},
    float: {"type": "number"},
    int: {"type": "integer"},
    str: {"type": "string"},
    types.NoneType: NULL,
    uuid.UUID: {"type": "string", "format": "uuid"},
}

_SEQUENCE_ORIGINS: Final[frozenset[object]] = frozenset(
    {
        AbstractSet,
        Collection,
        Iterable,
        Iterator,
        MutableSequence,
        Sequence,
        frozenset,
        list,
        set,
        tuple,
    }
)

_MAPPING_ORIGINS: Final[frozenset[object]] = frozenset({Mapping, MutableMapping, dict})

#: Keywords that say how a value is constrained rather than what it is. They come
#: from Pydantic when a signature carries field metadata, and never replace the
#: shape this module decides for the underlying type.
_CONSTRAINT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "contentEncoding",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "maximum",
        "maxItems",
        "maxLength",
        "minimum",
        "minItems",
        "minLength",
        "multipleOf",
        "pattern",
    }
)

#: Keys whose presence means a document says something about the JSON it allows.
_SCHEMA_KEYS: Final[tuple[str, ...]] = (
    "$ref",
    "allOf",
    "anyOf",
    "enum",
    "items",
    "prefixItems",
    "properties",
    "type",
)

_SECRET_ANNOTATIONS: Final[frozenset[object]] = frozenset({SecretStr, SecretBytes})

#: ``typing.Optional[X]`` still shows up in annotations and shares an origin with
#: nothing else; ``X | None`` is handled by ``types.UnionType`` above.
_UNION_ORIGIN: Final = cast(object, typing.Union)  # pyright: ignore[reportDeprecated]


def _import_optional(module: str) -> ModuleType | None:
    """Import *module*, or return ``None`` when its extras are not installed.

    Args:
        module: Dotted module name to import.

    Returns:
        The imported module, or ``None`` when importing it failed.
    """
    try:
        return importlib.import_module(module)
    except ImportError:
        return None


def _scanned_modules(
    names: tuple[str, ...], *, with_submodules: bool
) -> Iterator[ModuleType]:
    """Yield the modules whose members describe the public API.

    Args:
        names: Dotted module names to scan.
        with_submodules: Also scan the submodules of each package.

    Yields:
        Each importable module in the scan.
    """
    for name in names:
        module = _import_optional(name)
        if module is None:
            continue
        yield module
        if not with_submodules:
            continue
        for info in pkgutil.iter_modules(getattr(module, "__path__", [])):
            child = _import_optional(f"{name}.{info.name}")
            if child is not None:
                yield child


def _is_literal_alias(member: object) -> bool:
    """Say whether a module member is a public ``Literal`` alias.

    Args:
        member: Value read from a model module.

    Returns:
        True for a ``TypeAliasType`` whose value is a ``Literal``.
    """
    if not isinstance(member, typing.TypeAliasType):
        return False
    return type_origin(alias_value(member)) is typing.Literal


def literal_aliases() -> dict[str, typing.TypeAliasType]:
    """Discover the public ``Literal`` aliases from the model modules.

    The count follows the models, so a new alias reaches the manifest without a
    matching edit here.

    Returns:
        Each alias keyed by its public name, first occurrence winning.
    """
    found: dict[str, typing.TypeAliasType] = {}
    for module in _scanned_modules(MODEL_MODULES, with_submodules=False):
        for name, member in members_of(module):
            if name.startswith("_") or not _is_literal_alias(member):
                continue
            alias = cast(typing.TypeAliasType, member)
            _ = found.setdefault(name_of(alias), alias)
    return found


def defining_objects() -> dict[str, set[object]]:
    """Index the classes and aliases that can own a schema name.

    Returns:
        Every model class, enum and alias seen, keyed by the name a schema would
        carry. A name maps to a set so a genuine clash stays visible.
    """
    index: dict[str, set[object]] = {}
    modules = list(_scanned_modules(MODEL_MODULES, with_submodules=False))
    modules.extend(_scanned_modules(DEFINING_MODULES, with_submodules=True))
    for module in modules:
        for name, member in members_of(module):
            if name.startswith("_"):
                continue
            if not isinstance(member, type | typing.TypeAliasType):
                continue
            if isinstance(member, typing.TypeAliasType):
                pass
            elif not issubclass(member, BaseModel | enum.Enum):
                continue
            if name_of(member) != name:
                continue
            index.setdefault(name, set()).add(member)
    return index


def _owner_of(name: str, index: Mapping[str, set[object]]) -> str:
    """Name the object a schema key stands for.

    Args:
        name: Schema key to resolve.
        index: Index built by ``defining_objects``.

    Returns:
        A stable label used to tell an honest repeat from a name clash.
    """
    owners = index.get(name)
    if owners is None or len(owners) != 1:
        return f"unknown:{name}"
    return f"{module_of(next(iter(owners)))}.{name}"


def _direct_owner(obj: object, name: str) -> str:
    """Name the object a schema was built from.

    Args:
        obj: Model, enum or alias the schema came from.
        name: Name the schema is filed under.

    Returns:
        A label that matches what ``_owner_of`` reports for the same object.
    """
    return f"{module_of(obj)}.{name}"


def _is_annotated(annotation: object) -> bool:
    """Say whether an annotation carries field metadata.

    Args:
        annotation: Annotation read from a public signature.

    Returns:
        True for ``Annotated[...]`` forms.
    """
    return attribute_of(annotation, "__metadata__") is not None


def _is_data_leaf(annotation: object) -> bool:
    """Say whether Pydantic alone can describe an annotation that is plain data.

    A class the SDK does not treat as data, a callable, and an unannotated
    ``object`` are refused here, so they reach the caller as an excluded
    signature instead of a permissive schema.

    Args:
        annotation: Annotation read from a public signature.

    Returns:
        True when Pydantic should be asked for the schema.
    """
    if annotation is typing.Any or annotation is object:
        return False
    if _is_annotated(annotation) or isinstance(annotation, typing.NewType):
        return True
    if isinstance(annotation, type):
        module = module_of(annotation)
        return module == "pydantic" or module.startswith("pydantic.")
    return False


def _is_json_document(schema: Schema) -> bool:
    """Say whether a schema document says something about the JSON it allows.

    Args:
        schema: Schema built for an annotation.

    Returns:
        False for the empty document Pydantic gives ``object`` and ``Any``.
    """
    return any(key in schema for key in _SCHEMA_KEYS)


def _string_enum_values(schema: Schema) -> tuple[str, ...] | None:
    """Return the values of a string enum schema, or ``None`` for other shapes.

    Args:
        schema: Schema to inspect.

    Returns:
        The declared values when the schema is a string enum.
    """
    if schema.get("type") not in (None, "string"):
        return None
    values = schema.get("enum")
    if not isinstance(values, list):
        return None
    return tuple(
        value for value in cast("list[object]", values) if isinstance(value, str)
    )


def _page_item_type(annotation: object) -> object | None:
    """Return the item type of a ``Page`` model, or ``None`` for anything else.

    Pydantic builds a real class for ``Page[TokenInfo]``, so the item type lives
    in the generic metadata rather than in ``__args__``.

    Args:
        annotation: Annotation read from a public signature.

    Returns:
        The item type the page carries, or ``None`` when the annotation is not a
        page or names no item type.
    """
    if not isinstance(annotation, type) or not issubclass(annotation, Page):
        return None
    metadata = attribute_of(cast("object", annotation), "__pydantic_generic_metadata__")
    if not isinstance(metadata, dict):
        return None
    args = cast("dict[str, object]", metadata).get("args")
    if isinstance(args, tuple) and args:
        return cast("object", args[0])
    return None


def _is_union(annotation: object) -> bool:
    """Say whether an annotation is a union of alternatives.

    Args:
        annotation: Annotation read from a public signature.

    Returns:
        True for ``X | Y`` and for the ``typing.Optional`` form.
    """
    return (
        isinstance(annotation, types.UnionType)
        or type_origin(annotation) is _UNION_ORIGIN
    )


def _session_state_of(annotation: type[object]) -> object:
    """Return the saved state that names a client object in a parameter.

    A parameter that accepts a live session accepts the state a caller saved for
    it, so the state is what the schema can describe.

    Args:
        annotation: Client class used as an annotation.

    Returns:
        The resume-state model of that class.

    Raises:
        UnsupportedSignature: The class has no saved form to describe.
    """
    state = resume_state_for(annotation)
    if state is None:
        raise UnsupportedSignature(name_of(annotation))
    return state


def _is_secret_annotation(annotation: object) -> bool:
    """Say whether an annotation is, or carries, a ``SecretStr`` or ``SecretBytes``.

    Args:
        annotation: Field annotation to inspect.

    Returns:
        True when a secret type appears anywhere inside the annotation.
    """
    if annotation in _SECRET_ANNOTATIONS:
        return True
    return any(_is_secret_annotation(arg) for arg in type_args(annotation))


def _sensitive_field_names(model: type[BaseModel]) -> set[str]:
    """Return the fields of *model* that hold secrets.

    A field is sensitive when it stays out of ``repr()``, stays out of a generic
    dump, or is typed as a ``SecretStr`` or ``SecretBytes``.

    Args:
        model: Model class to inspect.

    Returns:
        Field names that carry credentials, keys or presigned URLs.
    """
    names: set[str] = set()
    for name, field in model.model_fields.items():
        annotation = cast("object", field.annotation)
        if field.repr is False or field.exclude is True:
            names.add(name)
        elif _is_secret_annotation(annotation):
            names.add(name)
    return names


def _model_closure(model: type[BaseModel]) -> Iterator[type[BaseModel]]:
    """Yield *model* and every model reachable through its fields.

    Args:
        model: Model to start from.

    Yields:
        Each model class in the graph, visited once.
    """
    seen: set[type[BaseModel]] = set()
    pending: list[object] = [model]
    while pending:
        annotation = pending.pop()
        if isinstance(annotation, typing.TypeVar):
            continue
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if annotation in seen:
                continue
            seen.add(annotation)
            yield annotation
            pending.extend(
                cast("object", field.annotation)
                for field in annotation.model_fields.values()
            )
            continue
        pending.extend(type_args(cast("object", annotation)))


class SchemaBuilder:
    """Collect the named schemas a manifest needs, once each.

    Every model, enum and literal alias gets one entry in ``$defs`` under its
    public name, and every reference points at that entry. Two different objects
    claiming one name stop the build instead of being renamed.
    """

    def __init__(self) -> None:
        """Register the public literal aliases as named string enums."""
        self._defs: dict[str, Schema] = {}
        self._owners: dict[str, str] = {}
        self._sensitive: dict[str, set[str]] = {}
        self._index = defining_objects()
        for name, alias in sorted(literal_aliases().items()):
            document = _literal_document(alias)
            if document is None:
                continue
            _ = self.register(name, document, _owner_of(name, self._index))

    @property
    def defs(self) -> dict[str, Schema]:
        """The named schemas, in registration order.

        Returns:
            Every registered schema, deep-copied out of the builder.
        """
        return copy.deepcopy(self._defs)

    def register(self, name: str, schema: Schema, owner: str) -> Schema:
        """Add a named schema, refusing to rename a clash.

        Args:
            name: Public name the schema is filed under.
            schema: Schema document to store.
            owner: Label naming the object the schema came from.

        Returns:
            A reference to ``#/$defs/{name}``.

        Raises:
            ManifestError: If a different schema already holds *name*.
        """
        existing = self._defs.get(name)
        if existing is None:
            self._defs[name] = copy.deepcopy(schema)
            self._owners[name] = owner
        elif existing == schema or self._owners[name] == owner:
            pass
        elif _string_enum_values(existing) == _string_enum_values(schema):
            pass
        else:
            raise ManifestError(
                f"the manifest cannot name both {self._owners[name]!r} and "
                f"{owner!r} as {name!r}. Keep the public class names, and give "
                "one of them a distinct name in the public API."
            )
        return {"$ref": f"{REF_PREFIX}{name}"}

    def model_ref(self, model: type[BaseModel]) -> Schema:
        """File a model and its nested models under their own names.

        Args:
            model: Model class to describe.

        Returns:
            A reference to the model's entry in ``$defs``.
        """
        self._note_models(model)
        document = self._absorb(model)
        if set(document) == {"$ref"}:
            return document
        return self.register(
            name_of(model), document, _direct_owner(model, name_of(model))
        )

    def enum_ref(self, enumeration: type[enum.Enum]) -> Schema:
        """File an enum under its public name.

        Args:
            enumeration: Enum class to describe.

        Returns:
            A reference to the enum's entry in ``$defs``.
        """
        name = name_of(enumeration)
        return self.register(
            name, self._pydantic(enumeration), _direct_owner(enumeration, name)
        )

    def alias_ref(
        self,
        alias: typing.TypeAliasType,
        bindings: Mapping[object, object],
        *,
        returns: bool = False,
        owner: type[object] | None = None,
    ) -> Schema:
        """File a public alias under its own name and return the reference.

        A ``Literal`` alias becomes a named string enum, which is how a binding
        sees the allowed values. Any other alias, such as the constrained
        ``CertificateSerialNumber``, is filed under the same name so a parameter
        that uses it still says which public type it means.

        Args:
            alias: Public ``TypeAliasType`` used by a signature.
            bindings: Type variables the walked class already filled in.
            returns: Whether the annotation describes the result.
            owner: Class the signature belongs to, used to resolve ``Self``.

        Returns:
            A reference to the alias' entry in ``$defs``.
        """
        name = name_of(alias)
        document = _literal_document(alias)
        if document is None:
            document = dict(
                self.schema_of(
                    alias_value(alias), bindings, returns=returns, owner=owner
                )
            )
            _ = document.setdefault("title", name)
        return self.register(name, document, _direct_owner(alias, name))

    def page_schema(self, item: Schema) -> Schema:
        """Describe one page of a collection.

        The live pager is never described: a binding fetches pages of the same
        collection, and the cursor is what carries it between requests.

        Args:
            item: Schema of one item of the collection.

        Returns:
            An object schema with ``items`` and ``next_cursor``.
        """
        return {
            "type": "object",
            "title": name_of(Page),
            "properties": {
                "items": {"type": "array", "items": copy.deepcopy(item)},
                "next_cursor": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "required": ["items", "next_cursor"],
        }

    def generated_token_schema(self) -> Schema:
        """Describe a generated token as its saved state plus the one-time token.

        ``GeneratedTokenResumeState`` holds no token by design, and a binding
        still has to receive it once, so the token is a sibling of the state.

        Returns:
            An object schema with required ``state`` and ``token``.
        """
        state = self.model_ref(GENERATED_TOKEN_STATE_MODEL)
        return {
            "type": "object",
            "title": name_of(GENERATED_TOKEN_CLASS),
            "properties": {
                "state": copy.deepcopy(state),
                GENERATED_TOKEN_FIELD: {"type": "string"},
            },
            "required": ["state", GENERATED_TOKEN_FIELD],
        }

    def state_ref(self, model: type[BaseModel]) -> Schema:
        """Describe the saved state a receiver needs.

        Args:
            model: Resume-state model of a walked class.

        Returns:
            A reference to the model's entry in ``$defs``.
        """
        return self.model_ref(model)

    def definition(self, name: str) -> Schema | None:
        """Return the stored schema for one ``$defs`` key.

        The document belongs to the builder and must not be modified; it is
        handed out so the manifest can follow the references inside it.

        Args:
            name: Key in ``$defs``.

        Returns:
            The schema filed under that name, or ``None`` when none is.
        """
        return self._defs.get(name)

    def sensitive_field_names(self, def_name: str) -> frozenset[str]:
        """Return the fields a named schema keeps out of ``repr()``.

        Args:
            def_name: Key in ``$defs``.

        Returns:
            The secret-bearing field names of that schema.
        """
        return frozenset(self._sensitive.get(def_name, set()))

    def schema_of(
        self,
        annotation: object,
        bindings: Mapping[object, object],
        *,
        returns: bool = False,
        owner: type[object] | None = None,
    ) -> Schema:
        """Describe one annotation as JSON Schema.

        Args:
            annotation: Annotation read from a public signature.
            bindings: Type variables the walked class already filled in.
            returns: Whether the annotation describes the result, which decides
                how a client object is reported.
            owner: Class the signature belongs to, used to resolve ``Self``.

        Returns:
            A schema for the annotation.

        Raises:
            UnsupportedSignature: The annotation has no JSON representation.
            HandsBackAnotherClient: The result is another walked client.
        """
        if annotation is None or annotation is types.NoneType:
            return copy.deepcopy(NULL)
        if annotation is typing.Self:
            if owner is None:
                raise UnsupportedSignature("Self")
            return self.schema_of(owner, {}, returns=True)
        if isinstance(annotation, typing.TypeVar):
            bound = bindings.get(annotation, annotation)
            if bound is annotation:
                return copy.deepcopy(ANY_VALUE)
            return self.schema_of(bound, bindings, returns=returns, owner=owner)
        if isinstance(annotation, typing.TypeAliasType):
            return self.alias_ref(annotation, bindings, returns=returns, owner=owner)
        if is_pager(annotation):
            return self.page_schema(self._pager_item(annotation, bindings, owner))
        page_item = _page_item_type(annotation)
        if page_item is not None:
            return self.page_schema(
                self.schema_of(page_item, bindings, returns=returns, owner=owner)
            )
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return self.model_ref(annotation)
        if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
            return self.enum_ref(annotation)
        state = resume_state_for(annotation) if isinstance(annotation, type) else None
        if state is not None:
            return self.model_ref(state)
        if annotation is GENERATED_TOKEN_CLASS:
            return self.generated_token_schema()
        if isinstance(annotation, type) and is_client_class(annotation):
            if returns:
                raise HandsBackAnotherClient(name_of(annotation))
            return self.schema_of(
                _session_state_of(annotation), bindings, returns=returns, owner=owner
            )
        if _is_annotated(annotation):
            return self._annotated(annotation, bindings, returns=returns, owner=owner)
        scalar = (
            _SCALAR_SCHEMAS.get(annotation) if isinstance(annotation, type) else None
        )
        if (
            scalar is None
            and isinstance(annotation, type)
            and issubclass(annotation, pathlib.PurePath)
        ):
            return {"type": "string", "format": "path"}
        if scalar is not None:
            return copy.deepcopy(scalar)
        if _is_union(annotation):
            return self._union(annotation, bindings, returns=returns, owner=owner)
        container = self._container(annotation, bindings, returns=returns, owner=owner)
        if container is not None:
            return container
        if _is_data_leaf(annotation):
            documented = self._absorb(annotation)
            if _is_json_document(documented):
                return documented
        raise UnsupportedSignature(name_of(annotation))

    def _pager_item(
        self,
        annotation: object,
        bindings: Mapping[object, object],
        owner: type[object] | None,
    ) -> Schema:
        """Describe the items of a pager annotation.

        Args:
            annotation: Pager annotation, bare or parameterised.
            bindings: Type variables the walked class already filled in.
            owner: Class the signature belongs to, used to resolve ``Self``.

        Returns:
            The item schema, or any JSON value when the item type is the caller's
            to choose.
        """
        item = pager_item_type(annotation)
        if item is None:
            return copy.deepcopy(ANY_VALUE)
        return self.schema_of(item, bindings, owner=owner)

    def _annotated(
        self,
        annotation: object,
        bindings: Mapping[object, object],
        *,
        returns: bool,
        owner: type[object] | None,
    ) -> Schema:
        """Describe an ``Annotated`` form, keeping the constraints Pydantic reads.

        The underlying type still goes through the rules above, so a validated
        session or a constrained serial number keeps the shape this module gives
        it and only picks up the constraint keywords from Pydantic.

        Args:
            annotation: ``Annotated[...]`` form to describe.
            bindings: Type variables the walked class already filled in.
            returns: Whether the annotation describes the result.
            owner: Class the signature belongs to, used to resolve ``Self``.

        Returns:
            The schema of the underlying type plus its declared constraints.
        """
        underlying = type_args(annotation)[0]
        schema = dict(
            self.schema_of(underlying, bindings, returns=returns, owner=owner)
        )
        try:
            constraints = self._pydantic(annotation)
        except UnsupportedSignature:
            return schema
        for key, value in constraints.items():
            if key in _CONSTRAINT_KEYS:
                schema[key] = value
        return schema

    def _union(
        self,
        annotation: object,
        bindings: Mapping[object, object],
        *,
        returns: bool,
        owner: type[object] | None,
    ) -> Schema:
        """Describe a union as ``anyOf``, without duplicate alternatives.

        Args:
            annotation: Union annotation to describe.
            bindings: Type variables the walked class already filled in.
            returns: Whether the annotation describes the result.
            owner: Class the signature belongs to, used to resolve ``Self``.

        Returns:
            An ``anyOf`` schema, or the single distinct alternative.

        Raises:
            UnsupportedSignature: The union names no alternative at all.
        """
        members: list[Schema] = []
        for arg in type_args(annotation):
            member = self.schema_of(arg, bindings, returns=returns, owner=owner)
            if member not in members:
                members.append(member)
        if not members:
            raise UnsupportedSignature(name_of(annotation))
        if len(members) == 1:
            return members[0]
        return {"anyOf": members}

    def _container(
        self,
        annotation: object,
        bindings: Mapping[object, object],
        *,
        returns: bool,
        owner: type[object] | None,
    ) -> Schema | None:
        """Describe a sequence or mapping annotation, or decline.

        Args:
            annotation: Annotation to describe.
            bindings: Type variables the walked class already filled in.
            returns: Whether the annotation describes the result.
            owner: Class the signature belongs to, used to resolve ``Self``.

        Returns:
            An array or object schema, or ``None`` when the annotation is not a
            container.
        """
        origin = type_origin(annotation)
        if origin is None and annotation in _SEQUENCE_ORIGINS | _MAPPING_ORIGINS:
            origin = annotation
        if origin is None:
            return None
        args = list(type_args(annotation))
        if origin is tuple:
            if not args or Ellipsis in args:
                return {"type": "array", "items": copy.deepcopy(ANY_VALUE)}
            return {
                "type": "array",
                "prefixItems": [
                    self.schema_of(arg, bindings, returns=returns, owner=owner)
                    for arg in args
                ],
                "minItems": len(args),
                "maxItems": len(args),
            }
        if origin in _MAPPING_ORIGINS:
            value = args[1] if len(args) > 1 else None
            return {
                "type": "object",
                "additionalProperties": (
                    copy.deepcopy(ANY_VALUE)
                    if value is None
                    else self.schema_of(value, bindings, returns=returns, owner=owner)
                ),
            }
        if origin in _SEQUENCE_ORIGINS:
            item = args[0] if args else None
            return {
                "type": "array",
                "items": (
                    copy.deepcopy(ANY_VALUE)
                    if item is None
                    else self.schema_of(item, bindings, returns=returns, owner=owner)
                ),
            }
        return None

    def _absorb(self, annotation: object) -> Schema:
        """Ask Pydantic for a schema and file every nested definition it names.

        Args:
            annotation: Type Pydantic can describe.

        Returns:
            The schema for *annotation*, with nested models referenced by name.

        Raises:
            UnsupportedSignature: Pydantic cannot describe the annotation.
        """
        document = dict(self._pydantic(annotation))
        nested = document.pop("$defs", None)
        if isinstance(nested, dict):
            for name, value in cast("dict[str, object]", nested).items():
                if isinstance(value, dict):
                    _ = self.register(
                        name,
                        cast("Schema", value),
                        _owner_of(name, self._index),
                    )
        return document

    def _pydantic(self, annotation: object) -> Schema:
        """Return the standalone JSON Schema Pydantic builds for *annotation*.

        Args:
            annotation: Type to describe.

        Returns:
            The schema, with nested models left in ``$defs``.

        Raises:
            UnsupportedSignature: Pydantic cannot describe the annotation.
        """
        adapter = TypeAdapter(cast("type[object]", annotation))
        try:
            schema = adapter.json_schema(ref_template=f"{REF_PREFIX}{{model}}")
        except (PydanticSchemaGenerationError, TypeError) as exc:
            raise UnsupportedSignature(name_of(annotation)) from exc
        return cast("Schema", schema)

    def _note_models(self, model: type[BaseModel]) -> None:
        """Record which fields of a model graph hold secrets.

        Args:
            model: Model reachable from a signature.
        """
        for entry in _model_closure(model):
            names = _sensitive_field_names(entry)
            if names:
                self._sensitive.setdefault(name_of(entry), set()).update(names)


def _literal_document(alias: typing.TypeAliasType) -> Schema | None:
    """Describe a string ``Literal`` alias as a named enum schema.

    Args:
        alias: Public ``TypeAliasType`` to inspect.

    Returns:
        A string enum document, or ``None`` when the alias stands for anything
        else and has to be described through its value.
    """
    value = alias_value(alias)
    if type_origin(value) is not typing.Literal:
        return None
    values = type_args(value)
    if not values or not all(isinstance(item, str) for item in values):
        return None
    name = name_of(alias)
    return {"type": "string", "enum": list(values), "title": name}


def ref_names(schema: object) -> set[str]:
    """Collect every ``$ref`` target inside a schema document.

    Args:
        schema: Schema, or any nested part of one.

    Returns:
        The names each reference points at in ``$defs``.
    """
    found: set[str] = set()
    if isinstance(schema, dict):
        for key, value in cast("dict[object, object]", schema).items():
            if (
                isinstance(key, str)
                and key == "$ref"
                and isinstance(value, str)
                and value.startswith(REF_PREFIX)
            ):
                found.add(value[len(REF_PREFIX) :])
            else:
                found.update(ref_names(value))
    elif isinstance(schema, list):
        for item in cast("list[object]", schema):
            found.update(ref_names(item))
    return found
