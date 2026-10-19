"""The machine-readable manifest of the public sync API: shape, coverage, refs."""

import json
import subprocess
import sys
from typing import Any, cast

import pytest
from pydantic import BaseModel

import ksef2
import ksef2.clients as public_clients
from ksef2 import KSeFException
from ksef2.bridge import manifest
from ksef2.bridge._bytes import (
    BytesLeaf,
    ItemsPlan,
    Plan,
    UnionPlan,
    ValuesPlan,
    bytes_plan,
)
from ksef2.bridge._catalog import (
    EXCLUDED_FRESH_ONLY,
    EXCLUDED_PAGER,
    EXCLUDED_UPLOAD_WITHOUT_PAYLOAD,
    WalkedClass,
)
from ksef2.bridge._errors import ManifestError
from ksef2.bridge._manifest import _forms_of, _operation
from ksef2.bridge._schemas import (
    SchemaBuilder,
    defining_objects,
    without_text_alternative,
)

#: The same table the manifest walks, spelled out here so a class that quietly
#: disappears from the manifest is a failing test and not a smaller document.
WALKED: tuple[tuple[type[object], str], ...] = (
    (public_clients.Client, "client"),
    (public_clients.AuthClient, "auth"),
    (public_clients.EncryptionClient, "encryption"),
    (public_clients.PeppolClient, "peppol"),
    (public_clients.TestDataClient, "testdata"),
    (public_clients.TemporalTestData, "temporal_testdata"),
    (public_clients.AuthenticatedClient, "authenticated"),
    (public_clients.TokensClient, "tokens"),
    (public_clients.CertificatesClient, "certificates"),
    (public_clients.PermissionsClient, "permissions"),
    (public_clients.InvoicesService, "invoices"),
    (public_clients.BatchService, "batch_service"),
    (public_clients.LimitsClient, "limits"),
    (public_clients.CollectiveIdentifiersClient, "collective_identifiers"),
    (public_clients.SessionManagementClient, "sessions"),
    (public_clients.InvoiceSessionsClient, "invoice_sessions"),
    (public_clients.OnlineSessionClient, "online"),
    (public_clients.BatchSessionClient, "batch"),
    (public_clients.GeneratedToken, "generated_token"),
    (public_clients.CertificateEnrollment, "certificate_enrollment"),
    (public_clients.PermissionOperation, "permission_operation"),
    (public_clients.InvoiceSubmission, "invoice_submission"),
    (public_clients.ExportJob, "export_job"),
    (public_clients.InvoiceSearchPager, "invoice_search"),
    (public_clients.ExportedInvoices, "exported_invoices"),
    (public_clients.Pager, "pager"),
)

DEFS = "#/$defs/"

CURSOR_ENTRY = {
    "name": "cursor",
    "required": False,
    "default": None,
    "schema": {"anyOf": [{"type": "string"}, {"type": "null"}]},
}


def _operations() -> dict[str, dict[str, Any]]:
    """The manifest's operations, keyed by id.

    Returns:
        Every operation object.
    """
    entries = cast("list[dict[str, Any]]", manifest()["operations"])
    return {entry["id"]: entry for entry in entries}


def _refs(document: object) -> set[str]:
    """Collect every ``$ref`` string in a JSON document.

    Args:
        document: Any part of the manifest.

    Returns:
        The reference strings it contains.
    """
    if isinstance(document, dict):
        found: set[str] = set()
        for key, value in document.items():
            if key == "$ref" and isinstance(value, str):
                found.add(value)
            else:
                found.update(_refs(value))
        return found
    if isinstance(document, list):
        return set().union(*(_refs(item) for item in document)) if document else set()
    return set()


def test_manifest_is_json_and_names_the_sdk_version() -> None:
    data = manifest()

    round_tripped = json.loads(json.dumps(data))
    assert round_tripped == data
    assert data["format_version"] == 1
    assert data["ksef2_version"] == ksef2.__version__
    assert set(data) == {
        "format_version",
        "ksef2_version",
        "operations",
        "excluded",
        "exceptions",
        "$defs",
    }
    assert json.dumps(data, sort_keys=True, indent=2)


def test_bytes_or_text_is_described_as_base64_bytes() -> None:
    operations = _operations()
    invoice_xml = next(
        parameter
        for parameter in operations["online.send_invoice"]["parameters"]
        if parameter["name"] == "invoice_xml"
    )
    assert invoice_xml["schema"] == {"type": "string", "contentEncoding": "base64"}

    def check_schema(schema: dict[str, Any]) -> None:
        alternatives = schema.get("anyOf", [])
        assert not (
            {"type": "string"} in alternatives
            and any(
                item.get("type") == "string" and "contentEncoding" in item
                for item in alternatives
            )
        ), schema
        for value in schema.values():
            if isinstance(value, dict):
                check_schema(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        check_schema(item)

    for operation in operations.values():
        for parameter in operation["parameters"]:
            check_schema(parameter["schema"])

    assert without_text_alternative(bytes | str) is bytes
    assert without_text_alternative(str | bytes | None) == bytes | None
    text_or_none = str | None
    assert without_text_alternative(text_or_none) is text_or_none
    assert without_text_alternative(bytes) is bytes
    integer_or_text = int | str
    assert without_text_alternative(integer_or_text) is integer_or_text


def test_every_public_sync_method_is_an_operation_or_excluded() -> None:
    data = manifest()
    operations = cast("list[dict[str, Any]]", data["operations"])
    excluded = cast("list[dict[str, str]]", data["excluded"])
    operation_ids = [entry["id"] for entry in operations]
    excluded_ids = [entry["id"] for entry in excluded]
    by_id = {entry["id"]: entry for entry in operations}
    reasons = {entry["id"]: entry["reason"] for entry in excluded}

    assert len(operation_ids) == len(set(operation_ids))
    assert len(excluded_ids) == len(set(excluded_ids))
    assert not set(operation_ids) & set(excluded_ids)

    for cls, prefix in WALKED:
        for name in sorted(dir(cls)):
            if name.startswith("_"):
                continue
            identifier = f"{prefix}.{name}"
            covered = identifier in by_id or identifier in reasons
            covered = covered or any(
                known.startswith(f"{identifier}.")
                for known in [*operation_ids, *excluded_ids]
            )
            assert covered, f"{identifier} is described by neither list"

    # A member with several @overload forms is one operation per form, named by
    # its distinguishing keyword, and never the implementation signature as well.
    for identifier in (
        "authenticated.online_session.form_code",
        "authenticated.online_session.state",
        "authenticated.batch_session.prepared_batch",
        "authenticated.batch_session.batch_file",
        "authenticated.batch_session.state",
        "invoices.export.filters",
        "invoices.export.state",
    ):
        assert identifier in by_id, identifier
    assert "authenticated.online_session" not in by_id
    assert "authenticated.batch_session" not in by_id
    assert "authenticated.batch_session" not in reasons
    assert "invoices.export" not in by_id

    # The accessors hand back a walked client, so they are excluded, and so is
    # every deprecated member, each with the reason that applies to it.
    assert reasons["client.authentication"] == (
        "returns another client; its methods are separate operations"
    )
    assert reasons["authenticated.tokens"] == (
        "returns another client; its methods are separate operations"
    )
    assert reasons["testdata.temporal"] == (
        "returns another client; its methods are separate operations"
    )
    assert reasons["tokens.list_all"] == "deprecated"
    assert reasons["online.get_state"] == "deprecated"
    assert reasons["client.__enter__"] == "context manager protocol"
    assert "tokens.list_page" in by_id


def test_with_xades_is_an_operation_with_the_data_form() -> None:
    data = manifest()
    operation = _operations()["auth.with_xades"]
    excluded_ids = {
        entry["id"] for entry in cast("list[dict[str, str]]", data["excluded"])
    }

    # The live certificate and key are objects, so the manifest describes the data
    # form of the member: the XAdESCredentials model that carries the same material.
    assert "auth.with_xades" not in excluded_ids
    names = [parameter["name"] for parameter in operation["parameters"]]
    assert names == [
        "nip",
        "credentials",
        "verify_chain",
        "timeout",
        "poll_interval",
    ]
    assert "cert" not in names
    assert "private_key" not in names

    by_name = {parameter["name"]: parameter for parameter in operation["parameters"]}
    credentials = by_name["credentials"]
    assert credentials["required"] is True
    assert credentials["schema"] == {"$ref": f"{DEFS}XAdESCredentials"}
    assert "default" not in credentials

    optional = ("verify_chain", "timeout", "poll_interval")
    assert all(by_name[name]["required"] is False for name in optional)
    assert {name: by_name[name]["schema"] for name in optional} == {
        "verify_chain": {"type": "boolean"},
        "timeout": {"type": "number"},
        "poll_interval": {"type": "number"},
    }
    assert {name: by_name[name]["default"] for name in optional} == {
        "verify_chain": False,
        "timeout": 60.0,
        "poll_interval": 1.0,
    }

    assert operation["receiver"] == "unauthenticated"
    assert operation["state_schema"] is None
    assert operation["returns"] == {"$ref": f"{DEFS}AuthenticationResumeState"}

    # The model holds the private key and the resume state holds the tokens, so
    # both ends of the call are secrets.
    assert "credentials" in operation["sensitive"]
    assert "state" in operation["sensitive"]


def test_literal_alias_is_a_named_enum() -> None:
    data = manifest()
    definitions = cast("dict[str, dict[str, Any]]", data["$defs"])
    alias = definitions["ContextIdentifierType"]

    assert alias["type"] == "string"
    assert alias["title"] == "ContextIdentifierType"
    assert isinstance(alias["enum"], list) and alias["enum"]

    users = [
        parameter["name"]
        for operation in cast("list[dict[str, Any]]", data["operations"])
        for parameter in operation["parameters"]
        if f"{DEFS}ContextIdentifierType" in json.dumps(parameter["schema"])
    ]
    fields = [
        f"{model}.{field}"
        for model, schema in definitions.items()
        for field in schema.get("properties", {})
        if f"{DEFS}ContextIdentifierType" in json.dumps(schema["properties"][field])
    ]
    assert users or fields


def test_paged_list_returns_a_page_schema() -> None:
    data = manifest()
    definitions = cast("dict[str, dict[str, Any]]", data["$defs"])
    operation = _operations()["tokens.list"]

    returns = operation["returns"]
    assert returns["type"] == "object"
    assert returns["properties"]["items"]["type"] == "array"
    item = returns["properties"]["items"]["items"]
    assert item == {"$ref": f"{DEFS}TokenInfo"}
    assert "reference_number" in definitions["TokenInfo"]["properties"]
    assert returns["properties"]["next_cursor"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }
    assert operation["parameters"][-1] == CURSOR_ENTRY
    assert all(
        parameter["name"] != "cursor" for parameter in operation["parameters"][:-1]
    )


def test_pager_members_are_excluded() -> None:
    data = manifest()
    assert not any(
        identifier.startswith(("pager.", "invoice_search."))
        for identifier in _operations()
    )
    excluded = cast("list[dict[str, str]]", data["excluded"])
    assert {entry["id"] for entry in excluded if entry["reason"] == EXCLUDED_PAGER} == {
        "pager.first_page",
        "pager.page",
        "pager.pages",
        "pager.wait",
        "invoice_search.first_page",
        "invoice_search.first_response",
        "invoice_search.page",
        "invoice_search.pages",
        "invoice_search.responses",
        "invoice_search.wait",
    }


def test_collection_operations_declare_a_cursor() -> None:
    operations = _operations()
    collections = {
        identifier
        for identifier, operation in operations.items()
        if operation["returns"].get("title") == "Page"
    }
    assert collections == {
        "certificates.list",
        "collective_identifiers.list",
        "collective_identifiers.list_for_invoice",
        "collective_identifiers.list_invoices",
        "invoice_sessions.list",
        "invoices.search",
        "peppol.list",
        "permissions.list_authorizations",
        "permissions.list_entities",
        "permissions.list_entity_roles",
        "permissions.list_eu_entities",
        "permissions.list_personal",
        "permissions.list_persons",
        "permissions.list_subordinate_entities",
        "permissions.list_subunits",
        "sessions.list",
        "tokens.list",
    }
    for identifier, operation in operations.items():
        names = [parameter["name"] for parameter in operation["parameters"]]
        if identifier in collections:
            assert operation["parameters"][-1] == CURSOR_ENTRY, identifier
            assert names.count("cursor") == 1, identifier
        else:
            assert "cursor" not in names, identifier


def test_batch_operations_are_published() -> None:
    data = manifest()
    assert {
        identifier
        for identifier in _operations()
        if identifier.startswith(
            ("batch.", "batch_service.", "authenticated.batch_session")
        )
    } == {
        "authenticated.batch_session.prepared_batch",
        "authenticated.batch_session.batch_file",
        "authenticated.batch_session.state",
        "batch_service.prepare",
        "batch_service.submit",
        "batch_service.upload_parts",
        "batch.access_token",
        "batch.aes_key",
        "batch.close",
        "batch.download_upo",
        "batch.get_status",
        "batch.iv",
        "batch.list_failed_invoices",
        "batch.list_invoices",
        "batch.part_upload_requests",
        "batch.reference_number",
        "batch.resume_state",
        "batch.wait",
    }
    excluded = cast("list[dict[str, str]]", data["excluded"])
    reasons = {entry["id"]: entry["reason"] for entry in excluded}
    assert {
        entry["id"]
        for entry in excluded
        if entry["reason"] == EXCLUDED_UPLOAD_WITHOUT_PAYLOAD
    } == {"batch.upload_parts"}
    for identifier in (
        "batch_service.get_status",
        "batch_service.get_upo",
        "batch_service.list_failed_invoices",
        "batch_service.list_invoices",
        "batch_service.prepare_batch",
        "batch_service.prepare_batch_from_paths",
        "batch_service.submit_batch",
        "batch_service.submit_prepared_batch",
        "batch_service.open_session",
        "batch_service.wait_for_completion",
        "batch.get_state",
        "batch.get_upo",
    ):
        assert reasons[identifier] == "deprecated"
    assert reasons["batch.__enter__"] == "context manager protocol"
    upload = _operations()["batch_service.upload_parts"]
    assert upload["parameters"][0] == {
        "name": "session",
        "required": True,
        "schema": {"$ref": f"{DEFS}BatchSessionResumeState"},
    }


def test_enum_values_are_json_scalars() -> None:
    definitions = cast("dict[str, dict[str, Any]]", manifest()["$defs"])
    for name, definition in definitions.items():
        if "enum" in definition:
            assert all(
                type(value) in (str, int, float, bool, type(None))
                for value in definition["enum"]
            ), name
    assert definitions["FormSchema"]["enum"] == [
        "FA2",
        "FA3",
        "FA_RR1",
        "PEF3",
        "PEF_KOR3",
    ]


def test_every_bytes_value_is_standard_base64() -> None:
    data = manifest()
    definitions = cast("dict[str, dict[str, Any]]", data["$defs"])

    def reject_nonstandard_bytes(value: object) -> None:
        if isinstance(value, dict):
            assert value.get("format") not in {"binary", "base64url"}, value
            for child in value.values():
                reject_nonstandard_bytes(child)
        elif isinstance(value, list):
            for child in value:
                reject_nonstandard_bytes(child)

    def assert_plan(schema: dict[str, Any], plan: Plan) -> None:
        if "$ref" in schema:
            schema = definitions[schema["$ref"][len(DEFS) :]]
        if isinstance(plan, UnionPlan):
            for alternative in plan.alternatives:
                assert_plan(schema, alternative)
            return
        variants = schema.get("anyOf", [schema])
        shape = (
            "string"
            if isinstance(plan, BytesLeaf)
            else "array"
            if isinstance(plan, ItemsPlan)
            else "object"
        )
        matching = []
        for variant in variants:
            if "$ref" in variant:
                variant = definitions[variant["$ref"][len(DEFS) :]]
            if variant.get("type") == shape:
                matching.append(variant)
        assert matching, (schema, plan)
        for variant in matching:
            if isinstance(plan, BytesLeaf):
                assert variant["contentEncoding"] == "base64", variant
                assert "format" not in variant
            elif isinstance(plan, ItemsPlan):
                for item in variant.get("prefixItems", [variant.get("items")]):
                    assert_plan(item, plan.item)
            elif isinstance(plan, ValuesPlan):
                assert_plan(variant["additionalProperties"], plan.value)
            else:
                for name, field_plan in plan.fields.items():
                    assert_plan(variant["properties"][name], field_plan)

    reject_nonstandard_bytes(data)
    for model, fields in {
        "XAdESCredentials": ("cert_pem", "key_pem"),
        "ExportedInvoicesData": ("archive",),
        "BatchInvoice": ("content",),
        "BatchPreparedPart": ("content",),
    }.items():
        for field in fields:
            schema = definitions[model]["properties"][field]
            assert schema["type"] == "string"
            assert schema["contentEncoding"] == "base64"
    assert definitions["XAdESCredentials"]["properties"]["key_pem"]["writeOnly"] is True

    checked: set[str] = set()
    for name, owners in defining_objects().items():
        if name not in definitions or len(owners) != 1:
            continue
        model = next(iter(owners))
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            continue
        plan = bytes_plan(model)
        if plan is not None:
            assert_plan(definitions[name], plan)
            checked.add(name)
    assert {
        "XAdESCredentials",
        "ExportedInvoicesData",
        "BatchInvoice",
        "BatchPreparedPart",
    } <= checked


def test_cursor_parameter_clash_stops_the_build() -> None:
    class Collection:
        def list(self, cursor: str) -> public_clients.Pager[int]:
            raise NotImplementedError

    forms = _forms_of(Collection, "list", Collection.list)
    assert len(forms) == 1
    target = WalkedClass(
        cls=Collection, prefix="fake", receiver="unauthenticated", state_model=None
    )
    with pytest.raises(ManifestError, match=r"fake\.list.*cursor"):
        _operation(SchemaBuilder(), target, "list", forms[0], "", {}, None)


def test_fresh_only_handle_members_are_excluded() -> None:
    data = manifest()
    operations = _operations()
    excluded = cast("list[dict[str, str]]", data["excluded"])
    fresh_only_ids = {
        "generated_token.token",
        "generated_token.response",
        "generated_token.to_sensitive_dict",
        "certificate_enrollment.response",
        "certificate_enrollment.timestamp",
    }

    assert {
        entry["id"] for entry in excluded if entry["reason"] == EXCLUDED_FRESH_ONLY
    } == fresh_only_ids
    assert fresh_only_ids.isdisjoint(operations)
    assert {
        "generated_token.reference_number",
        "generated_token.resume_state",
        "generated_token.get_status",
        "generated_token.wait",
        "certificate_enrollment.reference_number",
        "certificate_enrollment.get_status",
        "certificate_enrollment.resume_state",
    } <= operations.keys()

    returns = operations["tokens.generate"]["returns"]
    assert sorted(returns["required"]) == ["state", "token"]
    assert returns["properties"] == {
        "state": {"$ref": f"{DEFS}GeneratedTokenResumeState"},
        "token": {"type": "string"},
    }


def test_generate_token_returns_resume_state_and_the_one_time_token() -> None:
    data = manifest()
    definitions = cast("dict[str, dict[str, Any]]", data["$defs"])
    operation = _operations()["tokens.generate"]

    returns = operation["returns"]
    assert sorted(returns["required"]) == ["state", "token"]
    assert returns["properties"]["state"] == {
        "$ref": f"{DEFS}GeneratedTokenResumeState"
    }
    assert returns["properties"]["token"] == {"type": "string"}
    assert "token" in operation["sensitive"]
    assert "token" not in definitions["GeneratedTokenResumeState"]["properties"]


def test_online_session_send_uses_session_state() -> None:
    operation = _operations()["online.send_invoice"]

    assert operation["receiver"] == "online_session"
    assert operation["state_schema"] == {"$ref": f"{DEFS}OnlineSessionResumeState"}
    assert operation["returns"] == {"$ref": f"{DEFS}InvoiceSubmissionResumeState"}


def test_exception_catalogue_matches_exported_classes() -> None:
    expected = []
    for name in ksef2.__all__:
        member = getattr(ksef2, name)
        if not isinstance(member, type) or not issubclass(member, KSeFException):
            continue
        parent = next(
            (
                base.__name__
                for base in member.__mro__[1:]
                if isinstance(base, type) and issubclass(base, KSeFException)
            ),
            None,
        )
        expected.append(
            {
                "name": member.__name__,
                "code": cast("type[KSeFException]", member).code,
                "parent": parent,
            }
        )
    expected.sort(key=lambda entry: entry["name"])

    entries = cast("list[dict[str, str]]", manifest()["exceptions"])

    assert entries == expected
    assert {"name": "KSeFException", "code": "SDK_ERROR", "parent": None} in entries
    assert {
        "name": "KSeFTransportError",
        "code": "TRANSPORT_ERROR",
        "parent": "KSeFException",
    } in entries
    argument_error = next(e for e in entries if e["name"] == "KSeFArgumentError")
    assert argument_error["parent"] == "KSeFValidationError"
    assert any(entry["name"] == "NoCertificateAvailableError" for entry in entries)
    assert all(entry["name"] != "ExceptionCode" for entry in entries)
    assert entries == sorted(entries, key=lambda entry: entry["name"])


def test_cli_prints_the_manifest() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "ksef2.bridge", "manifest"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == manifest()
    assert completed.stdout == json.dumps(manifest(), sort_keys=True, indent=2) + "\n"


def test_refs_resolve() -> None:
    data = manifest()
    definitions = cast("dict[str, dict[str, Any]]", data["$defs"])

    missing = sorted(
        ref[len(DEFS) :]
        for ref in _refs(data)
        if not ref.startswith(DEFS) or ref[len(DEFS) :] not in definitions
    )
    assert not missing
    assert definitions
