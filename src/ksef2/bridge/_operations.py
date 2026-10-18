"""What each manifest operation needs before a binding can call it.

The manifest published by :mod:`ksef2.bridge._manifest` says which ids exist,
which arguments they take, which state rebuilds their receiver and what their
result looks like. This module turns that document into a table of Python types:
one row per operation, holding the member to read, a validator per argument and
the shape of the result. No operation is named here, so an operation that joins
the walked classes reaches the dispatcher without an edit in this file.

Only two things are decided locally. A pager is a position inside one
operation's own walk, so no saved state rebuilds it and its operations cannot be
bound. A parameter whose type is a client is written as the state that rebuilds
it, which is how the manifest already describes it, and has to be turned back
into the live client before the call.
"""

import functools
import inspect
import typing
from dataclasses import dataclass
from types import NoneType
from typing import Final, cast

from pydantic import BaseModel, ConfigDict, TypeAdapter

from ksef2.bridge._catalog import WALKED_CLASSES, resume_state_for
from ksef2.bridge._manifest import build_manifest

CURSOR: Final = "cursor"
"""The extra argument a page takes, and no other operation takes."""

PAGE_TITLE: Final = "Page"
"""The title the manifest gives the result of a collection operation."""

GENERATED_TOKEN_TITLE: Final = "GeneratedToken"
"""The title the manifest gives a freshly generated token."""

#: Receivers no saved state rebuilds, because the object is a position in a walk
#: rather than something a document describes.
UNBOUND_PREFIXES: Final[frozenset[str]] = frozenset({"pager", "invoice_search"})

_CLASS_BY_PREFIX: Final[dict[str, type[object]]] = {
    target.prefix: target.cls for target in WALKED_CLASSES
}
"""The class each id prefix belongs to."""

_STATE_BY_PREFIX: Final[dict[str, type[BaseModel] | None]] = {
    target.prefix: target.state_model for target in WALKED_CLASSES
}
"""The state that rebuilds each prefix's receiver, ``None`` when none does."""


@dataclass(frozen=True)
class Parameter:
    """One argument of one operation.

    Attributes:
        name: The name the caller spells in ``args_json``.
        required: Whether the operation cannot be called without it.
        validator: Reads the JSON value into the Python the member accepts.
        client: The client class the value rebuilds, when the member wants a live
            client rather than the state it was given.
    """

    name: str
    required: bool
    validator: TypeAdapter[object]
    client: type[object] | None


@dataclass(frozen=True)
class Operation:
    """One manifest operation, ready to be called.

    Attributes:
        id: The manifest id, such as ``tokens.list``.
        prefix: The first id component, which names the receiver.
        member: The attribute to read on the receiver.
        state_model: The state that rebuilds the receiver, ``None`` when the
            receiver needs none.
        parameters: The declared arguments, in signature order.
        names: The argument names the call may use.
        required: The argument names the call may not omit.
        attribute: Whether the member is a property to read instead of a method.
        constructor: Whether the member is reached on the class rather than on a
            receiver, because it builds one.
        page: Whether the result is one page of a collection.
        token: Whether the result is a freshly generated token.
        bindable: Whether saved state rebuilds the receiver.
    """

    id: str
    prefix: str
    member: str
    state_model: type[BaseModel] | None
    parameters: tuple[Parameter, ...]
    names: frozenset[str]
    required: frozenset[str]
    attribute: bool
    constructor: bool
    page: bool
    token: bool
    bindable: bool


def required_type(annotation: object) -> object:
    """Return the type of an argument the caller must supply.

    A parameter the manifest marks required is not optional, even where the
    Python signature defaults it to ``None`` on behalf of another form. The
    manifest dropped that ``None`` from the schema it published, so dropping it
    here is what keeps the two boundaries agreeing.

    Args:
        annotation: The declared annotation.

    Returns:
        The annotation with any ``None`` alternative removed.
    """
    alternatives = cast("tuple[object, ...]", typing.get_args(annotation))
    if not alternatives:
        return annotation
    kept = tuple(item for item in alternatives if item is not NoneType)
    if len(kept) == len(alternatives) or not kept:
        return annotation
    if len(kept) == 1:
        return kept[0]
    joined: type[object] | None = None
    for item in cast("tuple[type[object], ...]", kept):
        joined = item if joined is None else cast("type[object]", joined | item)
    return cast("object", joined)


def validator_of(annotation: object) -> TypeAdapter[object]:
    """Return the validator of one declared argument, reading JSON semantics.

    A bare ``bytes`` is read as the standard Base64 the manifest declares for it.
    A model keeps the configuration it carries, because its own schema says how
    it reads itself: ``ExportedInvoicesData`` asks for Base64, while
    ``XAdESCredentials`` asks for the text of a PEM document.

    Args:
        annotation: The annotation of the argument.

    Returns:
        A validator for a value that came out of ``json.loads``.
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return TypeAdapter(annotation)
    return TypeAdapter(
        cast("type[object]", annotation),
        config=ConfigDict(val_json_bytes="base64"),
    )


def _member_of(cls: type[object], member: str) -> object:
    """Return the callable whose annotations describe one member.

    Args:
        cls: The class that holds the member.
        member: The attribute name.

    Returns:
        The function itself, the getter of a property, or the function behind a class
        or static method. A cached property is never reached here: the table treats it
        as an attribute, which is how a value that reads no arguments is called.
    """
    raw = cast("object", inspect.getattr_static(cls, member))
    if isinstance(raw, property):
        return cast("object", raw.fget)
    if isinstance(raw, classmethod | staticmethod):
        return cast("object", raw.__func__)
    return raw


def _is_attribute(cls: type[object], member: str) -> bool:
    """Say whether one member is read rather than called.

    Args:
        cls: The class that holds the member.
        member: The attribute name.

    Returns:
        True for a property or a cached property.
    """
    return isinstance(
        inspect.getattr_static(cls, member), property | functools.cached_property
    )


def _is_constructor(cls: type[object], member: str) -> bool:
    """Say whether one member is reached on the class itself.

    A class method builds the object its class otherwise hands out, so it is reached
    without one: a binding rebuilding an export result from a snapshot has no result
    to name yet.

    Args:
        cls: The class that holds the member.
        member: The attribute name.

    Returns:
        True for a class method or a static method.
    """
    return isinstance(
        cast("object", inspect.getattr_static(cls, member)), classmethod | staticmethod
    )


def class_of(prefix: str) -> type[object]:
    """Return the class one id prefix belongs to.

    Args:
        prefix: The first component of a manifest id.

    Returns:
        The class the manifest walks under that prefix.
    """
    return _CLASS_BY_PREFIX[prefix]


def _parameters_of(
    cls: type[object], member: str, entry: dict[str, object]
) -> tuple[Parameter, ...]:
    """Build the arguments of one operation from its manifest entry.

    Args:
        cls: The class the member belongs to.
        member: The attribute name.
        entry: The manifest operation entry.

    Returns:
        One parameter per declared argument, in signature order.

    Raises:
        RuntimeError: The manifest names an argument the member does not declare,
            which means the two views of the same method have drifted apart.
    """
    member_of = typing.cast("typing.Callable[..., object]", _member_of(cls, member))
    hints = cast("dict[str, object]", typing.get_type_hints(member_of))
    built: list[Parameter] = []
    for item in cast("list[dict[str, object]]", entry["parameters"]):
        name = cast("str", item["name"])
        if name not in hints:
            raise RuntimeError(
                f"the manifest gives {cls.__name__}.{member} an argument named {name!r} "
                "that its own signature does not declare"
            )
        declared = hints[name]
        client = declared if resume_state_for(declared) is not None else None
        checked = resume_state_for(declared) if client is not None else declared
        required = bool(item["required"])
        built.append(
            Parameter(
                name=name,
                required=required,
                validator=validator_of(required_type(checked) if required else checked),
                client=cast("type[object] | None", client),
            )
        )
    return tuple(built)


def _is_page(entry: dict[str, object]) -> bool:
    """Say whether the manifest describes the result as one page.

    Args:
        entry: The manifest operation entry.

    Returns:
        True when the result schema is a page of items and a cursor.
    """
    return cast("dict[str, object]", entry["returns"]).get("title") == PAGE_TITLE


def _is_token(entry: dict[str, object]) -> bool:
    """Say whether the manifest describes the result as a fresh token.

    Args:
        entry: The manifest operation entry.

    Returns:
        True when the result schema is the token and its state together.
    """
    return (
        cast("dict[str, object]", entry["returns"]).get("title")
        == GENERATED_TOKEN_TITLE
    )


def _operation(entry: dict[str, object]) -> Operation:
    """Build one row of the dispatch table.

    Args:
        entry: The manifest operation entry.

    Returns:
        The operation, ready to be called.
    """
    identifier = cast("str", entry["id"])
    prefix, member = identifier.split(".")[:2]
    cls = _CLASS_BY_PREFIX[prefix]
    bindable = prefix not in UNBOUND_PREFIXES
    parameters = _parameters_of(cls, member, entry)
    names = {parameter.name for parameter in parameters}
    if _is_page(entry):
        names.add(CURSOR)
    return Operation(
        id=identifier,
        prefix=prefix,
        member=member,
        state_model=_STATE_BY_PREFIX[prefix],
        parameters=parameters,
        names=frozenset(names),
        required=frozenset(
            parameter.name for parameter in parameters if parameter.required
        ),
        attribute=_is_attribute(cls, member),
        constructor=_is_constructor(cls, member),
        page=_is_page(entry),
        token=_is_token(entry),
        bindable=bindable,
    )


@functools.cache
def _table() -> dict[str, Operation]:
    """Walk the manifest once per process and index the operations by id.

    Returns:
        One row per operation the manifest reports as public and callable.
    """
    entries = cast("list[dict[str, object]]", build_manifest()["operations"])
    built = [_operation(entry) for entry in entries]
    return {operation.id: operation for operation in built}


def operations() -> dict[str, Operation]:
    """Return every dispatchable operation, keyed by its manifest id.

    Returns:
        The table built from the manifest.
    """
    return _table()


def lookup(op: str) -> Operation | None:
    """Find one operation by id.

    Args:
        op: The id the caller asked for.

    Returns:
        The operation, or ``None`` when no operation carries that id.
    """
    return _table().get(op)
