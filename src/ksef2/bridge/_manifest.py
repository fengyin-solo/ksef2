"""Build the machine-readable manifest of the public sync API.

The manifest is one JSON document: every public sync method or property of the
walked classes is either an operation with JSON Schema parameters and result, or
an exclusion that says why it is not. Live objects are replaced by the state a
caller saves and hands back, so a language binding can drive the SDK without
holding a Python object.
"""

import inspect
import json
import types
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property, reduce
from operator import or_
from typing import Final, cast

import ksef2

from ksef2 import KSeFException

from ksef2.bridge._catalog import (
    DATA_FORMS,
    EXCLUDED_CLASSES,
    EXCLUDED_MEMBERS,
    GENERATED_TOKEN_CLASS,
    GENERATED_TOKEN_FIELD,
    WALKED_CLASSES,
    WalkedClass,
    is_pager,
    typevar_bindings,
)
from ksef2.bridge._errors import (
    HandsBackAnotherClient,
    ManifestError,
    UnsupportedSignature,
)
from ksef2.bridge._schemas import Schema, SchemaBuilder, ref_names

FORMAT_VERSION: Final = 1
"""Version of the manifest document itself."""

CURSOR_PARAMETER: Final = "cursor"
"""Parameter every collection operation takes to choose the page it returns."""

EXCLUDED_DEPRECATED: Final = "deprecated"
EXCLUDED_CONTEXT_MANAGER: Final = "context manager protocol"
EXCLUDED_CLIENT: Final = "returns another client; its methods are separate operations"
EXCLUDED_SIGNATURE: Final = "no JSON schema for this signature"
"""Reasons an excluded member is reported, each naming the rule that applied."""

SENSITIVE_PARAMETERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "credentials",
        "key_password",
        "key_pem",
        "password",
        "private_key",
        "refresh_token",
        "token",
    }
)
"""Parameter names that always name a secret.

``credentials`` is the ``XAdESCredentials`` model, which keeps the signing key as
unencrypted PEM, so the parameter is a secret as a whole rather than in part.
"""

SENSITIVE_STATE_MODEL: Final = "AuthenticationResumeState"
"""Saved state whose presence makes a whole parameter, or a result, sensitive."""

SENSITIVE_RESULT_NAME: Final = "state"
"""Name given to a result that is authentication state."""

_NO_KEYWORD: Final = "no_arguments"
"""Id suffix for an overload that takes no keyword of its own."""


@dataclass(frozen=True)
class _Parameter:
    """One declared parameter of one callable form.

    Attributes:
        name: Parameter name as callers spell it.
        annotation: Evaluated annotation, or ``None`` when undeclared.
        default: Declared default, or ``inspect.Parameter.empty``.
    """

    name: str
    annotation: object
    default: object


@dataclass(frozen=True)
class _Form:
    """One callable form of a member: the implementation, or one ``@overload``.

    Attributes:
        keyword: Distinguishing keyword that names this form in an id, or
            ``None`` when the member has a single form.
        parameters: Declared parameters in signature order, without ``self``.
        returns: Evaluated return annotation, or ``None`` when undeclared.
    """

    keyword: str | None
    parameters: tuple[_Parameter, ...]
    returns: object


def _public_names(cls: type[object]) -> list[str]:
    """List the member names a manifest reader can reach on the class."""
    return [name for name in dir(cls) if not name.startswith("_")]


def _callable_of(member: object) -> object | None:
    """Return the function whose signature describes a member."""
    if isinstance(member, property):
        return cast("object | None", member.fget)
    if isinstance(member, cached_property):
        return cast("object", member.func)
    if isinstance(member, classmethod | staticmethod):
        return cast("object", member.__func__)
    if callable(member):
        return member
    return None


def _document(function: object) -> str:
    """Return the first line of a member's docstring."""
    if function is None:
        return ""
    doc = cast("object | None", getattr(function, "__doc__", None))
    if not isinstance(doc, str):
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _overload_forms(cls: type[object], name: str) -> list[_Form]:
    """Read registered overloads, naming each by its first declared parameter."""
    fn = _callable_of(cast("object", getattr(cls, name)))
    if fn is None:
        return []
    forms: list[_Form] = []
    for overload in typing.get_overloads(cast("Callable[..., object]", fn)):
        form = _implementation_form(overload)
        forms.append(
            _Form(
                keyword=form.parameters[0].name if form.parameters else _NO_KEYWORD,
                parameters=form.parameters,
                returns=form.returns,
            )
        )
    return forms


def _implementation_form(fn: object) -> _Form:
    """Build a form from a callable's runtime signature."""
    signature = inspect.signature(cast("Callable[..., object]", fn))
    hints = cast(
        "dict[str, object]",
        typing.get_type_hints(cast("Callable[..., object]", fn)),
    )
    parameters: list[_Parameter] = []
    for name, parameter in signature.parameters.items():
        if name in ("self", "cls"):
            continue
        annotation = hints.get(name, cast("object", parameter.annotation))
        if annotation is inspect.Parameter.empty:
            annotation = None
        parameters.append(
            _Parameter(
                name=name,
                annotation=annotation,
                default=cast("object", parameter.default),
            )
        )
    return _Form(
        keyword=None,
        parameters=tuple(parameters),
        returns=hints.get("return", cast("object", signature.return_annotation)),
    )


def _without_none(annotation: object) -> object:
    """Return the type a parameter the caller must supply accepts.

    Required data-form parameters exclude ``None``, which the Python signature
    allows only to support the other form.
    """
    alternatives: tuple[object, ...] = typing.get_args(annotation)
    kept: tuple[object, ...] = tuple(
        item for item in alternatives if item is not types.NoneType
    )
    if len(kept) == len(alternatives):
        return annotation
    if len(kept) == 1:
        return kept[0]
    return cast("object", reduce(or_, kept))


def _as_data_form(cls: type[object], name: str, form: _Form) -> _Form:
    """Rewrite a member's form into the one a caller sends as data.

    Live cryptography parameters give way to the required data model, because its
    ``None`` default only indicates that the other form was used.
    Forms already using only data remain unchanged.
    A declared data-form parameter absent from the signature raises ``ManifestError``.
    """
    declared = DATA_FORMS.get((cls, name))
    if declared is None:
        return form
    known = {parameter.name for parameter in form.parameters}
    unknown = sorted((declared.live | declared.required) - known)
    if unknown:
        raise ManifestError(
            f"the data form of {cls.__name__}.{name} names parameters the signature "
            "does not have: " + ", ".join(unknown)
        )
    contradictory = sorted(declared.live & declared.required)
    if contradictory:
        raise ManifestError(
            f"the data form of {cls.__name__}.{name} requires parameters it also "
            "drops: " + ", ".join(contradictory)
        )
    parameters = [
        _Parameter(
            name=parameter.name,
            annotation=(
                _without_none(parameter.annotation)
                if parameter.name in declared.required
                else parameter.annotation
            ),
            default=(
                inspect.Parameter.empty
                if parameter.name in declared.required
                else parameter.default
            ),
        )
        for parameter in form.parameters
        if parameter.name not in declared.live
    ]
    return _Form(
        keyword=form.keyword, parameters=tuple(parameters), returns=form.returns
    )


def _forms_of(cls: type[object], name: str, member: object) -> list[_Form]:
    """Collect every callable form of a member.

    Registered overloads take precedence over the runtime signature, and all forms
    are narrowed to the data a caller can send.
    """
    fn = _callable_of(member)
    if fn is None:
        return []
    overloads = _overload_forms(cls, name)
    if overloads:
        return [_as_data_form(cls, name, form) for form in overloads]
    return [_as_data_form(cls, name, _implementation_form(fn))]


def _is_json_scalar(value: object) -> bool:
    """Say whether a declared default can appear in JSON unchanged.

    Callables and object instances are left out: they describe what Python would
    do, not what a caller would send.
    """
    return value is None or type(value) in (bool, int, float, str)


def _parameter_entries(
    builder: SchemaBuilder,
    form: _Form,
    bindings: dict[object, object],
    owner: type[object],
) -> list[Schema]:
    """Describe the parameters of one form.

    A parameter without JSON Schema raises ``UnsupportedSignature``, while a live
    object without a saved form raises ``HandsBackAnotherClient``.
    """
    entries: list[Schema] = []
    for parameter in form.parameters:
        if parameter.annotation is None:
            raise UnsupportedSignature(parameter.name)
        schema = builder.schema_of(parameter.annotation, bindings, owner=owner)
        entry: Schema = {
            "name": parameter.name,
            "required": parameter.default is inspect.Parameter.empty,
            "schema": schema,
        }
        if parameter.default is not inspect.Parameter.empty and _is_json_scalar(
            parameter.default
        ):
            entry["default"] = parameter.default
        entries.append(entry)
    return entries


def _reachable_definitions(builder: SchemaBuilder, names: set[str]) -> set[str]:
    """Close a set of schema names over the references they make."""
    seen: set[str] = set()
    pending = list(names)
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        definition = builder.definition(name)
        if definition is not None:
            pending.extend(ref_names(definition) - seen)
    return seen


def _sensitive_names(
    builder: SchemaBuilder,
    member: str,
    entries: Sequence[Mapping[str, object]],
    returns: Schema,
    *,
    hands_back_token: bool,
) -> list[str]:
    """List the names in one operation that carry secrets.

    A name appears when it is a known secret parameter, when the member itself is
    a secret the receiver holds, when a parameter or the result is authentication
    state as a whole, when the result is a one-time token, or when a schema the
    operation touches keeps that field out of ``repr()``.
    """
    names: set[str] = set()
    returned_refs = ref_names(returns)
    if member in SENSITIVE_PARAMETERS:
        names.add(member)
    for entry in entries:
        name = cast("str", entry["name"])
        if name in SENSITIVE_PARAMETERS:
            names.add(name)
        if SENSITIVE_STATE_MODEL in ref_names(entry["schema"]):
            names.add(name)
    if SENSITIVE_STATE_MODEL in returned_refs:
        names.add(SENSITIVE_RESULT_NAME)
    if hands_back_token:
        names.add(GENERATED_TOKEN_FIELD)
    touched = _reachable_definitions(
        builder,
        returned_refs | {n for entry in entries for n in ref_names(entry["schema"])},
    )
    for definition in touched:
        names.update(builder.sensitive_field_names(definition))
    return sorted(names)


def _operation(
    builder: SchemaBuilder,
    target: WalkedClass,
    name: str,
    form: _Form,
    summary: str,
    bindings: dict[object, object],
    state: Schema | None,
) -> dict[str, object]:
    """Build one operation entry.

    A signature without JSON Schema raises ``UnsupportedSignature``, a client result
    raises ``HandsBackAnotherClient``, and a collection member that already declares
    a cursor parameter raises ``ManifestError``.
    """
    entries = _parameter_entries(builder, form, bindings, target.cls)
    if is_pager(form.returns):
        if any(parameter.name == CURSOR_PARAMETER for parameter in form.parameters):
            raise ManifestError(
                f"{target.prefix}.{name} already declares {CURSOR_PARAMETER!r}"
            )
        entries.append(
            {
                "name": CURSOR_PARAMETER,
                "required": False,
                "default": None,
                "schema": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            }
        )
    returns = builder.schema_of(form.returns, bindings, returns=True, owner=target.cls)
    identifier = f"{target.prefix}.{name}"
    if form.keyword is not None:
        identifier = f"{identifier}.{form.keyword}"
    return {
        "id": identifier,
        "receiver": target.receiver,
        "summary": summary,
        "parameters": entries,
        "returns": returns,
        "state_schema": state,
        "sensitive": _sensitive_names(
            builder,
            name,
            entries,
            returns,
            hands_back_token=form.returns is GENERATED_TOKEN_CLASS,
        ),
    }


def _walk_class(
    builder: SchemaBuilder, target: WalkedClass
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Turn one walked class into operations and exclusions."""
    operations: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    bindings = typevar_bindings(target.cls)
    state = (
        None
        if target.state_model is None or target.cls in EXCLUDED_CLASSES
        else builder.state_ref(target.state_model)
    )
    for name in _public_names(target.cls):
        member = cast("object", getattr(target.cls, name))
        if hasattr(member, "__deprecated__"):
            excluded.append(_excluded(target, name, EXCLUDED_DEPRECATED))
            continue
        reason = EXCLUDED_CLASSES.get(target.cls)
        if reason is None:
            reason = EXCLUDED_MEMBERS.get((target.cls, name))
        if reason is not None:
            excluded.append(_excluded(target, name, reason))
            continue
        forms = _forms_of(target.cls, name, member)
        if not forms:
            excluded.append(_excluded(target, name, EXCLUDED_SIGNATURE))
            continue
        summary = _document(_callable_of(member))
        built: list[dict[str, object]] = []
        failure: str | None = None
        for form in forms:
            try:
                built.append(
                    _operation(builder, target, name, form, summary, bindings, state)
                )
            except HandsBackAnotherClient:
                failure = EXCLUDED_CLIENT
                break
            except UnsupportedSignature:
                failure = EXCLUDED_SIGNATURE
                break
            except ManifestError:
                # A schema clash is a broken public API, not a reason to drop a
                # member from the document.
                raise
        if failure is None:
            operations.extend(built)
        else:
            excluded.append(_excluded(target, name, failure))
    for name in ("__enter__", "__exit__"):
        if hasattr(target.cls, name):
            excluded.append(_excluded(target, name, EXCLUDED_CONTEXT_MANAGER))
    return operations, excluded


def _excluded(target: WalkedClass, name: str, reason: str) -> dict[str, object]:
    """Build one exclusion entry."""
    return {"id": f"{target.prefix}.{name}", "reason": reason}


def exception_catalogue() -> list[dict[str, object]]:
    """List every exported exception with its code and its parent.

    ``ExceptionCode`` is a code list and not an exception, so it never appears.
    ``KSeFArgumentError`` parents ``KSeFValidationError`` even though it is also
    a ``TypeError``, because the SDK family is what a caller catches.

    Returns:
        One entry per exported ``KSeFException`` subclass, sorted by name.
    """
    entries: list[dict[str, object]] = []
    for name in ksef2.__all__:
        member = cast("object", getattr(ksef2, name))
        if not isinstance(member, type) or not issubclass(member, KSeFException):
            continue
        parent = next(
            (
                base.__name__
                for base in member.__mro__[1:]
                if issubclass(base, KSeFException)
            ),
            None,
        )
        entries.append(
            {
                "name": member.__name__,
                "code": member.code,
                "parent": parent,
            }
        )
    entries.sort(key=lambda entry: cast("str", entry["name"]))
    return entries


def _reject_non_json(value: object, path: str) -> None:
    """Refuse a manifest value that ``json.dumps`` could not write faithfully.

    Non-JSON data raises ``ManifestError``.
    """
    if value is None or type(value) in (str, bool, int, float):
        return
    if isinstance(value, dict):
        for key, item in cast("dict[object, object]", value).items():
            if not isinstance(key, str):
                raise ManifestError(f"{path} has a {type(key).__name__} key")
            _reject_non_json(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(cast("list[object]", value)):
            _reject_non_json(item, f"{path}[{index}]")
        return
    raise ManifestError(f"{path} holds {type(value).__name__}, which is not JSON data")


def render(data: Mapping[str, object]) -> str:
    """Serialize a manifest the way the command line prints it.

    Args:
        data: Manifest built by ``manifest()``.

    Returns:
        Sorted, indented JSON with one trailing newline.
    """
    return json.dumps(data, sort_keys=True, indent=2) + "\n"


def build_manifest() -> dict[str, object]:
    """Build the manifest of the public sync API.

    Returns:
        Plain JSON-compatible data describing every walked member.

    Raises:
        ManifestError: Two schemas would share one name, one id would describe
            two members, a reference would point at nothing, or a value is not
            JSON data.
    """
    builder = SchemaBuilder()
    operations: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for target in WALKED_CLASSES:
        class_operations, class_exclusions = _walk_class(builder, target)
        operations.extend(class_operations)
        excluded.extend(class_exclusions)
    operations.sort(key=lambda entry: cast("str", entry["id"]))
    excluded.sort(key=lambda entry: cast("str", entry["id"]))
    data: dict[str, object] = {
        "format_version": FORMAT_VERSION,
        "ksef2_version": ksef2.__version__,
        "operations": operations,
        "excluded": excluded,
        "exceptions": exception_catalogue(),
        "$defs": builder.defs,
    }
    _reject_non_json(data, "$")
    _check_unique(operations, excluded)
    _check_refs(data)
    return data


def _check_unique(
    operations: Sequence[Mapping[str, object]],
    excluded: Sequence[Mapping[str, object]],
) -> None:
    """Refuse an id that two entries claim.

    An id repeated within or across the two lists raises ``ManifestError``.
    """
    seen: dict[str, str] = {}
    for kind, entries in (("operation", operations), ("exclusion", excluded)):
        for entry in entries:
            identifier = cast("str", entry["id"])
            if identifier in seen:
                raise ManifestError(
                    f"{identifier!r} is reported twice ({seen[identifier]} and "
                    f"{kind}); one id must describe one member"
                )
            seen[identifier] = kind


def _check_refs(data: Mapping[str, object]) -> None:
    """Refuse a reference that points at no schema.

    A ``$ref`` absent from ``$defs`` raises ``ManifestError``.
    """
    definitions = cast("Mapping[str, object]", data["$defs"])
    missing = sorted(ref_names(data) - set(definitions))
    if missing:
        raise ManifestError(
            "these references have no entry in $defs: " + ", ".join(missing)
        )
