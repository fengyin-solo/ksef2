"""Build the machine-readable manifest of the public synchronous SDK API.

The manifest is assembled from ``ksef2.clients`` itself: each public sync class
becomes a unit, each non-deprecated public method becomes an operation or lands
in ``excluded`` with a reason, and every parameter, return value and state gets a
JSON Schema. See ``ksef2.bridge`` for the public entry points.
"""

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from typing import Self, cast

from pydantic import BaseModel

from ksef2 import __version__ as ksef2_version
from ksef2._clients._pager import Pager
from ksef2._core import exceptions
from ksef2._domain.models.pagination import Page
from ksef2.bridge._api import (
    CONVENTIONS,
    UNITS,
    EXCLUSIONS,
    KIND_PAGER,
    REASON_DEPRECATED,
    REASON_PYTHON_ONLY,
    STATES,
    Exclusion,
    Unit,
)
from ksef2.bridge._data import (
    JsonObject,
    argument_descriptions,
    as_list,
    as_object,
    first_summary,
    require_json,
)
from ksef2.bridge._schema import (
    DEF_PREFIX,
    SCHEMA_DIALECT,
    TYPE_PARAMETER,
    Schemas,
    SchemaBuilder,
    T,
    UndescribableType,
    item_type_of,
    reference_to,
    resolve_type,
)

FORMAT_VERSION = "1.0"
"""Version of the manifest layout. A generator reads it before parsing."""

_GENERATOR = "ksef2.bridge.manifest"
_ORIGIN_SIGNATURE = "signature"
_ORIGIN_UNIT_STATE = "unit_state"
_STATE_ARGUMENT = "state"
_STATE_ARGUMENT_DESCRIPTION = (
    "State of the live object the operation runs on. The Python client holds it;"
    " a stateless caller passes what it saved from the operation that created the"
    " object."
)
_KIND_VALUE = "value"
_KIND_NONE = "none"
_KIND_PAGED = "paged"
_KIND_DATA = "data"
_KIND_BRANCH = "branch"
_NONE_SCHEMA: JsonObject = {"type": "null"}


@dataclass(frozen=True)
class _Member:
    """One public member of a public sync class.

    Attributes:
        unit: Unit of the class that declares or inherits it.
        name: Attribute name in Python.
        kind: ``method``, ``classmethod``, ``property`` or ``attribute``.
        function: Function behind the member; ``None`` for a plain attribute.
        summary: First docstring line of the member.
        deprecated: PEP 702 deprecation message, when the member is deprecated.
    """

    unit: Unit
    name: str
    kind: str
    function: Callable[..., object] | None
    summary: str
    deprecated: str | None


@dataclass
class _Returns:
    """How the result of an operation is described.

    Attributes:
        kind: ``value``, ``none``, ``paged``, ``data``, ``handle``, ``session``
            or ``client``.
        unit: Unit named by the result, when it returns a live object.
        page_name: Name of the ``Page`` definition a paged result returns, whose
            item schema is recorded on the operation once it exists.
        schema: Result schema the manifest already holds, such as the null schema.
        value_key: Request key that holds the result schema once generated.
    """

    kind: str
    unit: str | None = None
    page_name: str | None = None
    schema: JsonObject | None = None
    value_key: str | None = None


@dataclass
class _OperationPlan:
    """Preparation of one operation, before its schemas exist.

    Attributes:
        member: Member the operation describes.
        params_key: Request key of its signature.
        state_model: Resume-state model injected as ``state``, when there is one.
        returns: Description of its result.
        descriptions: Docstring description of each parameter.
    """

    member: _Member
    params_key: str
    state_model: type[BaseModel] | None
    returns: _Returns
    descriptions: dict[str, str] = field(default_factory=dict)


@dataclass
class _AttributePlan:
    """Preparation of one attribute, before its schema exists.

    Attributes:
        member: Property the attribute describes.
        unit: Unit the property returns, when it is a branch accessor.
        value_key: Request key holding the schema of its value.
    """

    member: _Member
    unit: str | None = None
    value_key: str | None = None


@dataclass
class _ExcludedPlan:
    """One member the manifest lists instead of describing.

    Attributes:
        member: Member left out of the operations.
        exclusion: Reason and detail recorded for it.
    """

    member: _Member
    exclusion: Exclusion


type _Plan = _OperationPlan | _AttributePlan | UndescribableType
"""What the builder found out about one member: an operation, an attribute, or
the reason the member cannot be described."""


def manifest() -> JsonObject:
    """Build the manifest of the public synchronous API.

    Returns:
        Plain JSON-compatible data: the header, the states, one entry per public
        sync class, one operation per bindable method, the attributes those
        classes expose, the members left out with their reasons and the shared
        ``$defs`` registry.

    Raises:
        KSeFException: If a public class is missing from the bridge tables, or if
            pydantic produces something that is not JSON data.
    """
    _check_units()
    builder = SchemaBuilder()
    operations: list[_OperationPlan] = []
    attributes: list[_AttributePlan] = []
    excluded: list[_ExcludedPlan] = []

    for unit in sorted(UNITS, key=lambda item: item.id):
        for member in _members(unit):
            exclusion = _exclusion_for(member)
            if exclusion is not None:
                excluded.append(_ExcludedPlan(member, exclusion))
                continue
            planned = _plan(member, builder)
            if isinstance(planned, _OperationPlan):
                operations.append(planned)
            elif isinstance(planned, _AttributePlan):
                attributes.append(planned)
            else:
                excluded.append(_ExcludedPlan(member, _python_only(planned)))

    schemas = builder.build()
    generated = _Generated(schemas)
    operation_entries = generated.operations(operations)
    attribute_entries = generated.attributes(attributes)
    unit_entries = _unit_entries(generated)
    return {
        "format_version": FORMAT_VERSION,
        "generated_by": _GENERATOR,
        "ksef2_version": ksef2_version,
        "json_schema_dialect": SCHEMA_DIALECT,
        "conventions": {name: text for name, text in CONVENTIONS},
        "states": [{"name": name, "description": text} for name, text in STATES],
        "units": unit_entries,
        "operations": operation_entries,
        "attributes": attribute_entries,
        "excluded": _excluded_entries(excluded),
        "$defs": schemas.definitions,
    }


def public_sync_classes() -> list[type[object]]:
    """Return the public sync classes of ``ksef2.clients``.

    Async twins and the module-level deprecated aliases are left out: the
    manifest describes the synchronous surface that bindings are generated from.

    Returns:
        The classes, sorted by name.
    """
    import ksef2.clients as clients

    found: list[type[object]] = []
    for name in _public_names(clients):
        value = cast("object", getattr(clients, name))
        if inspect.isclass(value) and not name.startswith("Async"):
            found.append(cast("type[object]", value))
    found.sort(key=lambda item: item.__name__)
    return found


def _public_names(clients: object) -> list[str]:
    """Return the names listed in a module's ``__all__``.

    Args:
        clients: Module whose public names are read.

    Returns:
        Its declared public names.
    """
    declared = cast("object", getattr(clients, "__all__", []))
    return [str(name) for name in as_list(declared)]


def _check_units() -> None:
    """Fail when the public classes and the bridge tables disagree.

    A class added to ``ksef2.clients`` without a unit, or a unit whose class left
    the public surface, would silently make the manifest incomplete.

    Raises:
        KSeFException: If some public class has no unit, or some unit describes no
            public class.
    """
    public = public_sync_classes()
    declared = {unit.cls for unit in UNITS}
    missing = [klass.__name__ for klass in public if klass not in declared]
    extra = sorted(
        unit.cls.__name__
        for unit in UNITS
        if not any(unit.cls is klass for klass in public)
    )
    if missing or extra:
        raise exceptions.KSeFException(
            "The bridge manifest does not cover the public sync API evenly.",
            hint="Update the unit table in ksef2/bridge/_api.py.",
            missing=", ".join(missing),
            undeclared=", ".join(extra),
        )


def _members(unit: Unit) -> list[_Member]:
    """Return the public members of a unit's class.

    Args:
        unit: Unit whose class is inspected.

    Returns:
        Its public methods, class methods and properties, sorted by name.
    """
    members: list[_Member] = []
    for found in inspect.getmembers(unit.cls):
        name: str = found[0]
        if name.startswith("_"):
            continue
        value = cast("object", found[1])
        members.append(_member(unit, name, value))
    return members


def _member(unit: Unit, name: str, value: object) -> _Member:
    """Classify one attribute of a unit's class.

    Args:
        unit: Unit that owns the attribute.
        name: Attribute name.
        value: Value of the attribute.

    Returns:
        The member, with its summary and its deprecation message.
    """
    kind: str
    function: Callable[..., object] | None
    if isinstance(value, property):
        kind, function = "property", value.fget
    elif isinstance(value, cached_property):
        kind, function = "property", value.func
    elif inspect.ismethod(value) and getattr(value, "__self__", None) is unit.cls:
        kind, function = "classmethod", cast("Callable[..., object]", value)
    elif isinstance(value, classmethod | staticmethod):
        wrapped = cast("object", value.__func__)
        kind, function = "classmethod", cast("Callable[..., object]", wrapped)
    elif inspect.isfunction(value):
        kind, function = "method", value
    else:
        kind, function = "attribute", None
    return _Member(
        unit=unit,
        name=name,
        kind=kind,
        function=function,
        summary=first_summary(None if function is None else function.__doc__),
        deprecated=_deprecation(function),
    )


def _deprecation(function: Callable[..., object] | None) -> str | None:
    """Return the PEP 702 deprecation message of a member.

    Args:
        function: Function behind the member, or ``None``.

    Returns:
        The message ``typing_extensions.deprecated`` recorded, or ``None`` when
        the member is current.
    """
    if function is None:
        return None
    message = getattr(function, "__deprecated__", None)
    return message if isinstance(message, str) else None


def _exclusion_for(member: _Member) -> Exclusion | None:
    """Return the reason a member is not described.

    Args:
        member: Member to check.

    Returns:
        Its deprecation message or its declared exclusion, or ``None`` when the
        manifest describes it.
    """
    if member.deprecated is not None:
        return Exclusion(REASON_DEPRECATED, member.deprecated)
    return EXCLUSIONS.get(member.unit.id, {}).get(member.name)


def _python_only(reason: UndescribableType) -> Exclusion:
    """Build the exclusion of a member whose types are not JSON data.

    Args:
        reason: What the schema builder could not describe.

    Returns:
        An exclusion that names the type and points at the bridge tables.
    """
    return Exclusion(
        REASON_PYTHON_ONLY,
        f"{reason.detail} has no JSON Schema. Declare the member in"
        " ksef2/bridge/_api.py with the reason it is left out.",
    )


def _plan(member: _Member, builder: SchemaBuilder) -> _Plan:
    """Prepare one member for the manifest.

    Args:
        member: Member to describe.
        builder: Schema builder to queue schema requests with.

    Returns:
        The prepared operation, the prepared attribute, or the reason the member
        cannot be described.
    """
    if member.kind == "attribute" or member.function is None:
        return UndescribableType(f"The member {member.name} is not a method")
    try:
        signature = inspect.signature(member.function, eval_str=True)
    except (TypeError, ValueError, NameError) as error:
        return UndescribableType(f"The signature of {member.name} reads as {error}")
    return (
        _plan_attribute(member, builder, signature)
        if member.kind == "property"
        else _plan_operation(member, builder, signature)
    )


def _plan_operation(
    member: _Member, builder: SchemaBuilder, signature: inspect.Signature
) -> _OperationPlan | UndescribableType:
    """Prepare a method or class method as an operation.

    Args:
        member: Method to describe.
        builder: Schema builder to queue schema requests with.
        signature: Readable signature of the method.

    Returns:
        The prepared operation, or the reason it cannot be described.
    """
    unit = member.unit
    fields: dict[str, tuple[object, object]] = {}
    for name, parameter in signature.parameters.items():
        if name in ("self", "cls"):
            continue
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            return UndescribableType(
                f"{member.name} takes extra arguments through *{name}"
            )
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return UndescribableType(
                f"{member.name} takes extra arguments through **{name}"
            )
        try:
            annotation = resolve_type(
                cast("object", parameter.annotation), item=_item_of(unit)
            )
        except UndescribableType as error:
            return error
        fields[name] = (annotation, cast("object", parameter.default))
    key = f"params:{unit.id}.{member.name}"
    builder.add_parameters(key, fields)
    try:
        returns = _plan_returns(
            member, cast("object", signature.return_annotation), builder
        )
    except UndescribableType as error:
        return error
    return _OperationPlan(
        member=member,
        params_key=key,
        state_model=_receiver_state(unit, member),
        returns=returns,
        descriptions=argument_descriptions(
            member.function.__doc__ if member.function else None
        ),
    )


def _plan_returns(
    member: _Member, annotation: object, builder: SchemaBuilder
) -> _Returns:
    """Describe the result of an operation.

    Args:
        member: Method whose return annotation is described.
        annotation: Return annotation of the method.
        builder: Schema builder to queue schema requests with.

    Returns:
        The description of its result.

    Raises:
        UndescribableType: If neither a JSON Schema nor a live-object description
            fits the annotation.
    """
    unit = member.unit
    if annotation is None or annotation is type(None):
        return _Returns(kind=_KIND_NONE, schema=dict(_NONE_SCHEMA))
    if annotation is inspect.Parameter.empty:
        raise UndescribableType(f"{member.name} does not annotate what it returns")
    if annotation is Self:
        return _unit_descriptor(unit, builder)
    origin = cast("object | None", typing.get_origin(annotation))
    owner = annotation if origin is None else origin
    if isinstance(owner, type) and issubclass(owner, Pager):
        pager = cast("type[object]", owner)
        return _paged_returns(
            _pager_unit(pager, member), item_type_of(annotation), builder
        )
    target = _unit_of(cast("object", owner))
    if target is not None:
        return _unit_descriptor(target, builder)
    if isinstance(owner, type) and issubclass(owner, Page):
        return _paged_returns(unit, item_type_of(annotation), builder)
    resolved = resolve_type(annotation, item=_item_of(unit))
    key = f"return:{unit.id}.{member.name}"
    builder.add_value(key, resolved)
    return _Returns(kind=_KIND_VALUE, value_key=key)


def _pager_unit(owner: type[object], member: _Member) -> Unit:
    """Return the pager unit a returned pager class belongs to.

    Args:
        owner: Pager class the operation returns.
        member: Method that returns it, used to name the class in an error.

    Returns:
        The unit of that pager class.

    Raises:
        UndescribableType: If the class is not a unit of the public surface.
    """
    unit = _unit_of(owner)
    if unit is None or unit.kind != KIND_PAGER:
        raise UndescribableType(f"{_type_name(owner)}, which {member.name} returns")
    return unit


def _paged_returns(unit: Unit, item: object | None, builder: SchemaBuilder) -> _Returns:
    """Describe an operation that returns a pager.

    A pager is described by the page it hands out: the items of one page and the
    cursor that resumes the collection. Its item type is the one the returned
    pager carries, or the unit's own item type when the annotation leaves the
    type variable open.

    Args:
        unit: Pager unit the operation returns.
        item: Item type named by the returned annotation, when it names one.
        builder: Schema builder to queue schema requests with.

    Returns:
        The paged description, whose result schema is the ``Page`` of that item.
    """
    item_type = unit.item_model if unit.item_model is not None else T
    if item is not None and not isinstance(item, typing.TypeVar):
        item_type = cast("type[object]", item)
    name = _definition_name(item_type)
    key = f"page:{name}"
    builder.add_value(key, cast("object", Page[item_type]))
    return _Returns(kind=_KIND_PAGED, unit=unit.id, page_name=name, value_key=key)


def _unit_descriptor(unit: Unit, builder: SchemaBuilder) -> _Returns:
    """Describe an operation that returns a live object of ``unit``.

    Args:
        unit: Unit of the returned object.
        builder: Schema builder to queue schema requests with.

    Returns:
        A description that names the unit and points at the data carrying it.

    Raises:
        UndescribableType: If the unit has no data form to point at.
    """
    if unit.kind == KIND_PAGER:
        return _paged_returns(unit, None, builder)
    model = unit.receiver_state if unit.receiver_state is not None else unit.data_model
    if model is None:
        raise UndescribableType(f"{_type_name(unit.cls)}, which has no state model")
    key = f"unit:{unit.id}"
    builder.add_value(key, model)
    return _Returns(
        kind=_KIND_DATA if unit.data_model is not None else unit.kind,
        unit=unit.id,
        value_key=key,
    )


def _unit_of(annotation: object) -> Unit | None:
    """Return the unit a class belongs to, when it has one.

    Args:
        annotation: Class a member returns.

    Returns:
        Its unit, or ``None`` for a class outside the manifest.
    """
    if not isinstance(annotation, type):
        return None
    for unit in UNITS:
        if unit.cls is annotation:
            return unit
    return None


def _receiver_state(unit: Unit, member: _Member) -> type[BaseModel] | None:
    """Return the state an operation needs beyond its own arguments.

    Args:
        unit: Unit that owns the member.
        member: Operation being described.

    Returns:
        The unit's resume-state model, except for the operation that produces it.
    """
    if unit.receiver_state is None or member.name == "resume_state":
        return None
    return unit.receiver_state


def _plan_attribute(
    member: _Member, builder: SchemaBuilder, signature: inspect.Signature
) -> _AttributePlan | UndescribableType:
    """Prepare a property as an attribute of its unit.

    Args:
        member: Property to describe.
        builder: Schema builder to queue schema requests with.
        signature: Signature of its getter.

    Returns:
        The prepared attribute, or the reason it cannot be described.
    """
    unit = member.unit
    annotation = cast("object", signature.return_annotation)
    origin = cast("object | None", typing.get_origin(annotation))
    branch = _unit_of(annotation if origin is None else origin)
    if branch is not None:
        return _AttributePlan(member=member, unit=branch.id)
    try:
        resolved = resolve_type(annotation, item=_item_of(unit))
    except UndescribableType as error:
        return error
    key = f"attribute:{unit.id}.{member.name}"
    builder.add_value(key, resolved)
    return _AttributePlan(member=member, value_key=key)


def _item_of(unit: Unit) -> object | None:
    """Return the type that stands in for a unit's type parameters.

    Args:
        unit: Unit whose annotations may name a type variable.

    Returns:
        The item type the unit fixes, the type parameter placeholder for a
        generic pager, or ``None`` for a class with no type parameters.
    """
    if unit.kind != KIND_PAGER:
        return None
    return unit.item_model if unit.item_model is not None else T


def _definition_name(annotation: object) -> str:
    """Return the ``$defs`` name pydantic gives a type.

    Args:
        annotation: Type used in a schema.

    Returns:
        Its definition key, which is the placeholder name for a type variable.
    """
    return annotation.__name__ if isinstance(annotation, type) else TYPE_PARAMETER


def _type_name(annotation: object) -> str:
    """Return a readable name of a type.

    Args:
        annotation: Type to name.

    Returns:
        Its module-qualified name.
    """
    module = getattr(annotation, "__module__", "")
    qualifier = getattr(annotation, "__qualname__", repr(annotation))
    return f"{module}.{qualifier}"


class _Generated:
    """Turn the generated schemas into manifest entries.

    Live objects are recorded as they are created, so each unit says which
    members hand one out.

    Args:
        schemas: Schemas generated for every queued request.
    """

    def __init__(self, schemas: Schemas) -> None:
        """Keep the generated schemas."""
        self._schemas = schemas
        self._creators: dict[str, list[str]] = {}

    def operations(self, plans: list[_OperationPlan]) -> list[JsonObject]:
        """Return the ``operations`` section.

        Args:
            plans: Prepared operations.

        Returns:
            One entry per operation, sorted by identifier.
        """
        entries: list[JsonObject] = []
        for plan in plans:
            member = plan.member
            identifier = f"{member.unit.id}.{member.name}"
            returns: JsonObject = {"kind": plan.returns.kind}
            if plan.returns.unit is not None:
                returns["unit"] = plan.returns.unit
                # A paged operation names the unit it belongs to, so only an
                # operation that hands out another unit creates it.
                if plan.returns.unit != member.unit.id:
                    _ = self._creators.setdefault(plan.returns.unit, []).append(
                        identifier
                    )
            if plan.returns.page_name is not None:
                returns["item"] = self.item_of_page(plan.returns.page_name)
            returns["schema"] = self._returns_schema(plan)
            entries.append(
                {
                    "id": identifier,
                    "unit": member.unit.id,
                    "class": member.unit.cls.__name__,
                    "member": member.name,
                    "binding": member.kind,
                    "state": member.unit.state,
                    "summary": member.summary,
                    "params": self._params(plan),
                    "returns": returns,
                }
            )
        return sorted(entries, key=lambda entry: str(entry["id"]))

    def attributes(self, plans: list[_AttributePlan]) -> list[JsonObject]:
        """Return the ``attributes`` section.

        Args:
            plans: Prepared attributes.

        Returns:
            One entry per attribute, sorted by unit and member.
        """
        entries: list[JsonObject] = []
        for plan in plans:
            member = plan.member
            entry: JsonObject = {
                "unit": member.unit.id,
                "class": member.unit.cls.__name__,
                "member": member.name,
                "state": member.unit.state,
                "summary": member.summary,
            }
            if plan.unit is not None:
                entry["kind"] = _KIND_BRANCH
                entry["unit_ref"] = plan.unit
                _ = self._creators.setdefault(plan.unit, []).append(
                    f"{member.unit.id}.{member.name}"
                )
            else:
                entry["kind"] = _KIND_VALUE
                entry["schema"] = (
                    {}
                    if plan.value_key is None
                    else self._schemas.values[plan.value_key]
                )
            entries.append(entry)
        return sorted(
            entries,
            key=lambda entry: (
                str(as_object(entry)["unit"]),
                str(as_object(entry)["member"]),
            ),
        )

    def creators(self) -> dict[str, list[str]]:
        """Return which members hand out each live object.

        Returns:
            Member identifiers keyed by the unit they return.
        """
        return {
            unit: sorted(set(names)) for unit, names in sorted(self._creators.items())
        }

    def item_of_page(self, page_name: str) -> JsonObject:
        """Return the schema of one item of a page.

        The page model already carries the item schema in its definition, so the
        item of an operation is read back from it. That keeps the two equal for a
        model, which the definition only points at, and for a scalar such as
        ``bytes``, which has no definition of its own.

        Args:
            page_name: Name of the ``Page`` definition of the page.

        Returns:
            The schema of one item, either a reference or an inline schema.
        """
        key = f"page:{page_name}"
        if key not in self._schemas.values:
            return reference_to(page_name)
        reference = str(self._schemas.values[key].get("$ref", ""))
        page = as_object(self._schemas.definitions[reference[len(DEF_PREFIX) :]])
        properties = as_object(page["properties"])
        return as_object(as_object(properties["items"])["items"])

    def _params(self, plan: _OperationPlan) -> list[JsonObject]:
        """Return the parameters of one operation.

        Args:
            plan: Prepared operation.

        Returns:
            The injected state first, then the parameters of the Python signature.
        """
        params: list[JsonObject] = []
        state = plan.state_model
        if state is not None:
            params.append(
                {
                    "name": _STATE_ARGUMENT,
                    "origin": _ORIGIN_UNIT_STATE,
                    "required": True,
                    "schema": reference_to(state.__name__),
                    "description": _STATE_ARGUMENT_DESCRIPTION,
                }
            )
        for parameter in self._schemas.parameters[plan.params_key]:
            entry: JsonObject = {
                "name": parameter.name,
                "origin": _ORIGIN_SIGNATURE,
                "required": parameter.required,
                "schema": parameter.schema,
            }
            if parameter.has_default:
                entry["default"] = require_json(parameter.default)
            description = plan.descriptions.get(parameter.name)
            if description:
                entry["description"] = description
            params.append(entry)
        return params

    def _returns_schema(self, plan: _OperationPlan) -> JsonObject:
        """Return the schema of one operation's result.

        Args:
            plan: Prepared operation.

        Returns:
            Its result schema.
        """
        if plan.returns.schema is not None:
            return plan.returns.schema
        if plan.returns.value_key is None:
            return {}
        return self._schemas.values[plan.returns.value_key]


def _excluded_entries(plans: list[_ExcludedPlan]) -> list[JsonObject]:
    """Return the ``excluded`` section.

    Args:
        plans: Members left out of the operations.

    Returns:
        One entry per member, sorted by identifier.
    """
    entries: list[JsonObject] = []
    for plan in plans:
        member = plan.member
        entries.append(
            {
                "id": f"{member.unit.id}.{member.name}",
                "unit": member.unit.id,
                "class": member.unit.cls.__name__,
                "member": member.name,
                "kind": member.kind,
                "reason": plan.exclusion.reason,
                "detail": plan.exclusion.detail,
            }
        )
    return sorted(entries, key=lambda entry: str(entry["id"]))


def _unit_entries(generated: _Generated) -> list[JsonObject]:
    """Return the ``units`` section.

    Args:
        generated: Generated schemas, used for the schemas of live objects.

    Returns:
        One entry per unit, sorted by identifier.
    """
    creators = generated.creators()
    entries: list[JsonObject] = []
    for unit in sorted(UNITS, key=lambda item: item.id):
        entry: JsonObject = {
            "id": unit.id,
            "class": unit.cls.__name__,
            "kind": unit.kind,
            "state": unit.state,
            "summary": first_summary(unit.cls.__doc__),
            "accessors": [
                {"unit": accessor.unit, "member": accessor.member}
                for accessor in unit.accessors
            ],
            "created_by": creators.get(unit.id, []),
        }
        if unit.receiver_state is not None:
            entry["receiver_state"] = reference_to(unit.receiver_state.__name__)
        if unit.kind == KIND_PAGER:
            entry["item"] = generated.item_of_page(_definition_name(_item_of(unit)))
        entries.append(entry)
    return entries


def manifest_json(indent: int = 2) -> str:
    """Render the manifest as JSON text.

    The document is written in the order ``manifest`` builds it, so the same
    public API always produces the same bytes.

    Args:
        indent: Spaces per nesting level; 0 writes one compact line.

    Returns:
        The manifest as JSON.

    Raises:
        KSeFException: If ``indent`` is negative, or if the manifest cannot be
            built.
    """
    import json

    if indent < 0:
        raise exceptions.KSeFArgumentError(
            "The manifest indent cannot be negative.",
            hint="Use 0 for one compact line, or a positive number of spaces.",
            indent=indent,
        )
    document = manifest()
    if indent == 0:
        return json.dumps(document, separators=(",", ":"))
    return json.dumps(document, indent=indent)
