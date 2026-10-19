"""Binding workflows driven by JSON answers and unedited state envelopes."""

import base64
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import patch
from xml.etree import ElementTree

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding
from polyfactory import BaseFactory
from pydantic import SecretStr

import ksef2.bridge as bridge
from ksef2._core.crypto import decrypt_aes_cbc, encrypt_invoice, sha256_b64
from ksef2._domain.models.certificates import CertificateEnrollmentResumeState
from ksef2._domain.models.invoices import (
    ExportedInvoicesData,
    ExportResumeState,
    InvoiceSubmissionResumeState,
)
from ksef2._domain.models.permissions import PermissionOperationResumeState
from ksef2._domain.models.tokens import GeneratedTokenResumeState
from ksef2._infra.schema.api import spec
from ksef2.bridge._operations import operations
from tests.unit.payloads import (
    INVOICE_REF,
    KSEF_1,
    KSEF_2,
    archive,
    invoice_status,
    metadata_page,
    package_status,
    session_status,
)
from tests.unit.test_bridge_call import (
    NIP,
    SESSION_REF,
    Recorder,
    ask,
    clients,  # noqa: F401
    envelope,
    online_state,
    peppol_page,
    recorder as _recorder,
    session_state,
)
from tests.unit.xades_material import key_pem, self_signed

recorder = _recorder
MANIFEST = cast("dict[str, Any]", bridge.manifest())

KEY, IV = b"k" * 32, b"v" * 16
INITIAL_STATE = json.dumps(
    {
        "environment": "test",
        "authentication": None,
        "online_session": None,
        "batch_session": None,
        "handle": None,
    }
)
FILTERS = {
    "role": "seller",
    "date_type": "issue_date",
    "date_from": "2026-01-01T00:00:00Z",
    "date_to": "2026-02-01T00:00:00Z",
}


@pytest.fixture
def auth_answers(
    auth_challenge_resp: BaseFactory[spec.AuthenticationChallengeResponse],
    auth_init_resp: BaseFactory[spec.AuthenticationInitResponse],
    auth_status_resp: BaseFactory[spec.AuthenticationOperationStatusResponse],
    auth_tokens_resp: BaseFactory[spec.AuthenticationTokensResponse],
) -> list[dict[str, Any]]:
    return [
        auth_challenge_resp.build(
            challenge="A" * 36, timestampMs=1735689600000
        ).model_dump(mode="json", by_alias=True),
        auth_init_resp.build(referenceNumber="R" * 36).model_dump(
            mode="json", by_alias=True
        ),
        auth_status_resp.build(
            status=spec.StatusInfo(code=200, description="Authenticated")
        ).model_dump(mode="json", by_alias=True),
        auth_tokens_resp.build().model_dump(mode="json", by_alias=True),
    ]


@pytest.fixture
def authenticated(
    recorder: Recorder,
    auth_answers: list[dict[str, Any]],
    public_key_cert: BaseFactory[spec.PublicKeyCertificate],
) -> dict[str, Any]:
    certificate = public_key_cert.build(
        validFrom=datetime(2020, 1, 1, tzinfo=UTC),
        validTo=datetime(2035, 1, 1, tzinfo=UTC),
        usage=[
            spec.PublicKeyCertificateUsage.KsefTokenEncryption,
            spec.PublicKeyCertificateUsage.SymmetricKeyEncryption,
        ],
    )
    recorder.queue([certificate.model_dump(mode="json", by_alias=True)])
    for response in auth_answers:
        recorder.queue(response)
    with patch("ksef2._clients.auth.encrypt_token", return_value="ZW5jcnlwdGVk"):
        answer = ask(
            "auth.with_token", {"ksef_token": "test-token", "nip": NIP}, INITIAL_STATE
        )
    assert answer["ok"] is True, answer
    assert answer["state"]["authentication"] == answer["result"]
    assert answer["state"]["authentication"]["access_token"] == "access-token"
    assert [(r.method, r.url.path) for r in recorder.requests] == [
        ("GET", "/security/public-key-certificates"),
        ("POST", "/auth/challenge"),
        ("POST", "/auth/ksef-token"),
        ("GET", "/auth/" + "R" * 36),
        ("POST", "/auth/token/redeem"),
    ]
    body = json.loads(recorder.requests[2].content)
    assert body["contextIdentifier"] == {"type": "Nip", "value": NIP}
    assert body["challenge"] == "A" * 36
    assert body["encryptedToken"] == "ZW5jcnlwdGVk"
    assert not recorder.queued
    return answer


@pytest.fixture
def session_crypto() -> Iterator[None]:
    with (
        patch(
            "ksef2._clients.authenticated.generate_session_key",
            return_value=(KEY, IV),
        ),
        patch(
            "ksef2._clients.authenticated.encrypt_symmetric_key",
            return_value=b"enc-key",
        ),
    ):
        yield


# W1: authenticate, open, send, resume the submission, fetch its UPO, and close.
@pytest.mark.xfail(
    strict=True,
    reason="online.send_invoice encrypts Base64 text instead of decoding invoice_xml bytes",
)
def test_token_auth_online_send_and_upo(
    recorder: Recorder,
    authenticated: dict[str, Any],
    session_crypto: None,
    session_open_online_resp: BaseFactory[spec.OpenOnlineSessionResponse],
    inv_send_resp: BaseFactory[spec.SendInvoiceResponse],
    inv_session_invoice_status_resp: BaseFactory[spec.SessionInvoiceStatusResponse],
    inv_session_status_resp: BaseFactory[spec.SessionStatusResponse],
) -> None:
    recorder.queue(
        session_open_online_resp.build(
            referenceNumber=SESSION_REF, validUntil=datetime(2030, 1, 1, tzinfo=UTC)
        ).model_dump(mode="json", by_alias=True)
    )
    opened = ask(
        "authenticated.online_session.form_code",
        {"form_code": "FA3"},
        json.dumps(authenticated["state"]),
    )
    assert opened["ok"] is True, opened
    assert opened["state"]["online_session"] == opened["result"]
    assert opened["state"]["online_session"]["form_code"] == "FA3"

    xml = b"<Invoice>JSON boundary</Invoice>"
    parameter = next(
        op for op in MANIFEST["operations"] if op["id"] == "online.send_invoice"
    )["parameters"][0]
    assert parameter["schema"]["anyOf"][0]["contentEncoding"] == "base64"
    recorder.queue(
        inv_send_resp.build(referenceNumber=INVOICE_REF).model_dump(
            mode="json", by_alias=True
        )
    )
    sent = ask(
        "online.send_invoice",
        {"invoice_xml": base64.b64encode(xml).decode()},
        json.dumps(opened["state"]),
    )
    assert sent["ok"] is True, sent
    assert sent["state"]["handle"] == sent["result"]
    assert sent["state"]["handle"]["reference_number"] == INVOICE_REF
    assert sent["state"]["handle"]["session_reference_number"] == SESSION_REF

    recorder.queue(invoice_status(inv_session_invoice_status_resp, 200, KSEF_1))
    waited = ask("invoice_submission.wait", {}, json.dumps(sent["state"]))
    assert waited["ok"] is True, waited
    assert waited["result"]["ksef_number"] == KSEF_1
    assert waited["state"]["handle"] == sent["state"]["handle"]

    upo_xml = b"<UPO>accepted</UPO>"
    recorder.queued.append(httpx.Response(200, content=upo_xml))
    downloaded = ask("invoice_submission.download_upo", {}, json.dumps(waited["state"]))
    assert downloaded["ok"] is True, downloaded
    assert base64.b64decode(downloaded["result"], validate=True) == upo_xml

    recorder.queue(session_status(inv_session_status_resp, 100))
    recorder.queue(None, status_code=204)
    closed = ask("online.close", {}, json.dumps(downloaded["state"]))
    assert closed["ok"] is True, closed
    assert closed["state"]["handle"] == sent["state"]["handle"]
    assert [(r.method, r.url.path) for r in recorder.requests[5:]] == [
        ("POST", "/sessions/online"),
        ("POST", f"/sessions/online/{SESSION_REF}/invoices"),
        ("GET", f"/sessions/{SESSION_REF}/invoices/{INVOICE_REF}"),
        ("GET", f"/sessions/{SESSION_REF}/invoices/{INVOICE_REF}/upo"),
        ("GET", f"/sessions/{SESSION_REF}"),
        ("POST", f"/sessions/online/{SESSION_REF}/close"),
    ]
    opening = json.loads(recorder.requests[5].content)
    assert opening["formCode"]["systemCode"] == "FA (3)"
    assert (
        opening["encryption"]["initializationVector"] == base64.b64encode(IV).decode()
    )
    assert not recorder.queued
    sending = json.loads(recorder.requests[6].content)
    assert sending["invoiceSize"] == len(xml)
    assert sending["invoiceHash"] == sha256_b64(xml)
    assert (
        decrypt_aes_cbc(
            base64.b64decode(sending["encryptedInvoiceContent"]), key=KEY, iv=IV
        )
        == xml
    )


# W2: carry the first search page's cursor and the exact answer state forward.
def test_search_pages_through_the_cursor(
    recorder: Recorder,
    authenticated: dict[str, Any],
    inv_query_metadata_resp: BaseFactory[spec.QueryInvoicesMetadataResponse],
) -> None:
    filters = {**FILTERS, "invoice_schema": "FA3"}
    recorder.queue(metadata_page(inv_query_metadata_resp, count=1, has_more=True))
    first = ask(
        "invoices.search", {"filters": filters}, json.dumps(authenticated["state"])
    )
    assert first["ok"] is True, first
    assert len(first["result"]["items"]) == 1
    assert isinstance(first["result"]["next_cursor"], str)
    recorder.queue(metadata_page(inv_query_metadata_resp, count=2, has_more=False))
    second = ask(
        "invoices.search",
        {"filters": filters, "cursor": first["result"]["next_cursor"]},
        json.dumps(first["state"]),
    )
    assert second["ok"] is True, second
    assert len(second["result"]["items"]) == 2
    assert second["result"]["next_cursor"] is None
    assert [(r.method, r.url.path) for r in recorder.requests[5:]] == [
        ("POST", "/invoices/query/metadata"),
        ("POST", "/invoices/query/metadata"),
    ]
    assert [r.url.params["pageOffset"] for r in recorder.requests[5:]] == ["0", "1"]
    for request in recorder.requests[5:]:
        body = json.loads(request.content)
        assert body["formType"] == "FA"
        assert body["subjectType"] == "Subject1"
    assert not recorder.queued


# W3: preserve binary download content across the JSON response encoding.
def test_download_returns_base64_bytes(
    recorder: Recorder, authenticated: dict[str, Any]
) -> None:
    content = b'<?xml version="1.0"?><Invoice>\xc5\xbc\xc3\xb3\xc5\x82\xc4\x87</Invoice>\x00\xff'
    recorder.queued.append(httpx.Response(200, content=content))
    answer = ask(
        "invoices.download", {"ksef_number": KSEF_1}, json.dumps(authenticated["state"])
    )
    assert answer["ok"] is True, answer
    assert base64.b64decode(answer["result"], validate=True) == content
    assert [(r.method, r.url.path) for r in recorder.requests[5:]] == [
        ("GET", f"/invoices/ksef/{KSEF_1}")
    ]
    assert recorder.requests[-1].headers["authorization"] == "Bearer access-token"
    assert not recorder.queued


# W4: resume the export job, decrypt a real ZIP, then resume the exported archive.
def test_export_runs_to_its_archive(
    recorder: Recorder,
    authenticated: dict[str, Any],
    inv_export_resp: BaseFactory[spec.ExportInvoicesResponse],
    inv_export_status_resp: BaseFactory[spec.InvoiceExportStatusResponse],
) -> None:
    payload = archive()
    encrypted = encrypt_invoice(payload, key=KEY, iv=IV)
    recorder.queue(
        inv_export_resp.build(referenceNumber="E" * 36).model_dump(
            mode="json", by_alias=True
        ),
        status_code=201,
    )
    with (
        patch("ksef2._clients.invoices.generate_session_key", return_value=(KEY, IV)),
        patch("ksef2._clients.invoices.encrypt_symmetric_key", return_value=b"enc-key"),
    ):
        started = ask(
            "invoices.export.filters",
            {"filters": FILTERS, "compression_type": "zip"},
            json.dumps(authenticated["state"]),
        )
    assert started["ok"] is True, started
    assert started["state"]["handle"] == started["result"]
    assert started["state"]["handle"]["reference_number"] == "E" * 36
    status = package_status(inv_export_status_resp, 200, part_count=1)
    status["package"]["size"] = len(payload)
    status["package"]["compressionType"] = "Zip"
    status["package"]["parts"][0].update(
        partSize=len(payload),
        partHash=sha256_b64(payload),
        encryptedPartSize=len(encrypted),
        encryptedPartHash=sha256_b64(encrypted),
    )
    recorder.queue(status)
    recorder.queued.append(httpx.Response(200, content=encrypted))
    waited = ask("export_job.wait", {}, json.dumps(started["state"]))
    assert waited["ok"] is True, waited
    assert waited["state"]["handle"] == waited["result"]
    assert base64.urlsafe_b64decode(waited["result"]["archive"]) == payload
    listed = ask("exported_invoices.invoices", {}, json.dumps(waited["state"]))
    assert listed["ok"] is True, listed
    assert listed["result"] == [
        [KSEF_1, base64.b64encode(b"<one />").decode()],
        [KSEF_2, base64.b64encode(b"<two />").decode()],
    ]
    assert listed["state"]["handle"] == waited["state"]["handle"]
    assert [(r.method, r.url.path) for r in recorder.requests[5:]] == [
        ("POST", "/invoices/exports"),
        ("GET", "/invoices/exports/" + "E" * 36),
        ("GET", "/export/part-1"),
    ]
    body = json.loads(recorder.requests[5].content)
    assert body["compressionType"] == "Zip"
    assert body["encryption"]["initializationVector"] == base64.b64encode(IV).decode()
    assert "authorization" not in recorder.requests[-1].headers
    assert not recorder.queued


# W5: PEM literals cross JSON and produce a real XAdES signature at KSeF.
def test_xades_auth_with_pem_credentials(
    recorder: Recorder, auth_answers: list[dict[str, Any]]
) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    cert = self_signed(key)
    schema = MANIFEST["$defs"]["XAdESCredentials"]
    assert set(schema["required"]) == {"cert_pem", "key_pem"}
    assert schema["properties"]["key_pem"]["type"] == "string"
    for response in auth_answers:
        recorder.queue(response)
    answer = ask(
        "auth.with_xades",
        {
            "nip": NIP,
            "credentials": {
                "cert_pem": cert.public_bytes(Encoding.PEM).decode(),
                "key_pem": key_pem(key).decode(),
            },
        },
        INITIAL_STATE,
    )
    assert answer["ok"] is True, answer
    assert answer["state"]["authentication"] == answer["result"]
    assert answer["state"]["authentication"]["access_token"] == "access-token"
    assert [(r.method, r.url.path) for r in recorder.requests] == [
        ("POST", "/auth/challenge"),
        ("POST", "/auth/xades-signature"),
        ("GET", "/auth/" + "R" * 36),
        ("POST", "/auth/token/redeem"),
    ]
    signed = ElementTree.fromstring(recorder.requests[1].content)
    assert signed.findtext("{*}Challenge") == "A" * 36
    assert signed.findtext(".//{*}Nip") == NIP
    assert signed.findtext(".//{http://www.w3.org/2000/09/xmldsig#}SignatureValue")
    assert (
        signed.find(".//{http://uri.etsi.org/01903/v1.3.2#}SignedProperties")
        is not None
    )
    assert not recorder.queued


# W6: retain a generated token's resume state while reading status and reference.
def test_generated_token_waits_from_its_state(
    recorder: Recorder,
    authenticated: dict[str, Any],
    token_generate_resp: BaseFactory[spec.GenerateTokenResponse],
    token_status_resp: BaseFactory[spec.TokenStatusResponse],
) -> None:
    recorder.queue(
        token_generate_resp.build(
            referenceNumber="T" * 36, token="one-time-token"
        ).model_dump(mode="json", by_alias=True)
    )
    generated = ask(
        "tokens.generate",
        {"permissions": ["invoice_read"], "description": "JSON workflow"},
        json.dumps(authenticated["state"]),
    )
    assert generated["ok"] is True, generated
    assert generated["result"]["token"] == "one-time-token"
    assert generated["state"]["handle"] == generated["result"]["state"]
    recorder.queue(
        token_status_resp.build(
            status=spec.AuthenticationTokenStatus.Active
        ).model_dump(mode="json", by_alias=True)
    )
    waited = ask("generated_token.wait", {}, json.dumps(generated["state"]))
    assert waited["ok"] is True, waited
    assert waited["result"]["status"] == "active"
    referenced = ask(
        "generated_token.reference_number", {}, json.dumps(waited["state"])
    )
    assert referenced["ok"] is True, referenced
    assert referenced["result"] == "T" * 36
    assert referenced["state"]["handle"] == generated["state"]["handle"]
    assert [(r.method, r.url.path) for r in recorder.requests[5:]] == [
        ("POST", "/tokens"),
        ("GET", "/tokens/" + "T" * 36),
    ]
    assert json.loads(recorder.requests[5].content) == {
        "permissions": ["InvoiceRead"],
        "description": "JSON workflow",
    }
    assert not recorder.queued


HANDLE_IDS = {op["id"] for op in MANIFEST["operations"] if op["receiver"] == "handle"}
ARGUMENT_FREE_HANDLES = [
    op.id for op in operations().values() if op.id in HANDLE_IDS and not op.required
]


# W7: every resumable argument-free member returns JSON, even with HTTP offline.
@pytest.mark.parametrize("op", ARGUMENT_FREE_HANDLES)
def test_every_argument_free_handle_operation_answers_json(
    op: str, recorder: Recorder
) -> None:
    states = {
        "generated_token": GeneratedTokenResumeState(
            reference_number=SESSION_REF
        ).to_dict(mode="json"),
        "certificate_enrollment": CertificateEnrollmentResumeState(
            reference_number=SESSION_REF
        ).to_dict(mode="json"),
        "permission_operation": PermissionOperationResumeState(
            reference_number=SESSION_REF
        ).to_dict(mode="json"),
        "invoice_submission": InvoiceSubmissionResumeState(
            reference_number=INVOICE_REF, session_reference_number=SESSION_REF
        ).to_dict(mode="json"),
        "export_job": ExportResumeState(
            reference_number=SESSION_REF,
            aes_key=SecretStr(base64.b64encode(KEY).decode()),
            iv=SecretStr(base64.b64encode(IV).decode()),
        ).to_dict(mode="json"),
        "exported_invoices": ExportedInvoicesData(archive=archive()).model_dump(
            mode="json"
        ),
    }
    recorder.fail_with(httpx.ConnectError("offline"))
    answer = ask(
        op,
        {},
        envelope(
            authentication=session_state(),
            online_session=online_state(),
            handle=states[op.partition(".")[0]],
        ),
    )
    assert answer["ok"] is True or answer["ok"] is False
    if not answer["ok"]:
        assert answer["error"]["code"] == "TRANSPORT_ERROR", answer


def test_unrelated_handle_is_not_validated(recorder: Recorder) -> None:
    # A non-handle operation must preserve even a handle it cannot interpret.
    saved = {"opaque": ["binding-owned state"]}
    recorder.queue(peppol_page(1, has_more=False))
    answer = ask("peppol.list", {}, envelope(handle=saved))
    assert answer["ok"] is True, answer
    assert answer["state"]["handle"] == saved
    assert [(r.method, r.url.path) for r in recorder.requests] == [
        ("GET", "/peppol/query")
    ]
    assert recorder.requests[0].url.params["pageOffset"] == "0"
