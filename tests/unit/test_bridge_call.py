"""The JSON dispatcher: one operation in, one JSON document out.

These tests run real SDK clients over a faked HTTP transport, so they cover what a
binding actually sees: the envelope of each answer, the state that has to survive a
call, the code a rejected call reports, and what never appears in a failure. No test
here reaches the network, and none hands a Python object to ``call()``: every input
is a string.
"""

import base64
import json
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from polyfactory.factories.pydantic_factory import ModelFactory
from pydantic import SecretBytes, SecretStr, ValidationError

import ksef2.bridge as bridge
from ksef2 import Client, Environment, FormSchema
from ksef2._core import exceptions
from ksef2._domain.models.auth import AuthenticationResumeState
from ksef2._domain.models.certificates import CertificateEnrollmentResumeState
from ksef2._domain.models.invoices import (
    ExportedInvoicesData,
    ExportResumeState,
    InvoicePackage,
    InvoiceSubmissionResumeState,
    PackagePart,
)
from ksef2._domain.models.permissions import PermissionOperationResumeState
from ksef2._domain.models.session import OnlineSessionResumeState
from ksef2._domain.models.tokens import GeneratedTokenResumeState
from ksef2._infra.schema.api import spec
from ksef2.bridge import _runtime
from ksef2.bridge._catalog import EXCLUDED_BATCH, EXCLUDED_PAGER
from ksef2.bridge._dispatch import _RESOLVERS, _Scope, _receiver, read_envelope
from ksef2.bridge._json import dump_state, encode, error_of
from ksef2.bridge._operations import operations

#: The client builder the dispatcher uses by default, kept because the fixture below
#: replaces it for every test in this module.
DEFAULT_BUILDER = _runtime.build_client

BASE_URL = "https://ksef.mock"
NIP = "5261040828"
SESSION_REF = "20250625-SO-2C3E6C8000-B675CF5D68-07"
PRIVATE_KEY_MARKER = "PRIVATE-KEY-MATERIAL-MARKER"
ACCESS_TOKEN = "access-token-secret"
ARCHIVE = b"\x00\x01\x02\xfe"
KEY = base64.b64encode(b"0" * 32).decode()
INITIALIZER = base64.b64encode(b"0" * 16).decode()


class Recorder:
    """A transport the test drives, recording every request it answers."""

    def __init__(self) -> None:
        """Start with no queued answers and no recorded requests."""
        self.queued: list[httpx.Response] = []
        self.requests: list[httpx.Request] = []
        self.failing: Exception | None = None

    def queue(
        self,
        body: object,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Queue the JSON answer of the next request.

        Args:
            body: The document to answer with.
            status_code: The HTTP status to answer with.
            headers: Response headers, for the media type KSeF answers an error in.
        """
        self.queued.append(httpx.Response(status_code, json=body, headers=headers))

    def fail_with(self, error: Exception) -> None:
        """Make every following request raise instead of being answered.

        Args:
            error: The transport failure to raise.
        """
        self.failing = error

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Answer one request, recording it.

        Args:
            request: The request the SDK made.

        Returns:
            The next queued response.

        Raises:
            Exception: The transport failure this transport was set to raise.
            AssertionError: Nothing was queued for this request.
        """
        self.requests.append(request)
        if self.failing is not None:
            raise self.failing
        if not self.queued:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        answer = self.queued.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def paths(self) -> list[str]:
        """The path of every request answered so far."""
        return [request.url.path for request in self.requests]


def envelope(**slots: object) -> str:
    """Write a state envelope with the given slots filled.

    Args:
        **slots: The slots to fill; every other slot stays ``null``.

    Returns:
        The envelope as JSON text.
    """
    state: dict[str, object] = {
        "environment": "test",
        "authentication": None,
        "online_session": None,
        "batch_session": None,
        "handle": None,
    }
    state.update(slots)
    return json.dumps(state)


def plain() -> dict[str, Any]:
    """Return the empty envelope, as a dispatcher reports it.

    Returns:
        The five slots of an envelope with nothing resumed yet.
    """
    return json.loads(envelope())


def session_state() -> dict[str, Any]:
    """Write a saved session, the way an envelope holds it.

    Returns:
        The exported ``AuthenticationResumeState`` of a session.
    """
    return AuthenticationResumeState(
        access_token=SecretStr(ACCESS_TOKEN),
        access_token_valid_until=datetime(2030, 1, 1, tzinfo=UTC),
        refresh_token=SecretStr("refresh-token-secret"),
        refresh_token_valid_until=datetime(2030, 6, 1, tzinfo=UTC),
    ).to_dict(mode="json")


def online_state() -> dict[str, Any]:
    """Write a saved online session, the way an envelope holds it.

    Returns:
        The exported ``OnlineSessionResumeState`` of an open session.
    """
    return OnlineSessionResumeState(
        reference_number=SESSION_REF,
        aes_key=SecretStr(KEY),
        iv=SecretStr(INITIALIZER),
        form_code=FormSchema.FA3,
        valid_until=datetime(2030, 1, 1, tzinfo=UTC),
    ).to_dict(mode="json")


def saved_export() -> dict[str, Any]:
    """Write a finished export, the way an envelope holds it.

    Returns:
        The JSON form of an ``ExportedInvoicesData`` snapshot of a small archive.
    """
    return ExportedInvoicesData(
        archive=ARCHIVE, package=None, metadata=None
    ).model_dump(mode="json")


def peppol_page(count: int, has_more: bool) -> dict[str, Any]:
    """Write the answer of a Peppol provider query.

    Args:
        count: How many providers the page carries.
        has_more: Whether the collection continues after it.

    Returns:
        The response document.
    """
    return {
        "peppolProviders": [
            {
                "id": f"PDE{index:06d}",
                "name": f"Provider {index}",
                "dateCreated": "2030-01-01T00:00:00Z",
            }
            for index in range(1, count + 1)
        ],
        "hasMore": has_more,
    }


PROBLEM_JSON = {"content-type": "application/problem+json"}
"""The media type KSeF answers a rejected request in when the SDK asks for it."""


def problem(
    code: int,
    description: str,
    *,
    status: int = 400,
    trace_id: str = "trace-1",
    details: list[str] | None = None,
) -> dict[str, Any]:
    """Write the Problem Details document KSeF rejects a request with.

    Args:
        code: The KSeF exception code it reports.
        description: The text it gives that code.
        status: The HTTP status of the rejection.
        trace_id: The identifier KSeF asks callers to quote when reporting it.
        details: The further lines it adds for this occurrence.

    Returns:
        The error document.
    """
    return {
        "title": "Bad Request",
        "status": status,
        "instance": "/api/v2/online/sessions",
        "detail": "Zgloszenie zawieralo bledy.",
        "errors": [{"code": code, "description": description, "details": details}],
        "timestamp": "2030-01-01T00:00:00Z",
        "traceId": trace_id,
    }


def ask(op: str, args: object, state: str | None) -> dict[str, Any]:
    """Dispatch one call and parse the document it answered with.

    Args:
        op: The operation id.
        args: The arguments, as a Python object.
        state: The state envelope as JSON text.

    Returns:
        The answer, decoded.
    """
    document = bridge.call(op, json.dumps(args), state)
    assert isinstance(document, str)
    parsed = json.loads(document)
    assert parsed["ok"] is True or set(parsed) == {"ok", "error"}
    return parsed


@pytest.fixture
def recorder() -> Recorder:
    """Provide a transport the dispatcher's clients answer from.

    Returns:
        The recorder every request lands in.
    """
    return Recorder()


@pytest.fixture(autouse=True)
def clients(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> Iterator[list[Client]]:
    """Give the dispatcher clients that answer from the recorded transport.

    The cache is released afterwards, so no test inherits a client built over another
    test's transport.

    Yields:
        The list the clients this test builds are recorded in.
    """
    built: list[Client] = []

    def build(environment: Environment) -> Client:
        client = Client(
            environment,
            http_client=httpx.Client(
                base_url=BASE_URL, transport=httpx.MockTransport(recorder)
            ),
        )
        built.append(client)
        return client

    monkeypatch.setattr(_runtime, "build_client", build)
    yield built
    bridge.close()


def test_plain_call_returns_json(recorder: Recorder) -> None:
    """A call takes JSON arguments and answers with one JSON document."""
    recorder.queue(peppol_page(1, has_more=False))

    document = ask("peppol.list", {}, envelope())

    assert document == {
        "ok": True,
        "result": {
            "items": [
                {
                    "id": "PDE000001",
                    "name": "Provider 1",
                    "date_created": "2030-01-01T00:00:00Z",
                }
            ],
            "next_cursor": None,
        },
        "state": plain(),
    }
    assert recorder.paths == ["/peppol/query"]


def test_paged_call_passes_the_cursor(recorder: Recorder) -> None:
    """A collection operation takes the cursor of the page after the one it returned."""
    recorder.queue(peppol_page(1, has_more=True))

    first = ask("peppol.list", {}, envelope())

    assert first["result"]["next_cursor"] is not None

    recorder.queue(peppol_page(2, has_more=True))
    second = ask("peppol.list", {"cursor": first["result"]["next_cursor"]}, envelope())

    assert [item["id"] for item in second["result"]["items"]] == [
        "PDE000001",
        "PDE000002",
    ]
    assert recorder.requests[1].url.params["pageOffset"] == "1"
    assert recorder.requests[0].url.params["pageOffset"] == "0"

    refused = ask("peppol.list", {"cursor": 1}, envelope())
    assert refused["ok"] is False
    assert refused["error"]["code"] == "ARGUMENT_ERROR"
    assert "neither a string nor null" in refused["error"]["message"]

    recorder.queue(peppol_page(1, has_more=False))
    again = ask("peppol.list", {"cursor": None}, envelope())

    assert again["result"]["next_cursor"] is None
    assert recorder.requests[-1].url.params["pageOffset"] == "0"


def test_cursor_is_refused_where_there_is_no_page(recorder: Recorder) -> None:
    """Only a collection operation accepts a cursor."""
    document = ask("encryption.get_certificates", {"cursor": "anything"}, envelope())

    assert document["ok"] is False
    assert document["error"]["code"] == "ARGUMENT_ERROR"
    assert "cursor" in document["error"]["message"]
    assert recorder.paths == []


def test_handle_resumes_from_state(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finished export travels as state, and reading it again needs no client."""

    def build(_: Environment) -> Client:
        raise AssertionError("a saved export result answers without a client")

    monkeypatch.setattr(_runtime, "build_client", build)

    document = ask("exported_invoices.archive", {}, envelope(handle=saved_export()))

    assert base64.b64decode(document["result"]) == ARCHIVE
    assert document["state"]["handle"] == saved_export()
    assert recorder.requests == []


def test_online_session_operation(
    recorder: Recorder,
    inv_session_status_resp: ModelFactory[spec.SessionStatusResponse],
) -> None:
    """An online session is resumed from the envelope, and its bearer reaches KSeF."""
    status = inv_session_status_resp.build(
        status=spec.StatusInfo(code=3, description="Sesja otwarta")
    )
    recorder.queue(status.model_dump(mode="json", by_alias=True))

    document = ask(
        "online.get_status",
        {},
        envelope(authentication=session_state(), online_session=online_state()),
    )

    assert document["result"]["status"]["code"] == 3
    request = recorder.requests[0]
    assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert SESSION_REF in request.url.path
    assert document["state"]["online_session"] == online_state()


def test_online_session_operation_needs_its_session(recorder: Recorder) -> None:
    """A session operation without that session in the envelope is a bad call."""
    document = ask("online.get_status", {}, envelope(authentication=session_state()))

    assert document["ok"] is False
    assert document["error"]["code"] == "ARGUMENT_ERROR"
    assert "online_session" in document["error"]["message"]
    assert recorder.paths == []


def test_api_error_is_json(recorder: Recorder) -> None:
    """A rejection from KSeF keeps the fields a binding branches on."""
    recorder.queue(
        problem(21405, "Blad walidacji", details=["Session is not active"]),
        status_code=400,
        headers=PROBLEM_JSON,
    )

    document = ask(
        "online.get_status",
        {},
        envelope(authentication=session_state(), online_session=online_state()),
    )

    error = document["error"]
    assert document["ok"] is False
    assert issubclass(getattr(exceptions, error["type"]), exceptions.KSeFApiError)
    assert error["code"] == getattr(exceptions, error["type"]).code
    assert error["message"]
    assert error["status_code"] == 400
    assert error["ksef_code"] == 21405
    assert error["trace_id"] == "trace-1"
    assert error["details"] == ["Session is not active"]
    assert error["exception_code"] == {"name": "VALIDATION_ERROR", "value": 21405}
    assert error["context"]["code"] == error["code"]


def test_api_error_does_not_carry_the_response_body(recorder: Recorder) -> None:
    """The error names what KSeF reported, and adds nothing the caller did not ask for."""
    recorder.queue(
        problem(
            21405, "Blad walidacji", details=["INTERNAL-BLOB-OF-THE-REJECTED-REQUEST"]
        ),
        status_code=400,
        headers=PROBLEM_JSON,
    )

    document = ask(
        "online.get_status",
        {},
        envelope(authentication=session_state(), online_session=online_state()),
    )

    assert document["ok"] is False
    assert set(document) == {"ok", "error"}
    assert set(document["error"]) == {
        "type",
        "code",
        "message",
        "hint",
        "context",
        "status_code",
        "ksef_code",
        "trace_id",
        "details",
        "exception_code",
    }
    assert "instance" not in json.dumps(document)


def test_transport_error_is_json(recorder: Recorder) -> None:
    """A request that produced no usable response is reported as a transport failure."""
    recorder.fail_with(
        httpx.ConnectError(
            f"connection refused by {SESSION_REF}",
            request=httpx.Request("GET", BASE_URL),
        )
    )

    document = ask("peppol.list", {}, envelope())

    error = document["error"]
    assert document["ok"] is False
    assert error["type"] == "KSeFTransportError"
    assert error["code"] == "TRANSPORT_ERROR"
    assert error["context"]["outcome_ambiguous"] is False
    assert len(recorder.requests) > 1
    assert SESSION_REF not in json.dumps(document)


def test_unknown_operation_and_bad_arguments(recorder: Recorder) -> None:
    """An id that does not exist and a call that does not fit are both failures."""
    unknown = ask("invoices.does_not_exist", {}, envelope())
    assert unknown["error"]["code"] == "UNKNOWN_OPERATION"
    assert unknown["error"]["type"] == "KSeFArgumentError"

    not_json = json.loads(bridge.call("peppol.list", "{", envelope()))
    assert not_json["error"]["code"] == "ARGUMENT_ERROR"

    not_object = json.loads(bridge.call("peppol.list", "[]", envelope()))
    assert not_object["error"]["code"] == "ARGUMENT_ERROR"

    missing_state = json.loads(bridge.call("peppol.list", "{}", None))
    assert missing_state["error"]["code"] == "ARGUMENT_ERROR"
    assert "state_json" in missing_state["error"]["message"]

    extra_slot = json.loads(bridge.call("peppol.list", "{}", envelope(session_id="x")))
    assert extra_slot["error"]["code"] == "ARGUMENT_ERROR"
    assert "session_id" in extra_slot["error"]["message"]

    unknown_argument = ask("peppol.list", {"page_number": 2}, envelope())
    assert unknown_argument["error"]["code"] == "ARGUMENT_ERROR"
    assert "page_number" in unknown_argument["error"]["message"]

    wrong_type = ask("peppol.list", {"page_size": "ten"}, envelope())
    assert wrong_type["error"]["code"] == "ARGUMENT_ERROR"
    assert "page_size" in wrong_type["error"]["message"]

    bad_environment = json.loads(
        bridge.call("peppol.list", "{}", envelope(environment="staging"))
    )
    assert bad_environment["error"]["code"] == "ARGUMENT_ERROR"
    assert "environment" in bad_environment["error"]["message"]

    assert recorder.paths == []


def test_returned_state_is_accepted_by_the_next_call(recorder: Recorder) -> None:
    """The state one call hands back is what the next call reads, unchanged."""
    saved = session_state()

    resumed = ask("auth.resume", {"state": saved}, envelope())

    assert resumed["result"] == saved
    assert resumed["state"]["authentication"] == saved

    token = ask("authenticated.access_token", {}, json.dumps(resumed["state"]))

    assert token["result"] == ACCESS_TOKEN
    assert token["state"] == resumed["state"]

    recorder.queue(peppol_page(1, has_more=False))
    read = ask("peppol.list", {}, json.dumps(token["state"]))

    assert read["ok"] is True
    assert read["state"] == resumed["state"]
    assert recorder.paths == ["/peppol/query"]


def test_generated_token_operation(recorder: Recorder) -> None:
    """A generated token reports its state and the credential it still holds."""
    saved = GeneratedTokenResumeState(reference_number=SESSION_REF).to_dict(mode="json")

    document = ask(
        "tokens.generation", {"state": saved}, envelope(authentication=session_state())
    )

    assert document["result"] == {"state": saved, "token": None}
    assert document["state"]["handle"] == saved
    assert recorder.paths == []


def test_handle_operations_answer_from_their_own_state(recorder: Recorder) -> None:
    """Every handle kind is rebuilt from the state that names it, without a request."""
    cases = {
        "generated_token.reference_number": GeneratedTokenResumeState(
            reference_number=SESSION_REF
        ),
        "certificate_enrollment.reference_number": CertificateEnrollmentResumeState(
            reference_number=SESSION_REF
        ),
        "permission_operation.reference_number": PermissionOperationResumeState(
            reference_number=SESSION_REF
        ),
    }

    for op, state in cases.items():
        saved = state.to_dict(mode="json")

        document = ask(op, {}, envelope(authentication=session_state(), handle=saved))

        assert document["ok"] is True, document
        assert document["result"] == SESSION_REF
        assert document["state"]["handle"] == saved
    assert recorder.paths == []


def test_submission_handle_needs_its_session(recorder: Recorder) -> None:
    """A submission is continued through the session it was sent in."""
    saved = InvoiceSubmissionResumeState(
        reference_number=SESSION_REF,
        session_reference_number=SESSION_REF,
    ).to_dict(mode="json")

    missing = ask(
        "invoice_submission.reference_number",
        {},
        envelope(authentication=session_state(), handle=saved),
    )
    resumed = ask(
        "invoice_submission.reference_number",
        {},
        envelope(
            authentication=session_state(), online_session=online_state(), handle=saved
        ),
    )

    assert missing["ok"] is False
    assert missing["error"]["code"] == "ARGUMENT_ERROR"
    assert resumed["result"] == SESSION_REF
    assert recorder.paths == []


def test_export_job_continues_from_its_state(
    recorder: Recorder,
    inv_export_status_resp: ModelFactory[spec.InvoiceExportStatusResponse],
) -> None:
    """An export scheduled earlier is continued from its keys and reference."""
    status = inv_export_status_resp.build(
        status=spec.StatusInfo(code=200, description="Eksport faktur zakonczony"),
    )
    recorder.queue(status.model_dump(mode="json", by_alias=True))
    saved = ExportResumeState(
        reference_number=SESSION_REF,
        aes_key=SecretStr(KEY),
        iv=SecretStr(INITIALIZER),
    ).to_dict(mode="json")

    document = ask(
        "export_job.get_status",
        {},
        envelope(authentication=session_state(), handle=saved),
    )

    assert document["ok"] is True, document
    assert document["result"]["status"]["code"] == 200
    assert document["state"]["handle"] == saved
    assert SESSION_REF in recorder.requests[0].url.path


def test_temporal_testdata_reaches_only_the_test_environment(
    recorder: Recorder,
) -> None:
    """A TEST-only branch says so through the same failure envelope."""
    document = ask(
        "temporal_testdata.create_person",
        {"nip": NIP, "pesel": "12345678901", "description": "Somebody"},
        envelope(environment="production"),
    )

    assert document["ok"] is False
    assert document["error"]["type"] == "KSeFUnsupportedEnvironmentError"
    assert document["error"]["code"] == "UNSUPPORTED_ENVIRONMENT"
    assert recorder.paths == []


def test_a_handle_meant_for_another_operation_is_refused(recorder: Recorder) -> None:
    """State is not a general pocket: an operation that continues none says so."""
    saved = GeneratedTokenResumeState(reference_number=SESSION_REF).to_dict(mode="json")

    document = ask("peppol.list", {}, envelope(handle=saved))

    assert document["ok"] is False
    assert document["error"]["code"] == "ARGUMENT_ERROR"
    assert "handle" in document["error"]["message"]
    assert recorder.paths == []


def test_arguments_the_operation_itself_requires_are_checked(
    recorder: Recorder,
) -> None:
    """A parameter the operation needs is named, and none of it is guessed."""
    missing_type = ask("invoice_sessions.list", {}, envelope())
    missing_token = ask("auth.with_token", {"nip": NIP}, envelope())

    assert missing_type["error"]["code"] == "ARGUMENT_ERROR"
    assert "session_type" in missing_type["error"]["message"]
    assert missing_token["error"]["code"] == "ARGUMENT_ERROR"
    assert "ksef_token" in missing_token["error"]["message"]
    assert recorder.paths == []


def test_a_handle_operation_needs_the_state_of_its_handle(recorder: Recorder) -> None:
    """Continuing a handle names the state it needs rather than guessing one."""
    document = ask(
        "generated_token.reference_number", {}, envelope(authentication=session_state())
    )

    assert document["error"]["code"] == "ARGUMENT_ERROR"
    assert "carries no handle" in document["error"]["message"]
    assert recorder.paths == []


def test_a_handle_of_another_kind_is_refused(recorder: Recorder) -> None:
    """The state of one handle cannot stand in for the state of another.

    The export state asks for keys the permission-operation state does not carry, so
    the call is refused field by field before anything is sent.
    """
    saved = PermissionOperationResumeState(reference_number=SESSION_REF).to_dict(
        mode="json"
    )

    document = ask(
        "export_job.get_status",
        {},
        envelope(authentication=session_state(), handle=saved),
    )

    assert document["error"]["code"] == "ARGUMENT_ERROR"
    assert "state_json.handle" in document["error"]["message"]
    assert recorder.paths == []


def test_result_values_are_written_as_one_json_form() -> None:
    """Every kind of value an operation can hand back has one JSON form.

    The kinds are the ones the public API returns bare: bytes, text, numbers,
    durations, dates, paths and containers of those.
    """
    assert encode("op", None) is None
    assert encode("op", True) is True
    assert encode("op", b"\xff\x00") == "/wA="
    assert encode("op", bytearray(b"\xff\x00")) == "/wA="
    assert encode("op", memoryview(b"\xff\x00")) == "/wA="
    assert encode("op", SecretStr("a-secret")) == "a-secret"
    assert encode("op", SecretBytes(b"\xff")) == "/w=="
    assert encode("op", datetime(2030, 1, 1, tzinfo=UTC)) == "2030-01-01T00:00:00+00:00"
    assert encode("op", date(2030, 1, 1)) == "2030-01-01"
    assert encode("op", timedelta(minutes=2)) == "0:02:00"
    assert encode("op", Decimal("1.50")) == 1.5
    assert encode("op", UUID(int=7)) == "00000000-0000-0000-0000-000000000007"
    assert encode("op", PurePosixPath("/tmp/a.zip")) == "/tmp/a.zip"
    assert encode("op", Environment.TEST) == Environment.TEST.value
    assert encode("op", session_state()) == session_state() | {"format_version": 1}
    assert encode("op", spec.StatusInfo(code=200, description="OK")) == {
        "code": 200,
        "description": "OK",
        "details": None,
    }
    assert encode("op", {"k": b"\xff"}) == {"k": "/w=="}
    assert encode("op", (1, 2)) == [1, 2]
    assert encode("op", iter([1, 2])) == [1, 2]
    with pytest.raises(TypeError, match="no JSON form"):
        encode("op", object())


def test_failure_context_holds_only_what_a_caller_can_act_on() -> None:
    """Context is reported as data, and never as bytes or as a secret."""
    described = error_of(
        exceptions.KSeFException(
            "Something happened.",
            form=Environment.TEST,
            status=spec.StatusInfo(code=200, description="OK"),
            when=datetime(2030, 1, 1, tzinfo=UTC),
            amount=Decimal("1.50"),
            where=PurePosixPath("/tmp/a.zip"),
            ident=UUID(int=7),
            archive=b"invoice-bytes",
            mystery=SecretStr("a-secret"),
            references=[b"one", object()],
            odd=object(),
        )
    )

    assert described["context"] == {
        "form": Environment.TEST.value,
        "status": {"code": 200, "description": "OK", "details": None},
        "when": "2030-01-01T00:00:00+00:00",
        "amount": "1.50",
        "where": "/tmp/a.zip",
        "ident": "00000000-0000-0000-0000-000000000007",
        "archive": None,
        "mystery": None,
        "references": [None, "object"],
        "odd": "object",
        "code": "SDK_ERROR",
    }


def test_failure_json_describes_the_failure_and_nothing_else() -> None:
    """The error document keeps its shape, and drops what must not leave Python."""
    described = error_of(
        exceptions.KSeFException(
            "Something happened.",
            hint="Do the other thing.",
            access_token=SecretStr("one-time-token-secret"),
            payload=b"invoice-bytes",
            url="https://storage.mock/presigned?sign=x",
            nested={"private_key": "-----BEGIN", "count": 2},
            plain="kept",
        )
    )

    assert described["type"] == "KSeFException"
    assert described["code"] == "SDK_ERROR"
    assert described["message"] == "Something happened."
    assert described["hint"] == "Do the other thing."
    context = cast("dict[str, object]", described["context"])
    assert context["plain"] == "kept"
    assert context["nested"] == {"count": 2}

    text = json.dumps(described)
    for secret in ("one-time-token-secret", "invoice-bytes", "presigned", "-----BEGIN"):
        assert secret not in text

    bad_json = error_of(json.JSONDecodeError("Expecting value", "<document>", 3))
    assert bad_json["type"] == "JSONDecodeError"
    assert bad_json["code"] == "ARGUMENT_ERROR"
    assert "<document>" not in json.dumps(bad_json)

    invalid = error_of(ValidationError.from_exception_data("InvoiceQuery", []))
    assert invalid["type"] == "ValidationError"
    assert invalid["code"] == "VALIDATION_ERROR"

    unexpected = error_of(ValueError("a bug in the SDK"))
    assert unexpected["code"] == "SDK_ERROR"


def test_the_default_client_is_a_real_one() -> None:
    """What every test here replaces is itself a working client for that environment."""
    client = DEFAULT_BUILDER(Environment.TEST)
    try:
        assert cast("Any", client)._environment is Environment.TEST
    finally:
        client.close()


def test_state_of_another_kind_is_refused(recorder: Recorder) -> None:
    """A handle of one kind is not accepted where another kind is continued."""
    document = ask("export_job.get_status", {}, envelope(handle=saved_export()))

    assert document["ok"] is False
    assert document["error"]["code"] == "ARGUMENT_ERROR"
    assert "handle" in document["error"]["message"]
    assert "ExportResumeState" in document["error"]["hint"]
    assert recorder.paths == []


def test_concurrent_calls_share_one_client(
    clients: list[Client], recorder: Recorder
) -> None:
    """Calls from several threads each answer in full, on one client."""
    # Build the operation table before testing concurrent client use.
    assert "peppol.list" in operations()
    threads = 8
    body = peppol_page(1, has_more=False)
    recorder.queued.extend(httpx.Response(200, json=body) for _ in range(threads))
    answers: list[dict[str, Any]] = []
    lock = threading.Lock()

    def answer_one() -> None:
        document = json.loads(bridge.call("peppol.list", "{}", envelope()))
        with lock:
            answers.append(document)

    runners = [threading.Thread(target=answer_one) for _ in range(threads)]
    for runner in runners:
        runner.start()
    for runner in runners:
        runner.join(timeout=5)
        assert not runner.is_alive()

    assert len(answers) == threads
    assert all(document["ok"] for document in answers)
    assert len(recorder.requests) == threads
    assert len(clients) == 1


@pytest.fixture
def blocked_calls(
    clients: list[Client], monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[threading.Event, threading.Event, threading.Event]]:
    """Block requests and report when a closer starts waiting for them.

    Yields:
        Events for request entry, request release and a waiting closer.
    """
    entered = threading.Event()
    release = threading.Event()
    closing = threading.Event()
    condition_wait = _runtime._CONDITION.wait

    def handler(request: httpx.Request) -> httpx.Response:
        entered.set()
        assert release.wait(timeout=5)
        return httpx.Response(200, json=peppol_page(0, has_more=False))

    def build(environment: Environment) -> Client:
        client = Client(
            environment,
            http_client=httpx.Client(
                base_url=BASE_URL, transport=httpx.MockTransport(handler)
            ),
        )
        clients.append(client)
        return client

    def wait(timeout: float | None = None) -> bool:
        # This runs under the registry condition, after the closer has marked TEST.
        if Environment.TEST in _runtime._CLOSING:
            closing.set()
        return condition_wait(timeout=5 if timeout is None else timeout)

    monkeypatch.setattr(_runtime, "build_client", build)
    monkeypatch.setattr(_runtime._CONDITION, "wait", wait)
    try:
        yield entered, release, closing
    finally:
        release.set()


def finish_calls(runners: list[threading.Thread], release: threading.Event) -> None:
    """Unblock requests and verify that every started thread finishes.

    Args:
        runners: The threads started by the test.
        release: The event letting blocked requests return.
    """
    release.set()
    for runner in runners:
        runner.join(timeout=5)
    assert all(not runner.is_alive() for runner in runners)


def test_calls_run_concurrently(
    clients: list[Client], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four calls reach the transport together and share exactly one client."""
    assert "peppol.list" in operations()
    barrier = threading.Barrier(4, timeout=5)
    answers: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        barrier.wait(timeout=5)
        return httpx.Response(200, json=peppol_page(0, has_more=False))

    def build(environment: Environment) -> Client:
        client = Client(
            environment,
            http_client=httpx.Client(
                base_url=BASE_URL, transport=httpx.MockTransport(handler)
            ),
        )
        clients.append(client)
        return client

    monkeypatch.setattr(_runtime, "build_client", build)
    runners = [
        threading.Thread(
            target=lambda: answers.append(ask("peppol.list", {}, envelope()))
        )
        for _ in range(4)
    ]
    for runner in runners:
        runner.start()
    for runner in runners:
        runner.join(timeout=5)
    assert all(not runner.is_alive() for runner in runners)
    assert len(answers) == 4
    assert all(answer["ok"] is True for answer in answers)
    assert len(clients) == 1
    assert _runtime._IN_FLIGHT == {}


def test_close_waits_for_calls_in_flight(
    blocked_calls: tuple[threading.Event, threading.Event, threading.Event],
) -> None:
    """Closing the bridge waits for an active request before clearing the cache."""
    entered, release, closing = blocked_calls
    answers: list[dict[str, Any]] = []
    closed = threading.Event()

    def close() -> None:
        bridge.close()
        closed.set()

    caller = threading.Thread(
        target=lambda: answers.append(ask("peppol.list", {}, envelope()))
    )
    closer = threading.Thread(target=close)
    runners = [caller]
    caller.start()
    try:
        assert entered.wait(timeout=5)
        closer.start()
        runners.append(closer)
        assert closing.wait(timeout=5)
        closer.join(timeout=0.2)
        assert closer.is_alive()
    finally:
        finish_calls(runners, release)

    assert answers[0]["ok"] is True
    assert closed.is_set()
    assert _runtime._CLIENTS == {}
    assert _runtime._IN_FLIGHT == {}


def test_a_call_during_close_gets_a_new_client(
    clients: list[Client],
    blocked_calls: tuple[threading.Event, threading.Event, threading.Event],
) -> None:
    """A call arriving during closure waits and then uses a fresh client."""
    entered, release, closing = blocked_calls
    answers: list[dict[str, Any]] = []
    later_answers: list[dict[str, Any]] = []
    caller = threading.Thread(
        target=lambda: answers.append(ask("peppol.list", {}, envelope()))
    )
    closer = threading.Thread(target=bridge.close)
    later = threading.Thread(
        target=lambda: later_answers.append(ask("peppol.list", {}, envelope()))
    )
    runners = [caller]
    caller.start()
    try:
        assert entered.wait(timeout=5)
        closer.start()
        runners.append(closer)
        assert closing.wait(timeout=5)
        later.start()
        runners.append(later)
        later.join(timeout=0.2)
        assert later.is_alive()
        assert len(clients) == 1
    finally:
        finish_calls(runners, release)

    assert answers[0]["ok"] is True
    assert later_answers[0]["ok"] is True
    assert len(clients) == 2
    assert _runtime._CLIENTS[Environment.TEST] is clients[1]
    assert _runtime._IN_FLIGHT == {}


def test_client_close_operation_waits_for_other_calls(
    blocked_calls: tuple[threading.Event, threading.Event, threading.Event],
) -> None:
    """The close operation waits for peers and never counts itself as a user."""
    entered, release, closing = blocked_calls
    answers: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    caller = threading.Thread(
        target=lambda: answers.append(ask("peppol.list", {}, envelope()))
    )
    closer = threading.Thread(
        target=lambda: closed.append(ask("client.close", {}, envelope()))
    )
    runners = [caller]
    caller.start()
    try:
        assert entered.wait(timeout=5)
        closer.start()
        runners.append(closer)
        assert closing.wait(timeout=5)
        closer.join(timeout=0.2)
        assert closer.is_alive()
    finally:
        finish_calls(runners, release)

    assert answers[0]["ok"] is True
    assert closed == [{"ok": True, "result": None, "state": plain()}]
    assert _runtime._CLIENTS == {}

    idle_closer = threading.Thread(
        target=lambda: closed.append(ask("client.close", {}, envelope()))
    )
    idle_closer.start()
    idle_closer.join(timeout=5)
    assert not idle_closer.is_alive()
    assert closed == [{"ok": True, "result": None, "state": plain()}] * 2


def test_two_closers_do_not_deadlock(
    blocked_calls: tuple[threading.Event, threading.Event, threading.Event],
) -> None:
    """Concurrent close operations and bridge closure finish without self-waits."""
    entered, release, closing = blocked_calls
    answers: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    bridge_closed = threading.Event()

    def close() -> None:
        bridge.close()
        bridge_closed.set()

    caller = threading.Thread(
        target=lambda: answers.append(ask("peppol.list", {}, envelope()))
    )
    closers = [
        threading.Thread(
            target=lambda: closed.append(ask("client.close", {}, envelope()))
        )
        for _ in range(2)
    ]
    closers.append(threading.Thread(target=close))
    runners = [caller]
    caller.start()
    try:
        assert entered.wait(timeout=5)
        closers[0].start()
        runners.append(closers[0])
        assert closing.wait(timeout=5)
        for closer in closers[1:]:
            closer.start()
            runners.append(closer)
        for closer in closers[1:]:
            closer.join(timeout=5)
            assert not closer.is_alive()
    finally:
        finish_calls(runners, release)

    assert answers[0]["ok"] is True
    assert closed == [{"ok": True, "result": None, "state": plain()}] * 2
    assert bridge_closed.is_set()
    assert _runtime._CLIENTS == {}
    assert _runtime._CLOSING == set()


def test_closing_one_environment_does_not_block_another(
    blocked_calls: tuple[threading.Event, threading.Event, threading.Event],
) -> None:
    """An active TEST request and its closer do not delay a DEMO close."""
    entered, release, closing = blocked_calls
    answers: list[dict[str, Any]] = []
    demo_answers: list[dict[str, Any]] = []
    caller = threading.Thread(
        target=lambda: answers.append(ask("peppol.list", {}, envelope()))
    )
    closer = threading.Thread(target=lambda: ask("client.close", {}, envelope()))
    demo_closer = threading.Thread(
        target=lambda: demo_answers.append(
            ask("client.close", {}, envelope(environment="demo"))
        )
    )
    runners = [caller]
    caller.start()
    try:
        assert entered.wait(timeout=5)
        closer.start()
        runners.append(closer)
        assert closing.wait(timeout=5)
        demo_closer.start()
        runners.append(demo_closer)
        demo_closer.join(timeout=5)
        assert not demo_closer.is_alive()
        assert caller.is_alive()
        assert closer.is_alive()
        assert demo_answers == [
            {"ok": True, "result": None, "state": plain() | {"environment": "demo"}}
        ]
    finally:
        finish_calls(runners, release)

    assert answers[0]["ok"] is True


def test_a_failed_call_releases_its_client(recorder: Recorder) -> None:
    """A transport failure releases the call's count so closing can finish."""
    recorder.fail_with(httpx.ConnectError("cannot connect"))

    answer = ask("peppol.list", {}, envelope())

    assert answer["ok"] is False
    assert answer["error"]["code"] == "TRANSPORT_ERROR"
    assert _runtime._IN_FLIGHT == {}
    closed = threading.Event()

    def close() -> None:
        bridge.close()
        closed.set()

    closer = threading.Thread(target=close)
    closer.start()
    closer.join(timeout=5)
    assert not closer.is_alive()
    assert closed.is_set()
    assert _runtime._CLIENTS == {}


def test_close_drops_the_clients_and_the_next_call_builds_one(
    recorder: Recorder,
) -> None:
    """Closing releases the clients, and a later call works again."""
    recorder.queue(peppol_page(0, has_more=False))
    recorder.queue(peppol_page(0, has_more=False))

    assert ask("peppol.list", {}, envelope())["ok"] is True
    bridge.close()
    assert ask("peppol.list", {}, envelope())["ok"] is True

    assert len(recorder.requests) == 2


def test_close_through_an_operation_forgets_only_that_environment(
    recorder: Recorder,
) -> None:
    """A binding that closed its own client does not meet a closed one again."""
    recorder.queue(peppol_page(0, has_more=False))

    closed = ask("client.close", {}, envelope())

    assert closed["result"] is None
    assert closed["state"] == plain()
    assert recorder.requests == []

    assert ask("peppol.list", {}, envelope())["ok"] is True
    assert len(recorder.requests) == 1


def test_close_without_any_call_is_not_an_error(recorder: Recorder) -> None:
    """Closing a dispatcher that never worked has nothing to release."""
    bridge.close()

    assert recorder.requests == []


def test_secrets_stay_out_of_the_failure_json(recorder: Recorder) -> None:
    """A rejected credential-bearing argument is named, never repeated."""
    document = ask(
        "auth.with_xades",
        {
            "nip": NIP,
            "credentials": {
                "cert_pem": "certificate-pem",
                "key_pem": PRIVATE_KEY_MARKER,
                "password": "key-password",
            },
            "cert": "certificate-pem",
            "private_key": PRIVATE_KEY_MARKER,
        },
        envelope(),
    )

    assert document["ok"] is False
    assert document["error"]["code"] == "ARGUMENT_ERROR"
    assert "cert" in document["error"]["message"]
    assert "private_key" in document["error"]["message"]
    assert PRIVATE_KEY_MARKER not in json.dumps(document)
    assert "key-password" not in json.dumps(document)
    assert recorder.paths == []


def test_credentials_that_are_not_key_material_are_refused_without_being_shown(
    recorder: Recorder,
) -> None:
    """The XAdES operation reads its key material from one argument, as the manifest says."""
    document = ask(
        "auth.with_xades",
        {
            "nip": NIP,
            "credentials": {
                "cert_pem": PRIVATE_KEY_MARKER,
                "key_pem": PRIVATE_KEY_MARKER,
                "password": "p",
            },
        },
        envelope(),
    )

    assert document["ok"] is False
    assert document["error"]["code"] == "ARGUMENT_ERROR"
    assert document["error"]["type"] == "KSeFArgumentError"
    assert PRIVATE_KEY_MARKER not in json.dumps(document)
    assert recorder.paths == []


def test_every_operation_is_callable_or_says_why() -> None:
    """The dispatcher covers every operation the manifest publishes."""
    entries = cast("list[dict[str, Any]]", bridge.manifest()["operations"])
    documented = {entry["id"] for entry in entries}
    table = operations()

    assert set(table) == documented


def test_arguments_are_validated_against_the_operation_itself(
    recorder: Recorder,
) -> None:
    """An argument is read as the member declares it, not as a bare JSON type."""
    recorder.queue(peppol_page(0, has_more=False))

    document = ask("peppol.list", {"params": {"page_size": 20}}, envelope())

    assert document["ok"] is True
    assert recorder.requests[0].url.params["pageSize"] == "20"

    recorder.queue(peppol_page(0, has_more=False))
    rejected = ask("peppol.list", {"params": {"page_size": 5}}, envelope())

    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "ARGUMENT_ERROR"
    assert "params" in rejected["error"]["message"]


def test_bytes_go_in_and_out_as_base64(recorder: Recorder) -> None:
    """Bytes cross the boundary the way the manifest describes them."""
    written = base64.b64encode(ARCHIVE).decode()

    archive = ask("exported_invoices.archive", {}, envelope(handle=saved_export()))
    modelled = ask("exported_invoices.to_model", {}, envelope(handle=saved_export()))

    assert archive["result"] == written
    assert base64.b64decode(archive["result"]) == ARCHIVE
    assert base64.urlsafe_b64decode(modelled["result"]["archive"]) == ARCHIVE
    assert modelled["state"]["handle"] == saved_export()
    assert recorder.requests == []


def test_exported_invoices_snapshot_round_trips(recorder: Recorder) -> None:
    """A snapshot sent through the dispatcher comes back as the result that reads it."""
    rebuilt = ask("exported_invoices.from_model", {"data": saved_export()}, envelope())

    assert rebuilt["result"] == saved_export()
    assert rebuilt["state"]["handle"] == saved_export()
    assert recorder.requests == []


def test_public_entry_points_run_the_same_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ksef2.bridge.call`` and ``close`` are the dispatcher, with the same answers."""
    recorder = Recorder()
    recorder.queue(peppol_page(1, has_more=False))
    built: list[Client] = []

    def build(environment: Environment) -> Client:
        client = Client(
            environment,
            http_client=httpx.Client(
                base_url=BASE_URL, transport=httpx.MockTransport(recorder)
            ),
        )
        built.append(client)
        return client

    monkeypatch.setattr(_runtime, "build_client", build)
    recorder.queue(peppol_page(1, has_more=False))
    recorder.queue(peppol_page(1, has_more=False))

    document = json.loads(bridge.call("peppol.list", "{}", envelope()))
    bridge.close()
    again = json.loads(bridge.call("peppol.list", "{}", envelope()))
    bridge.close()

    assert [item["id"] for item in document["result"]["items"]] == ["PDE000001"]
    assert again["ok"] is True
    assert len(built) == 2


def test_a_result_with_no_json_form_is_not_silently_dropped() -> None:
    """A member that hands back what the manifest does not describe is a bug, not a null."""

    class Unencodable:
        """A result the dispatcher was never told about."""

    with pytest.raises(TypeError, match="has no JSON form"):
        encode("peppol.list", Unencodable())


def test_excluded_operations_answer_unknown_with_their_reason(
    recorder: Recorder,
) -> None:
    """Excluded ids explain the manifest's reason without making a request."""
    for op, reason in (
        ("pager.page", EXCLUDED_PAGER),
        ("invoice_search.page", EXCLUDED_PAGER),
        ("batch_service.submit", EXCLUDED_BATCH),
        ("authenticated.batch_session", EXCLUDED_BATCH),
    ):
        document = ask(op, {}, envelope())

        assert document["ok"] is False
        assert document["error"]["code"] == "UNKNOWN_OPERATION"
        assert "manifest's excluded members" in document["error"]["message"]
        assert reason in document["error"]["message"]
        assert document["error"]["hint"] == (
            "Read ksef2.bridge.manifest() for the ids, their arguments and their state."
        )

    unknown = ask("invoices.does_not_exist", {}, envelope())

    assert unknown["ok"] is False
    assert unknown["error"]["code"] == "UNKNOWN_OPERATION"
    assert "excluded" not in unknown["error"]["message"]
    assert unknown["error"]["message"] == (
        "invoices.does_not_exist: no operation carries this id."
    )
    assert recorder.requests == []


def test_collection_cursor_is_declared_and_read_by_the_dispatcher() -> None:
    """A collection's declared cursor is consumed before calling its member."""
    operation = operations()["tokens.list"]
    entries = cast("list[dict[str, Any]]", bridge.manifest()["operations"])
    entry = next(entry for entry in entries if entry["id"] == "tokens.list")

    assert "cursor" in operation.names
    assert all(parameter.name != "cursor" for parameter in operation.parameters)
    assert entry["parameters"][-1] == {
        "name": "cursor",
        "required": False,
        "default": None,
        "schema": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    }


def test_every_published_prefix_has_exactly_one_receiver() -> None:
    """An unrecognised prefix is a dispatcher bug, never an export handle."""
    assert set(_RESOLVERS) == {operation.prefix for operation in operations().values()}
    operation = replace(operations()["peppol.list"], prefix="nope")
    scope = _Scope(operation, read_envelope(operation.id, envelope()))

    with pytest.raises(
        RuntimeError, match="the dispatcher has no receiver for 'nope'"
    ) as raised:
        _receiver(operation, scope)

    assert not isinstance(raised.value, exceptions.KSeFException)


def test_export_result_keeps_package_part_urls(recorder: Recorder) -> None:
    """A multi-part export keeps the URLs needed to restore its handle."""
    urls = [
        "https://storage.mock/part-1?sig=first",
        "https://storage.mock/part-2?sig=second",
    ]
    data = ExportedInvoicesData(
        archive=ARCHIVE,
        package=InvoicePackage(
            invoice_count=2,
            size=len(ARCHIVE),
            parts=[
                PackagePart(
                    ordinal_number=ordinal,
                    part_name=f"package-{ordinal}.zip",
                    method="GET",
                    url=url,
                    part_size=1024 + ordinal,
                    part_hash=f"hash-{ordinal}",
                    encrypted_part_size=2048 + ordinal,
                    encrypted_part_hash=f"encrypted-{ordinal}",
                    expiration_date=datetime(2030, 1, 1, tzinfo=UTC),
                )
                for ordinal, url in enumerate(urls, start=1)
            ],
            is_truncated=False,
        ),
    )

    dumped = dump_state(data)
    package = cast("dict[str, Any]", dumped["package"])
    assert [part["url"] for part in package["parts"]] == urls
    assert ExportedInvoicesData.model_validate(dumped) == data

    document = ask("exported_invoices.to_model", {}, envelope(handle=dumped))

    assert document["ok"] is True, document
    assert [
        part["url"] for part in document["state"]["handle"]["package"]["parts"]
    ] == urls
    assert document["result"] == dumped
    assert document["state"]["handle"] == dumped
    assert recorder.requests == []


def test_close_clients_closes_every_client_even_when_one_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing drains the cache and attempts every client before raising failures."""
    closed: list[str] = []

    class FakeClient:
        def __init__(self, name: str, failure: Exception | None = None) -> None:
            self.name = name
            self.failure = failure

        def close(self) -> None:
            closed.append(self.name)
            if self.failure is not None:
                raise self.failure

    first = ValueError("first failed")
    third = RuntimeError("third failed")
    fake_clients = {
        Environment.TEST: FakeClient("first", first),
        Environment.DEMO: FakeClient("second"),
        Environment.PRODUCTION: FakeClient("third", third),
    }
    monkeypatch.setattr(_runtime, "_CLIENTS", fake_clients)

    with pytest.raises(ExceptionGroup, match="closing bridge clients failed") as raised:
        _runtime.close_clients()

    assert closed == ["first", "second", "third"]
    assert _runtime._CLIENTS == {}
    assert raised.value.exceptions == (first, third)

    fake_clients[Environment.TEST] = FakeClient("single", first)
    with pytest.raises(ValueError) as single:
        _runtime.close_clients()

    assert single.value is first
    assert closed == ["first", "second", "third", "single"]
    assert _runtime._CLIENTS == {}
