"""Contract tests for the machine-readable manifest of the public sync API.

The manifest is what a binding generator trusts instead of re-deriving the API
with ``inspect``, so these tests hold it to the rules in GitHub issue #270: plain
JSON data, valid JSON Schema 2020-12, a named enum for every ``Literal`` alias,
every non-deprecated public sync method either an operation or an ``excluded``
entry with a reason, and no Python-only type anywhere in it.
"""

import argparse
import enum
import inspect
import json
import math
import subprocess
import sys
import typing
from collections.abc import Iterator
from functools import cached_property
from pathlib import Path
from typing import Any, Self
import pytest
from jsonschema import Draft202012Validator

from ksef2 import KSeFArgumentError, KSeFException
from ksef2.bridge import FORMAT_VERSION, manifest, manifest_json
from ksef2.bridge import _manifest
from ksef2.bridge import __main__ as bridge_main
from ksef2.bridge.__main__ import build_parser, main
from ksef2.bridge._api import EXCLUSIONS, KIND_PAGER, REASONS, UNITS, Unit
from ksef2.bridge._data import (
    argument_descriptions,
    as_list,
    as_object,
    collect_refs,
    first_summary,
    require_json,
)
from ksef2.bridge._manifest import (
    Schemas,
    _check_units,
    _definition_name,
    _Generated,
    _Member,
    _OperationPlan,
    _pager_unit,
    _plan,
    _python_only,
    _Returns,
    _type_name,
    _unit_descriptor,
    public_sync_classes,
)
from ksef2.bridge._schema import (
    SCHEMA_DIALECT,
    TYPE_PARAMETER,
    SchemaBuilder,
    T,
    UndescribableType,
    _as_list,
    _is_scalar,
    _name_of,
    _is_open_item,
    _qualified_short_name,
    resolve_type,
)
from ksef2._clients._pager import Pager

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEF_PREFIX = "#/$defs/"

# One operation of each kind the manifest has to describe, so a change that
# breaks how a whole class of member is written fails with a readable name.
PLAIN_CALL = "tokens.get_status"
PAGED_CALL = "certificates.list"
HANDLE_CALL = "tokens.generate"
HANDLE_FOLLOW_UP = "generated_token.wait"
SESSION_STATE_CALL = "online_session.get_status"
SESSION_RESUME_CALL = "auth.resume"
EXPORT_RESULT_CALL = "export_job.wait"
PAGE_CALL = "pager.page"
LITERAL_ALIAS_PARAMETER = "auth.with_token"

LITERAL_ALIASES = (
    "ContextIdentifierType",
    "TokenPermission",
    "TokenStatus",
    "CertificateTypeValue",
    "CertificateStatusValue",
    "RevocationReason",
    "CertUsage",
    "AuthorizationPermissionType",
    "AuthorizationSubjectIdentifierType",
    "IndirectPermissionType",
    "CompressionType",
    "FormSchema",
    "SortOrder",
)


@pytest.fixture(scope="module")
def document() -> dict[str, object]:
    """Return the manifest, built once for this module.

    Returns:
        The manifest as loaded JSON data.
    """
    loaded = json.loads(manifest_json())
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def operations(document: dict[str, object]) -> dict[str, dict[str, object]]:
    """Return the operations keyed by identifier.

    Args:
        document: The manifest.

    Returns:
        One entry per operation identifier.
    """
    return _entries_by_id(document["operations"])


@pytest.fixture(scope="module")
def definitions(document: dict[str, object]) -> dict[str, object]:
    """Return the shared ``$defs`` registry.

    Args:
        document: The manifest.

    Returns:
        Definitions keyed by name.
    """
    assert isinstance(document["$defs"], dict)
    return document["$defs"]


def _entries_by_id(value: object) -> dict[str, dict[str, object]]:
    """Index a manifest list by its ``id`` key.

    Args:
        value: Value read from the manifest.

    Returns:
        Its entries keyed by identifier.
    """
    assert isinstance(value, list)
    entries = [entry for entry in value if isinstance(entry, dict)]
    return {str(entry["id"]): entry for entry in entries}


def _names(value: object) -> list[str]:
    """Return a manifest list as a list of strings.

    Args:
        value: Value read from the manifest.

    Returns:
        Its entries as strings.
    """
    assert isinstance(value, list)
    return [str(item) for item in value]


def _objects(value: object) -> list[dict[str, object]]:
    """Return a manifest list as a list of objects.

    Args:
        value: Value read from the manifest.

    Returns:
        Its object entries.
    """
    assert isinstance(value, list)
    return [entry for entry in value if isinstance(entry, dict)]


def _schema_entries(document: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    """Return every schema the manifest carries, with a name for failures.

    Args:
        document: The manifest.

    Returns:
        Each schema together with where it was found.
    """
    found: list[tuple[str, dict[str, object]]] = []
    definitions = document["$defs"]
    assert isinstance(definitions, dict)
    for name, schema in definitions.items():
        assert isinstance(schema, dict)
        found.append((f"$defs.{name}", schema))
    for entry in _objects(document["operations"]):
        identifier = str(entry["id"])
        returns = entry["returns"]
        assert isinstance(returns, dict)
        found.append((f"{identifier}.returns", _schema(returns["schema"])))
        parameters = entry["params"]
        assert isinstance(parameters, list)
        for parameter in parameters:
            assert isinstance(parameter, dict)
            found.append(
                (f"{identifier}({parameter['name']})", _schema(parameter["schema"]))
            )
    for entry in _objects(document["attributes"]):
        if entry.get("kind") == "value":
            location = f"{entry['unit']}.{entry['member']}"
            found.append((f"attributes.{location}", _schema(entry["schema"])))
    for entry in _objects(document["units"]):
        state = entry.get("receiver_state")
        if isinstance(state, dict):
            found.append((f"units.{entry['id']}.receiver_state", state))
        item = entry.get("item")
        if isinstance(item, dict):
            found.append((f"units.{entry['id']}.item", item))
    return found


def _schema(value: object) -> dict[str, object]:
    """Return a schema read out of the manifest.

    Args:
        value: Value that must be a schema.

    Returns:
        The schema.
    """
    assert isinstance(value, dict)
    return value


def _public_members(cls: type[object]) -> set[str]:
    """Return the public members a unit's class exposes.

    The manifest is built from ``inspect.getmembers``, which includes inherited
    members, so the check walks the same surface.

    Args:
        cls: Public sync class.

    Returns:
        Names of its public methods, class methods and properties.
    """
    members: set[str] = set()
    for name, value in inspect.getmembers(cls):
        if name.startswith("_"):
            continue
        if (
            isinstance(value, property)
            or isinstance(value, cached_property)
            or inspect.isfunction(value)
            or inspect.ismethod(value)
            or isinstance(value, classmethod | staticmethod)
        ):
            members.add(name)
    return members


def _deprecated_members(cls: type[object]) -> set[str]:
    """Return the public members marked with PEP 702 ``@deprecated``.

    Args:
        cls: Public sync class.

    Returns:
        Names of its deprecated members.
    """
    deprecated: set[str] = set()
    for name in _public_members(cls):
        value = getattr(cls, name)
        function = value
        if isinstance(value, property):
            function = value.fget
        elif isinstance(value, cached_property):
            function = value.func
        elif isinstance(value, classmethod | staticmethod):
            function = value.__func__
        if getattr(function, "__deprecated__", None) is not None:
            deprecated.add(name)
    return deprecated


def test_manifest_is_plain_json_data() -> None:
    built = manifest()
    assert json.loads(json.dumps(built)) == json.loads(manifest_json(indent=0))


def test_manifest_header_describes_itself(document: dict[str, object]) -> None:
    import ksef2

    assert document["format_version"] == FORMAT_VERSION
    assert document["generated_by"] == "ksef2.bridge.manifest"
    assert document["ksef2_version"] == ksef2.__version__
    assert document["json_schema_dialect"] == SCHEMA_DIALECT
    assert isinstance(document["conventions"], dict)
    assert document["conventions"], "the manifest must explain how to read it"


def test_every_schema_is_valid_json_schema_2020_12(
    document: dict[str, object], definitions: dict[str, object]
) -> None:
    entries = _schema_entries(document)
    assert len(entries) > 500, "the manifest must cover the whole public surface"
    # The definitions are validated inside their own document, so a "$ref" in one
    # definition resolves the same way a reader resolves it. Every other schema is
    # placed in one object schema and validated with it, which keeps the check to a
    # single pass over the document.
    Draft202012Validator.check_schema(
        {"$schema": SCHEMA_DIALECT, "$defs": definitions, "type": "object"}
    )
    _ = Draft202012Validator.check_schema(
        {
            "$schema": SCHEMA_DIALECT,
            "$defs": definitions,
            "type": "object",
            "properties": {location: schema for location, schema in entries},
        }
    )


@pytest.mark.parametrize(
    "location",
    [
        "$defs.Page_InvoiceMetadata_",
        "$defs.ContextIdentifierType",
        "$defs.OnlineSessionResumeState",
        "$defs.ExportedInvoices",
    ],
)
def test_a_definition_of_each_kind_is_valid(
    location: str, document: dict[str, object], definitions: dict[str, object]
) -> None:
    name = location.removeprefix("$defs.")
    found = next(
        schema
        for entry_location, schema in _schema_entries(document)
        if entry_location == location
    )
    candidate = {**found, "$schema": SCHEMA_DIALECT, "$defs": definitions}
    Draft202012Validator.check_schema(candidate)
    assert name in definitions


def test_every_reference_resolves_locally(document: dict[str, object]) -> None:
    references = collect_refs(document, set())
    assert references, "the manifest must describe its types with $ref"
    assert all(reference.startswith(DEF_PREFIX) for reference in references)
    definitions = document["$defs"]
    assert isinstance(definitions, dict)
    missing = sorted(
        reference
        for reference in references
        if reference[len(DEF_PREFIX) :] not in definitions
    )
    assert missing == []


def test_no_definition_is_left_unreferenced(
    document: dict[str, object], definitions: dict[str, object]
) -> None:
    references = {
        reference[len(DEF_PREFIX) :]
        for reference in collect_refs(document, set())
        if reference.startswith(DEF_PREFIX)
    }
    unused = sorted(set(definitions) - references)
    assert unused == []


@pytest.mark.parametrize("alias", LITERAL_ALIASES)
def test_literal_alias_is_a_named_enum(
    alias: str, document: dict[str, object], definitions: dict[str, object]
) -> None:
    schema = definitions[alias]
    assert isinstance(schema, dict)
    assert schema.get("type") in ("string", "integer")
    assert isinstance(schema.get("enum"), list)
    assert schema["enum"], f"{alias} must list its accepted values"
    assert f"{DEF_PREFIX}{alias}" in collect_refs(document, set())


def test_no_enum_is_inlined_outside_the_definitions(
    document: dict[str, object],
) -> None:
    inlined = [
        location
        for location, schema in _schema_entries(document)
        if "enum" in schema and not location.startswith("$defs")
    ]
    assert inlined == []


def test_operations_cover_every_public_sync_method(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
) -> None:
    described = set(operations)
    excluded = set(_entries_by_id(document["excluded"]))
    attributes = {
        f"{entry['unit']}.{entry['member']}"
        for entry in _objects(document["attributes"])
    }
    missing: list[str] = []
    for unit in UNITS:
        for name in _public_members(unit.cls):
            identifier = f"{unit.id}.{name}"
            if identifier not in described | excluded | attributes:
                missing.append(identifier)
    assert missing == [], (
        "public sync members must be operations or carry an exclusion with a"
        f" reason: {', '.join(sorted(missing))}"
    )


def test_no_public_sync_class_is_left_out_of_the_units(
    document: dict[str, object],
) -> None:
    listed = {str(entry["class"]) for entry in _objects(document["units"])}
    units = _objects(document["units"])
    assert listed == {cls.__name__ for cls in public_sync_classes()}
    assert len(listed) == len(units)


def test_described_members_match_the_public_surface(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
) -> None:
    public: set[str] = set()
    for unit in UNITS:
        for name in _public_members(unit.cls):
            public.add(f"{unit.id}.{name}")
    described = set(operations)
    described |= {
        f"{entry['unit']}.{entry['member']}"
        for entry in _objects(document["attributes"])
    }
    described |= set(_entries_by_id(document["excluded"]))
    assert described == public
    assert {str(entry["class"]) for entry in _objects(document["excluded"])} <= {
        cls.__name__ for cls in public_sync_classes()
    }


def test_deprecated_members_are_excluded_with_their_replacement(
    document: dict[str, object],
) -> None:
    excluded = _entries_by_id(document["excluded"])
    deprecated: set[str] = set()
    for unit in UNITS:
        for name in _deprecated_members(unit.cls):
            deprecated.add(f"{unit.id}.{name}")
    assert deprecated, "the SDK deprecates members, so the manifest must list them"
    assert deprecated <= set(excluded)
    for identifier in sorted(deprecated):
        entry = excluded[identifier]
        assert entry["reason"] == "deprecated"
        # AGENTS.md: a deprecation names a replacement and a 2.0.0 boundary.
        assert "2.0.0" in str(entry["detail"])


def test_every_exclusion_carries_a_known_reason(
    document: dict[str, object],
) -> None:
    for entry in _objects(document["excluded"]):
        assert entry["reason"] in REASONS, f"{entry['id']} uses an unknown reason"
        detail = str(entry["detail"])
        assert len(detail) > 30, f"{entry['id']} does not explain the exclusion"
        assert "Declare the member in" not in detail, (
            f"{entry['id']} was dropped by the builder rather than decided in"
            " ksef2/bridge/_api.py"
        )


def test_declared_exclusions_are_all_present_in_the_manifest(
    document: dict[str, object],
) -> None:
    excluded = _entries_by_id(document["excluded"])
    units = {str(entry["id"]): entry for entry in _objects(document["units"])}
    for unit_id, members in EXCLUSIONS.items():
        assert unit_id in units, f"{unit_id} is not a unit of the manifest"
        for member in members:
            assert f"{unit_id}.{member}" in excluded, f"{unit_id}.{member} reappeared"


def test_every_operation_is_described_completely(
    document: dict[str, object], operations: dict[str, dict[str, object]]
) -> None:
    units = {str(entry["id"]) for entry in _objects(document["units"])}
    states = {str(entry["name"]) for entry in _objects(document["states"])}
    assert len(operations) == len(_objects(document["operations"]))
    for identifier, entry in operations.items():
        assert entry["id"] == identifier
        assert entry["unit"] in units
        assert entry["state"] in states
        assert str(entry["summary"]), f"{identifier} has no summary"
        assert not str(entry["summary"]).endswith("\n")
        returns = _schema(entry["returns"])
        assert str(returns["kind"]), f"{identifier} does not say what it returns"
        assert isinstance(returns["schema"], dict)
        parameters = entry["params"]
        assert isinstance(parameters, list)
        for parameter in parameters:
            assert isinstance(parameter, dict)
            assert isinstance(parameter["name"], str)
            assert isinstance(parameter["required"], bool)
            assert isinstance(parameter["origin"], str)
            assert isinstance(parameter["schema"], dict)


def test_paged_operations_return_pages_with_a_cursor(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
    definitions: dict[str, object],
) -> None:
    paged = [
        entry
        for entry in operations.values()
        if _schema(entry["returns"])["kind"] == "paged"
    ]
    assert paged, "collection operations must be described as paged"
    for entry in paged:
        returns = _schema(entry["returns"])
        page = _definitions_schema(definitions, _schema(returns["schema"]))
        assert page["type"] == "object"
        properties = page["properties"]
        assert isinstance(properties, dict)
        assert "items" in properties and "next_cursor" in properties
        items = _schema(properties["items"])
        assert items["type"] == "array"
        assert returns["item"] == items["items"], (
            "the item of an operation is the item of its page"
        )
        item = _schema(returns["item"])
        assert "$ref" in item or "type" in item, f"{entry['id']} leaves its item open"
        next_cursor = properties["next_cursor"]
        assert isinstance(next_cursor, dict)
        assert _accepts_null(next_cursor), "a null cursor must end the collection"


def test_a_result_of_bytes_is_written_as_base64_array(
    operations: dict[str, dict[str, object]],
) -> None:
    returns = _schema(operations["batch_session.download_upo"]["returns"])
    assert returns == {
        "kind": "value",
        "schema": {
            "items": {"type": "string", "contentEncoding": "base64"},
            "type": "array",
        },
    }


def test_only_a_page_is_described_as_a_paged_result(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
    definitions: dict[str, object],
) -> None:
    for entry in operations.values():
        returns = _schema(entry["returns"])
        if returns["kind"] != "paged":
            continue
        reference = str(_schema(returns["schema"]).get("$ref", ""))
        assert reference.startswith(f"{DEF_PREFIX}Page_"), entry["id"]
    # A method that hands back every item of one page as a Python list is data,
    # not a collection a caller resumes: it carries no cursor.
    for identifier in ("pager.first_page", "online_session.download_upo"):
        assert _schema(operations[identifier]["returns"])["kind"] == "value"


def test_page_operations_are_described_as_pages(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
    definitions: dict[str, object],
) -> None:
    for unit in ("pager", "invoice_search_pager"):
        page = operations[f"{unit}.page"]
        page_schema = _schema(_schema(page["returns"])["schema"])
        schema = _definitions_schema(definitions, page_schema)
        reference = str(page_schema.get("$ref", ""))
        assert reference.startswith(f"{DEF_PREFIX}Page_"), f"{unit}.page is not a Page"
        properties = schema["properties"]
        assert isinstance(properties, dict) and "items" in properties
        cursor_parameter = _parameters(page)[-1]
        assert cursor_parameter["name"] == "cursor"
        assert cursor_parameter["required"] is False


def test_pagers_document_their_item_type(document: dict[str, object]) -> None:
    units = {str(entry["id"]): entry for entry in _objects(document["units"])}
    assert units["pager"]["item"] == {"$ref": f"{DEF_PREFIX}{TYPE_PARAMETER}"}
    assert units["invoice_search_pager"]["item"] == {
        "$ref": f"{DEF_PREFIX}InvoiceMetadata"
    }
    placeholder = document["$defs"]
    assert isinstance(placeholder, dict)
    schema = placeholder[TYPE_PARAMETER]
    assert isinstance(schema, dict)
    assert schema.get("description"), "the item placeholder must explain itself"
    assert "type" not in schema


def test_operations_that_return_handles_describe_their_state(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
    definitions: dict[str, object],
) -> None:
    handle_units = {
        str(entry["id"])
        for entry in _objects(document["units"])
        if entry["kind"] == "handle" and "receiver_state" in entry
    }
    assert handle_units == {
        "generated_token",
        "certificate_enrollment",
        "permission_operation",
        "invoice_submission",
        "export_job",
    }
    returning = [
        entry
        for entry in operations.values()
        if _schema(entry["returns"])["kind"] == "handle"
    ]
    assert returning, "operations that start asynchronous work must be found"
    for entry in returning:
        returns = _schema(entry["returns"])
        assert str(returns["unit"]) in handle_units
        state = _definitions_schema(definitions, _schema(returns["schema"]))
        assert state["type"] == "object"
        created_by = _unit(document, str(returns["unit"]))["created_by"]
        assert str(entry["id"]) in _names(created_by)


@pytest.mark.parametrize(
    "handle_unit",
    [
        "generated_token",
        "certificate_enrollment",
        "permission_operation",
        "invoice_submission",
        "export_job",
    ],
)
def test_handle_follow_up_operations_take_the_state(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
    handle_unit: str,
) -> None:
    unit = _unit(document, handle_unit)
    state = _schema(unit["receiver_state"])
    resume = operations[f"{handle_unit}.resume_state"]
    returns = _schema(resume["returns"])
    assert returns["kind"] == "value", "resume_state returns its state model"
    assert returns["schema"] == state
    assert _parameters(resume) == []
    name = "get_status" if handle_unit != "export_job" else "wait"
    follow_up = operations[f"{handle_unit}.{name}"]
    parameters = _parameters(follow_up)
    injected = parameters[0]
    assert injected["name"] == "state"
    assert injected["origin"] == "unit_state"
    assert injected["required"] is True
    assert injected["schema"] == state


def test_session_operations_take_their_session_state(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
) -> None:
    sessions = {
        str(entry["id"]): _schema(entry["receiver_state"])
        for entry in _objects(document["units"])
        if entry["kind"] in ("session", "client") and "receiver_state" in entry
    }
    assert sessions["online_session"]["$ref"] == f"{DEF_PREFIX}OnlineSessionResumeState"
    assert sessions["batch_session"]["$ref"] == f"{DEF_PREFIX}BatchSessionResumeState"
    assert sessions["authenticated"]["$ref"] == f"{DEF_PREFIX}AuthenticationResumeState"
    for identifier in (
        "online_session.get_status",
        "online_session.send_invoice",
        "batch_session.upload_parts",
    ):
        injected = _parameters(operations[identifier])[0]
        assert injected["origin"] == "unit_state"
        assert injected["schema"] == sessions[identifier.split(".")[0]]
    resume = operations["online_session.resume_state"]
    assert _schema(_schema(resume["returns"])["schema"]) == sessions["online_session"]


def test_authentication_operations_describe_the_authenticated_state(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
) -> None:
    for identifier in (
        "auth.with_token",
        "auth.with_profile",
        "auth.with_test_certificate",
        "auth.resume",
    ):
        returns = _schema(operations[identifier]["returns"])
        assert returns["kind"] == "client"
        assert returns["unit"] == "authenticated"
        assert returns["schema"] == {"$ref": f"{DEF_PREFIX}AuthenticationResumeState"}
    assert operations["auth.with_profile"]["state"] == "unauthenticated"


def test_export_results_are_described_as_data(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
    definitions: dict[str, object],
) -> None:
    returns = _schema(operations[EXPORT_RESULT_CALL]["returns"])
    assert returns["kind"] == "data"
    assert returns["unit"] == "exported_invoices"
    assert returns["schema"] == {"$ref": f"{DEF_PREFIX}ExportedInvoices"}
    export = definitions["ExportedInvoices"]
    assert isinstance(export, dict)
    properties = export["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {"archive", "package", "metadata"}
    archive = properties["archive"]
    assert isinstance(archive, dict)
    assert archive["type"] == "string"
    assert archive["contentEncoding"] == "base64"


def test_plain_calls_describe_parameters_and_returns(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
    definitions: dict[str, object],
) -> None:
    entry = operations[PLAIN_CALL]
    assert entry["state"] == "authenticated"
    parameters = _parameters(entry)
    assert [parameter["name"] for parameter in parameters] == ["reference_number"]
    assert parameters[0]["required"] is True
    assert parameters[0]["description"], (
        "a parameter description comes from the docstring"
    )
    assert entry["returns"] == {
        "kind": "value",
        "schema": {"$ref": f"{DEF_PREFIX}TokenStatusResponse"},
    }


def test_literal_alias_parameters_point_at_named_enums(
    document: dict[str, object],
    operations: dict[str, dict[str, object]],
    definitions: dict[str, object],
) -> None:
    parameters = _parameters(operations[LITERAL_ALIAS_PARAMETER])
    context_type = next(
        parameter for parameter in parameters if parameter["name"] == "context_type"
    )
    assert context_type["schema"] == {
        "$ref": f"{DEF_PREFIX}ContextIdentifierType",
        "default": "nip",
    }
    assert context_type["default"] == "nip"
    alias = definitions["ContextIdentifierType"]
    assert isinstance(alias, dict)
    assert "nip" in alias["enum"]


def test_defaults_are_written_as_json(
    document: dict[str, object], operations: dict[str, dict[str, object]]
) -> None:
    parameters = _parameters(operations["batch.prepare"])
    by_name = {str(parameter["name"]): parameter for parameter in parameters}
    assert by_name["form_code"]["default"] == "FA3"
    assert by_name["max_part_size"]["default"] == 100000000
    assert by_name["offline_mode"]["default"] is False
    assert "default" not in by_name["invoices"]
    assert by_name["invoices"]["required"] is True


def test_no_schema_uses_a_python_only_string_encoding(
    document: dict[str, object],
) -> None:
    encoded = json.dumps(document)
    assert '"format": "binary"' not in encoded
    assert "contentEncoding" in encoded


def test_live_objects_are_reachable_from_the_units(document: dict[str, object]) -> None:
    units = {str(entry["id"]): entry for entry in _objects(document["units"])}
    assert units["tokens"]["accessors"] == [
        {"unit": "authenticated", "member": "tokens"}
    ]
    assert units["client"]["kind"] == "root"
    assert units["invoices"]["kind"] == "service"
    for unit_id, entry in units.items():
        assert str(entry["class"]), unit_id
        assert str(entry["summary"]), unit_id
        assert isinstance(entry["created_by"], list)


def test_attributes_either_have_a_schema_or_name_a_unit(
    document: dict[str, object],
) -> None:
    units = {str(entry["id"]) for entry in _objects(document["units"])}
    for entry in _objects(document["attributes"]):
        location = f"{entry['unit']}.{entry['member']}"
        assert str(entry["summary"]), f"{location} has no summary"
        if entry["kind"] == "branch":
            assert entry["unit_ref"] in units
            assert "schema" not in entry, f"{location} names a unit, not a value"
        else:
            assert isinstance(entry["schema"], dict), location


def test_operations_are_sorted_and_unique(document: dict[str, object]) -> None:
    for key in ("operations", "excluded"):
        names = [str(entry["id"]) for entry in _objects(document[key])]
        assert names == sorted(names), f"{key} must be ordered for a stable document"
        assert len(names) == len(set(names)), f"{key} repeats an identifier"
    attributes = [
        f"{entry['unit']}.{entry['member']}"
        for entry in _objects(document["attributes"])
    ]
    assert attributes == sorted(attributes)
    assert len(attributes) == len(set(attributes))
    units = [str(entry["id"]) for entry in _objects(document["units"])]
    assert units == sorted(units)
    assert len(units) == len(set(units))


def test_definitions_are_sorted(definitions: dict[str, object]) -> None:
    names = list(definitions)
    assert names == sorted(names)


def test_definition_names_are_readable(definitions: dict[str, object]) -> None:
    qualified = sorted(
        name for name in definitions if "__" in name or name.startswith("ksef2_")
    )
    assert qualified == [], "a definition kept a module path written by pydantic"
    assert "CertificatesIdentifierType" in definitions
    assert "TestdataIdentifierType" in definitions


def test_no_schema_carries_a_label_written_by_pydantic(
    document: dict[str, object],
) -> None:
    assert _labels(document) == [], "pydantic labels repeat the names of the manifest"


def test_manifest_is_byte_for_byte_deterministic() -> None:
    assert manifest_json() == manifest_json()


@pytest.mark.parametrize("seed", ["0", "1", "12345"])
def test_manifest_survives_a_fresh_hash_seed(seed: str) -> None:
    script = "from ksef2.bridge import manifest_json; print(manifest_json(), end='')"
    environment = {"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        cwd=PROJECT_ROOT,
        env=_run_environment(environment),
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == manifest_json()


def _run_environment(extra: dict[str, str]) -> dict[str, str]:
    """Return a subprocess environment with the package importable.

    Args:
        extra: Variables the test adds.

    Returns:
        The environment to run with.
    """
    import os

    environment = dict(os.environ)
    environment.update(extra)
    return environment


def test_cli_manifest_command_prints_the_document() -> None:
    result = _run_cli("manifest", "--indent", "0")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == manifest()


def test_cli_indent_option_changes_only_the_layout() -> None:
    compact = _run_cli("manifest", "--indent", "0").stdout
    indented = _run_cli("manifest", "--indent", "4").stdout
    assert "\n    " in indented
    assert json.loads(compact) == json.loads(indented)


def test_cli_rejects_an_unknown_command() -> None:
    result = _run_cli("call", "tokens.list")
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_cli_rejects_a_negative_indent() -> None:
    result = _run_cli("manifest", "--indent", "-1")
    assert result.returncode == 2
    assert "negative" in result.stderr


def test_cli_rejects_an_indent_that_is_not_a_number() -> None:
    result = _run_cli("manifest", "--indent", "wide")
    assert result.returncode == 2
    assert "whole number" in result.stderr


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m ksef2.bridge`` with the given arguments.

    Args:
        arguments: Arguments after the module name.

    Returns:
        The completed process.
    """
    return subprocess.run(
        [sys.executable, "-m", "ksef2.bridge", *arguments],
        capture_output=True,
        check=False,
        cwd=PROJECT_ROOT,
        text=True,
    )


def _parameters(entry: dict[str, object]) -> list[dict[str, object]]:
    """Return the parameters of an operation entry.

    Args:
        entry: One entry from the ``operations`` section.

    Returns:
        Its parameter objects.
    """
    return _objects(entry["params"])


def _unit(document: dict[str, object], unit_id: str) -> dict[str, object]:
    """Return one entry of the ``units`` section.

    Args:
        document: The manifest.

    Returns:
        The unit with that identifier.
    """
    for entry in _objects(document["units"]):
        if entry["id"] == unit_id:
            return entry
    raise AssertionError(f"{unit_id} is not a unit of the manifest")


def _definitions_schema(
    definitions: dict[str, object], schema: dict[str, object]
) -> dict[str, object]:
    """Resolve a local reference into the shared definitions.

    Args:
        definitions: The ``$defs`` registry.
        schema: A schema that is a single local reference.

    Returns:
        The definition the reference points at.
    """
    reference = str(schema.get("$ref", ""))
    assert reference.startswith(DEF_PREFIX), reference
    resolved = definitions[reference[len(DEF_PREFIX) :]]
    assert isinstance(resolved, dict)
    return resolved


def _labels(value: object) -> list[str]:
    """Return every ``title`` written below ``value``.

    Args:
        value: Document subtree to walk.

    Returns:
        The labels found, in document order.
    """
    if isinstance(value, dict):
        found = [str(value["title"])] if "title" in value else []
        for item in value.values():
            found.extend(_labels(item))
        return found
    if isinstance(value, list):
        nested: list[str] = []
        for item in value:
            nested.extend(_labels(item))
        return nested
    return []


def _accepts_null(schema: dict[str, object]) -> bool:
    """Report whether a schema allows null.

    Args:
        schema: Schema to read.

    Returns:
        ``True`` when null is one of its accepted values.
    """
    if schema.get("type") == "null":
        return True
    variants = schema.get("anyOf")
    if isinstance(variants, list):
        return any(
            isinstance(variant, dict) and variant.get("type") == "null"
            for variant in variants
        )
    return False


def test_public_sync_classes_are_the_clients_facade() -> None:
    import ksef2.clients as clients

    sync = {
        name
        for name in clients.__all__
        if inspect.isclass(getattr(clients, name)) and not name.startswith("Async")
    }
    assert {cls.__name__ for cls in public_sync_classes()} == sync
    assert len(sync) == len(UNITS)


# --- what the builder refuses ---------------------------------------------------


class _Sample:
    """Class whose members stand in for the shapes the manifest cannot describe.

    Attributes:
        value: Plain attribute with no getter to describe.
    """

    value: str = "plain"

    def unannotated(self, value):  # noqa: ANN001 - the missing annotation is the point
        """Return a string."""
        return "value"

    def unreturns(self, value: str):
        """Return something without saying what."""
        return value

    def any_result(self) -> Any:
        """Return whatever arrives."""
        return None

    def iteration(self) -> Iterator[int]:
        """Yield Python objects."""
        return iter(())

    def star_arguments(self, *args: str) -> None:
        """Accept extra arguments."""

    def star_keywords(self, **kwargs: str) -> None:
        """Accept extra keywords."""

    @property
    def any_value(self) -> Any:
        """Return whatever the object holds."""
        return None


_ITEM = typing.TypeVar("_ITEM")


class _OtherPager(Pager[int]):
    """Pager that is not a unit of the manifest."""


class _Weird(enum.Enum):
    """Enumeration whose values are not JSON data."""

    FIRST = object()


_SAMPLE_UNIT = Unit(id="sample", cls=_Sample, kind="service", state="authenticated")
_PAGER_UNIT = Unit(id="pager", cls=Pager, kind=KIND_PAGER, state="pager")


def _sample_member(name: str, unit: Unit | None = None) -> _Member:
    """Return a member of the sample class.

    Args:
        name: Attribute name of the member.
        unit: Unit the member belongs to.

    Returns:
        The member the builder would see.
    """
    found = getattr(_Sample, name)
    function = found.fget if isinstance(found, property) else found
    return _Member(
        unit=unit or _SAMPLE_UNIT,
        name=name,
        kind="property" if isinstance(found, property) else "method",
        function=function,
        summary="",
        deprecated=None,
    )


@pytest.mark.parametrize(
    ("name", "detail"),
    [
        ("unannotated", "without a type annotation"),
        ("unreturns", "does not annotate what it returns"),
        ("any_result", "typed as Any"),
        ("iteration", "Python iteration"),
        ("star_arguments", "*args"),
        ("star_keywords", "**kwargs"),
    ],
)
def test_a_member_python_cannot_describe_is_left_out(name: str, detail: str) -> None:
    planned = _plan(_sample_member(name), SchemaBuilder())
    assert isinstance(planned, UndescribableType)
    assert detail in planned.detail
    exclusion = _python_only(planned)
    assert exclusion.reason == "python_only"
    assert detail in exclusion.detail


def test_a_property_without_a_json_value_is_left_out() -> None:
    planned = _plan(_sample_member("any_value"), SchemaBuilder())
    assert isinstance(planned, UndescribableType)
    assert "typed as Any" in planned.detail


def test_a_member_that_is_not_a_method_is_left_out() -> None:
    member = _Member(
        unit=_SAMPLE_UNIT,
        name="value",
        kind="attribute",
        function=None,
        summary="",
        deprecated=None,
    )
    planned = _plan(member, SchemaBuilder())
    assert isinstance(planned, UndescribableType)
    assert "value" in planned.detail


def test_a_signature_python_cannot_read_is_left_out() -> None:
    member = _Member(
        unit=_SAMPLE_UNIT,
        name="builtin",
        kind="method",
        function=dict.update,
        summary="",
        deprecated=None,
    )
    planned = _plan(member, SchemaBuilder())
    assert isinstance(planned, UndescribableType)
    assert "builtin" in planned.detail


def test_a_live_object_without_a_data_form_is_left_out() -> None:
    bare = Unit(id="bare", cls=_Sample, kind="handle", state="handle")
    with pytest.raises(UndescribableType) as error:
        _unit_descriptor(bare, SchemaBuilder())
    assert "no state model" in error.value.detail


def test_a_pager_that_is_not_a_unit_is_left_out() -> None:
    with pytest.raises(UndescribableType) as error:
        _pager_unit(_OtherPager, _sample_member("unreturns"))
    assert "_OtherPager" in error.value.detail


def test_a_pager_unit_keeps_its_item_open() -> None:
    returns = _unit_descriptor(_PAGER_UNIT, SchemaBuilder())
    assert returns.kind == "paged"
    assert returns.page_name == TYPE_PARAMETER


def test_a_page_of_an_unknown_name_is_referenced_as_it_is_named() -> None:
    generated = _Generated(Schemas(definitions={}, values={}, parameters={}))
    assert generated.item_of_page("Page_Unknown_") == {
        "$ref": f"{DEF_PREFIX}Page_Unknown_"
    }


def test_a_result_without_a_generated_schema_is_written_empty() -> None:
    plan = _OperationPlan(
        member=_sample_member("unreturns"),
        params_key="params:sample.unreturns",
        state_model=None,
        returns=_Returns(kind="value"),
    )
    generated = _Generated(
        Schemas(definitions={}, values={}, parameters={"params:sample.unreturns": []})
    )
    entry = generated.operations([plan])[0]
    assert entry["returns"] == {"kind": "value", "schema": {}}


def test_a_discovered_python_only_member_is_recorded_as_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def members(unit: Unit) -> list[_Member]:
        return [_sample_member("unreturns", unit)]

    monkeypatch.setattr(_manifest, "_members", members)
    document = _manifest.manifest()
    entries = _objects(document["excluded"])
    assert len(entries) == len(UNITS)
    assert {str(entry["reason"]) for entry in entries} == {"python_only"}
    assert _objects(document["operations"]) == []


def test_a_public_class_without_a_unit_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_manifest, "public_sync_classes", lambda: [_Sample])
    with pytest.raises(KSeFException, match="cover the public sync API") as missing:
        _check_units()
    assert "_Sample" in str(missing.value.context["missing"])


def test_a_unit_without_a_public_class_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_manifest, "public_sync_classes", lambda: [])
    with pytest.raises(KSeFException, match="cover the public sync API") as extra:
        _check_units()
    assert "Client" in str(extra.value.context["undeclared"])


@pytest.mark.parametrize(
    ("annotation", "detail"),
    [
        (inspect.Parameter.empty, "without a type annotation"),
        (Self, "receiving object"),
        (Any, "typed as Any"),
        (Iterator[int], "Python iteration"),
        (dict[int, str], "keys are not plain strings"),
        (typing.Iterable, "does not say what it holds"),
        (_Weird, "does not describe as a JSON enumeration"),
        (_Sample, "test_bridge_manifest._Sample"),
    ],
)
def test_a_type_without_a_json_form_is_refused(annotation: object, detail: str) -> None:
    with pytest.raises(UndescribableType) as error:
        resolve_type(annotation)
    assert detail in error.value.detail


def test_an_open_type_variable_needs_a_stand_in() -> None:
    # The annotations are built at runtime from a variable typed as ``object``:
    # a type variable written into a subscript expression means nothing to a
    # static checker, and these are values the builder reads, not annotations.
    variable: object = _ITEM
    collection: object = list[variable]
    choice: object = typing.Union[str, variable]  # noqa: UP007
    with pytest.raises(UndescribableType):
        resolve_type(variable)
    with pytest.raises(UndescribableType):
        resolve_type(collection)
    assert resolve_type(variable, item=str) is str
    assert resolve_type(collection, item=int) == list[int]
    assert resolve_type(choice, item=int) == (str | int)


def test_the_item_placeholder_is_a_named_definition() -> None:
    assert resolve_type(T) is T
    assert _definition_name(T) == TYPE_PARAMETER
    assert _is_open_item(_ITEM) is True
    assert _is_open_item(T) is False


def test_a_definition_name_is_only_invented_for_a_qualified_one() -> None:
    assert _definition_name(_Sample) == "_Sample"
    assert _qualified_short_name("TokenInfo") is None
    assert _qualified_short_name("__TokenInfo") is None
    assert _qualified_short_name("9__TokenInfo") is None
    assert (
        _qualified_short_name("ksef2___domain__models__testdata__IdentifierType")
        == "TestdataIdentifierType"
    )


def test_names_of_types_stay_readable() -> None:
    assert _name_of(str) == "str"
    assert _name_of(_Sample).endswith("_Sample")
    assert _name_of(3) == "3"
    assert _type_name(_Sample).endswith("_Sample")


def test_scalar_test_accepts_what_it_can_hash() -> None:
    assert _is_scalar(str) is True
    assert _is_scalar(list[int]) is False
    assert _is_scalar([1, 2]) is False
    assert _as_list(None) == []
    assert _as_list(1) == [1]


def test_an_empty_request_set_generates_nothing() -> None:
    schemas = SchemaBuilder().build()
    assert schemas.definitions == {}
    assert schemas.values == {}
    assert schemas.parameters == {}


# --- the data guardrails --------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        {1: "x"},
        object(),
        {1, 2},
        frozenset({1}),
        [object()],
        math.nan,
        math.inf,
        b"bytes",
    ],
)
def test_a_value_json_cannot_write_is_refused(value: object) -> None:
    with pytest.raises(KSeFException, match="not JSON data"):
        require_json(value)


def test_a_tuple_default_is_written_as_a_json_array() -> None:
    assert require_json(("a", 1)) == ["a", 1]
    assert require_json([1, ("a", None)]) == [1, ["a", None]]


def test_plain_data_passes_the_json_guard() -> None:
    data: dict[str, object] = {"a": [1, 2.5, None, True], "b": {"c": "text"}}
    assert require_json(data) == data
    assert as_object(data) == data
    assert as_list([1]) == [1]
    with pytest.raises(KSeFException, match="an object"):
        as_object([1])
    with pytest.raises(KSeFException, match="a list"):
        as_list({"a": 1})


def test_a_missing_docstring_reads_as_an_empty_description() -> None:
    assert first_summary(None) == ""
    assert first_summary("   \n  \n") == ""
    assert first_summary("\n  One line.\n  Another line.\n") == "One line."
    assert argument_descriptions(None) == {}
    assert argument_descriptions("No sections here.") == {}


# --- the command line -----------------------------------------------------------


def test_the_command_line_prints_the_document(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["manifest", "--indent", "0"]) == 0
    assert json.loads(capsys.readouterr().out) == manifest()


def test_the_command_line_reports_a_manifest_it_cannot_build(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(indent: int = 2) -> str:
        raise KSeFException("the manifest cannot be built.", hint="Fix the builder.")

    monkeypatch.setattr(bridge_main, "manifest_json", refuse)
    assert main(["manifest"]) == 1
    printed = capsys.readouterr().err
    assert "cannot be built" in printed
    assert "Fix the builder." in printed


def test_the_command_line_parses_its_indent() -> None:
    arguments = build_parser().parse_args(["manifest"])
    assert arguments.command == "manifest"
    assert arguments.indent == 2
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["manifest", "--indent", "-1"])
    assert exit_info.value.code == 2
    with pytest.raises(SystemExit):
        build_parser().parse_args(["manifest", "--indent", "wide"])
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_the_indent_validator_names_what_it_rejected() -> None:
    from ksef2.bridge.__main__ import _indent

    assert _indent("4") == 4
    with pytest.raises(argparse.ArgumentTypeError, match="whole number"):
        _indent("wide")
    with pytest.raises(argparse.ArgumentTypeError, match="negative"):
        _indent("-1")


def test_manifest_json_refuses_a_negative_indent() -> None:
    with pytest.raises(KSeFArgumentError, match="negative"):
        manifest_json(indent=-1)
