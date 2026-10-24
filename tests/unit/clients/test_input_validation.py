"""Public conversions reject invalid inputs before contacting KSeF."""

import pytest
from pydantic import ValidationError

from ksef2 import KSeFArgumentError, KSeFValidationError
from ksef2.models import (
    EntityPermission,
    EntityPermissionTypeEnum,
    TokenPermissionEnum,
    PersonPermissionTypeEnum,
)
from ksef2._clients.async_permissions import AsyncPermissionsClient
from ksef2._clients.async_tokens import AsyncTokensClient
from ksef2._clients.permissions import PermissionsClient
from ksef2._clients.tokens import TokensClient
from tests.unit.factories.session import DomainOnlineSessionResumeStateFactory
from tests.unit.support.flavors import Flavor


@pytest.mark.parametrize(
    "operation, parameter",
    [
        ("empty_invoice", "invoice_xml"),
        ("token_description", "description"),
        ("person_permission", "permissions"),
        ("entity_permission", "permissions"),
        ("export_state", "state"),
    ],
)
def test_invalid_public_input_is_sdk_validation_error(
    flavor: Flavor,
    operation: str,
    parameter: str,
) -> None:
    permissions = flavor.client(PermissionsClient, AsyncPermissionsClient)
    tokens = flavor.client(TokensClient, AsyncTokensClient)
    with pytest.raises(KSeFValidationError, match=parameter) as caught:
        match operation:
            case "empty_invoice":
                session = flavor.online_session(
                    DomainOnlineSessionResumeStateFactory.build()
                )
                flavor.run(session.send_invoice(b""))
            case "token_description":
                flavor.run(
                    tokens.generate(permissions=["invoice_read"], description="x")
                )
            case "person_permission":
                flavor.run(
                    permissions.grant_person(
                        subject_type="pesel",
                        subject_value="44051401458",
                        permissions=["InvoiceRead"],
                        description="Test grant",
                        first_name="Jan",
                        last_name="Kowalski",
                    )
                )
            case "entity_permission":
                flavor.run(
                    permissions.grant_entity(
                        subject_value="5261040828",
                        permissions=["garbage"],
                        description="Test grant",
                        entity_name="Example",
                    )
                )
            case "export_state":
                flavor.run(flavor.invoices_service().export(state="garbage"))
    if operation not in {"person_permission", "entity_permission"}:
        assert isinstance(caught.value.__cause__, ValidationError)
    assert not flavor.transport.calls


@pytest.mark.parametrize(
    "subject_type, subject_value",
    [
        ("pesel", "44051401459"),
        ("pesel", "5261040828"),
        ("nip", "44051401458"),
        ("nip", "5261040829"),
        ("nip", "1234567890"),
        ("nip", "５２６１０４０８２８"),
    ],
)
@pytest.mark.parametrize("grant", ["grant_person", "grant_indirect", "grant_subunit"])
def test_permission_identifier_matches_type_and_checksum(
    flavor: Flavor,
    subject_type: str,
    subject_value: str,
    grant: str,
) -> None:
    client = flavor.client(PermissionsClient, AsyncPermissionsClient)
    kwargs: dict[str, object] = dict(
        subject_type=subject_type,
        subject_value=subject_value,
        description="Test grant",
        first_name="Jan",
        last_name="Kowalski",
    )
    if grant == "grant_subunit":
        kwargs.update(context_type="nip", context_value="5261040828")
    else:
        kwargs["permissions"] = ["invoice_read"]
    with pytest.raises(KSeFArgumentError, match="subject_value") as caught:
        flavor.run(getattr(client, grant)(**kwargs))
    assert caught.value.hint
    assert not flavor.transport.calls


@pytest.mark.parametrize(
    "operation", ["token", "person", "entity", "indirect", "eu_entity"]
)
def test_empty_permission_lists_fail_locally(flavor: Flavor, operation: str) -> None:
    client = flavor.client(PermissionsClient, AsyncPermissionsClient)
    with pytest.raises(KSeFArgumentError, match="permissions") as caught:
        if operation == "token":
            tokens = flavor.client(TokensClient, AsyncTokensClient)
            flavor.run(tokens.generate(permissions=[], description="Test token"))
        elif operation == "person":
            flavor.run(
                client.grant_person(
                    subject_type="pesel",
                    subject_value="44051401458",
                    permissions=[],
                    description="Test grant",
                    first_name="Jan",
                    last_name="Kowalski",
                )
            )
        elif operation == "entity":
            flavor.run(
                client.grant_entity(
                    subject_value="5261040828",
                    permissions=[],
                    description="Test grant",
                    entity_name="Example",
                )
            )
        elif operation == "indirect":
            flavor.run(
                client.grant_indirect(
                    subject_type="pesel",
                    subject_value="44051401458",
                    permissions=[],
                    description="Test grant",
                    first_name="Jan",
                    last_name="Kowalski",
                )
            )
        else:
            flavor.run(
                client.grant_eu_entity(
                    subject_value="a" * 64,
                    permissions=[],
                    description="Test grant",
                )
            )
    assert caught.value.hint
    assert not flavor.transport.calls


@pytest.mark.parametrize("method", ["revoke", "revoke_authorization"])
@pytest.mark.parametrize("value", ["", "  "])
def test_permission_revoke_requires_nonempty_id(
    flavor: Flavor, method: str, value: str
) -> None:
    client = flavor.client(PermissionsClient, AsyncPermissionsClient)
    with pytest.raises(KSeFArgumentError, match="permission_id"):
        flavor.run(getattr(client, method)(permission_id=value))
    assert not flavor.transport.calls


def test_token_revoke_requires_nonempty_reference(flavor: Flavor) -> None:
    client = flavor.client(TokensClient, AsyncTokensClient)
    with pytest.raises(KSeFArgumentError, match="reference_number"):
        flavor.run(client.revoke(reference_number=""))
    assert not flavor.transport.calls


def test_token_authentication_requires_nonempty_credential(flavor: Flavor) -> None:
    with pytest.raises(KSeFArgumentError, match="ksef_token"):
        flavor.run(flavor.auth_client().with_token(ksef_token="", nip="5261040828"))
    assert not flavor.transport.calls


@pytest.mark.parametrize("branch", ["token", "person", "entity"])
def test_pascalcase_permissions_suggest_snake_case(flavor: Flavor, branch: str) -> None:
    client = flavor.client(PermissionsClient, AsyncPermissionsClient)
    with pytest.raises(
        KSeFArgumentError, match='did you mean "invoice_read"\\?'
    ) as caught:
        if branch == "token":
            tokens = flavor.client(TokensClient, AsyncTokensClient)
            flavor.run(
                tokens.generate(permissions=["InvoiceRead"], description="Test token")
            )
        elif branch == "person":
            flavor.run(
                client.grant_person(
                    subject_type="pesel",
                    subject_value="44051401458",
                    permissions=["InvoiceRead"],
                    description="Test grant",
                    first_name="Jan",
                    last_name="Kowalski",
                )
            )
        else:
            flavor.run(
                client.grant_entity(
                    subject_value="5261040828",
                    permissions=["InvoiceRead"],
                    description="Test grant",
                    entity_name="Example",
                )
            )
    assert caught.value.hint
    assert not flavor.transport.calls


@pytest.mark.parametrize("branch", ["token", "person", "entity"])
@pytest.mark.parametrize("use_enum", [False, True])
def test_snakecase_and_enum_permissions_produce_api_values(
    flavor: Flavor,
    branch: str,
    use_enum: bool,
) -> None:
    client = flavor.client(PermissionsClient, AsyncPermissionsClient)
    flavor.transport.enqueue(
        {
            "referenceNumber": "20250625-SO-2C3E6C8000-B675CF5D68-07",
            "token": "one-time-token",
        }
    )
    if branch == "token":
        permission = TokenPermissionEnum.INVOICE_READ if use_enum else "invoice_read"
        tokens = flavor.client(TokensClient, AsyncTokensClient)
        flavor.run(tokens.generate(permissions=[permission], description="Test token"))
    elif branch == "person":
        permission = (
            PersonPermissionTypeEnum.INVOICE_READ if use_enum else "invoice_read"
        )
        flavor.run(
            client.grant_person(
                subject_type="pesel",
                subject_value="44051401458",
                permissions=[permission],
                description="Test grant",
                first_name="Jan",
                last_name="Kowalski",
            )
        )
    else:
        permission = (
            EntityPermissionTypeEnum.INVOICE_READ if use_enum else "invoice_read"
        )
        flavor.run(
            client.grant_entity(
                subject_value="5261040828",
                permissions=[permission],
                description="Test grant",
                entity_name="Example",
            )
        )
    body = flavor.transport.calls[0].json
    assert body is not None
    expected: object = (
        [{"type": "InvoiceRead", "canDelegate": False}]
        if branch == "entity"
        else ["InvoiceRead"]
    )
    assert body["permissions"] == expected


def test_entity_permission_preserves_delegation_flag(flavor: Flavor) -> None:
    client = flavor.client(PermissionsClient, AsyncPermissionsClient)
    flavor.transport.enqueue(
        {"referenceNumber": "20250625-SO-2C3E6C8000-B675CF5D68-07"}
    )
    flavor.run(
        client.grant_entity(
            subject_value="5261040828",
            permissions=[EntityPermission(type="invoice_read", can_delegate=True)],
            description="Test grant",
            entity_name="Example",
        )
    )
    body = flavor.transport.calls[0].json
    assert body is not None
    assert body["permissions"] == [{"type": "InvoiceRead", "canDelegate": True}]
