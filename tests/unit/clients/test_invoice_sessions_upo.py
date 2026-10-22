"""Authenticated UPO downloads from stored references, without a session handle."""

import httpx
import pytest
from polyfactory import BaseFactory

from ksef2._clients.async_authenticated import AsyncAuthenticatedClient
from ksef2._clients.authenticated import AuthenticatedClient
from ksef2._core.exceptions import (
    KSeFApiError,
    KSeFAuthError,
    KSeFNotReadyError,
    KSeFValidationError,
)
from ksef2._core.middlewares.async_exceptions import AsyncKSeFExceptionMiddleware
from ksef2._core.middlewares.exceptions import KSeFExceptionMiddleware
from ksef2._core.stores import CertificateStore
from ksef2._domain.models.auth import AuthTokens
from tests.unit.fakes.transport import AsyncFakeTransport, FakeTransport
from tests.unit.flavors import Flavor


SESSION_REF = "20260625-SO-session"
INVOICE_REF = "20260625-EE-invoice"
KSEF_NUMBER = "1234567890-20260625-invoice"
UPO_REF = "upo-page-reference"


@pytest.fixture
def auth(
    flavor: Flavor,
    domain_auth_tokens: BaseFactory[AuthTokens],
) -> AuthenticatedClient | AsyncAuthenticatedClient:
    tokens = domain_auth_tokens.build()
    if flavor.is_async:
        assert isinstance(flavor.transport, AsyncFakeTransport)
        return AsyncAuthenticatedClient(
            AsyncKSeFExceptionMiddleware(flavor.transport), tokens, CertificateStore()
        )
    assert isinstance(flavor.transport, FakeTransport)
    return AuthenticatedClient(
        KSeFExceptionMiddleware(flavor.transport), tokens, CertificateStore()
    )


@pytest.fixture(
    params=["invoice_reference_number", "ksef_number", "upo_reference_number"]
)
def selector(request: pytest.FixtureRequest) -> dict[str, str]:
    values = {
        "invoice_reference_number": INVOICE_REF,
        "ksef_number": KSEF_NUMBER,
        "upo_reference_number": UPO_REF,
    }
    return {request.param: values[request.param]}


def test_download_after_restart_makes_one_authenticated_request(
    auth: AuthenticatedClient | AsyncAuthenticatedClient,
    flavor: Flavor,
    selector: dict[str, str],
) -> None:
    flavor.transport.enqueue(content=b"<upo>signed XML</upo>")

    result = flavor.run(auth.invoice_sessions.download_upo(SESSION_REF, **selector))

    assert result == b"<upo>signed XML</upo>"
    assert len(flavor.transport.calls) == 1
    call = flavor.transport.calls[0]
    expected_paths = {
        "invoice_reference_number": f"/sessions/{SESSION_REF}/invoices/{INVOICE_REF}/upo",
        "ksef_number": f"/sessions/{SESSION_REF}/invoices/ksef/{KSEF_NUMBER}/upo",
        "upo_reference_number": f"/sessions/{SESSION_REF}/upo/{UPO_REF}",
    }
    assert call.method == "GET"
    assert call.path == expected_paths[next(iter(selector))]
    assert call.headers == {"Authorization": "Bearer fake-access-token"}


@pytest.mark.parametrize(
    "selectors",
    [
        {},
        {"invoice_reference_number": INVOICE_REF, "ksef_number": KSEF_NUMBER},
        {"invoice_reference_number": INVOICE_REF, "upo_reference_number": UPO_REF},
        {"ksef_number": KSEF_NUMBER, "upo_reference_number": UPO_REF},
        {
            "invoice_reference_number": INVOICE_REF,
            "ksef_number": KSEF_NUMBER,
            "upo_reference_number": UPO_REF,
        },
    ],
)
def test_requires_exactly_one_selector_before_requesting(
    auth: AuthenticatedClient | AsyncAuthenticatedClient,
    flavor: Flavor,
    selectors: dict[str, str],
) -> None:
    with pytest.raises(KSeFValidationError, match="Pass exactly one"):
        _ = flavor.run(auth.invoice_sessions.download_upo(SESSION_REF, **selectors))
    assert flavor.transport.calls == []


@pytest.mark.parametrize("code", [21165, 21178])
@pytest.mark.parametrize("error_format", ["legacy", "problem-details"])
def test_early_download_preserves_not_ready_error(
    auth: AuthenticatedClient | AsyncAuthenticatedClient,
    flavor: Flavor,
    selector: dict[str, str],
    code: int,
    error_format: str,
) -> None:
    if error_format == "legacy":
        flavor.transport.enqueue(
            {
                "exception": {
                    "exceptionDetailList": [
                        {"exceptionCode": code, "exceptionDescription": "Not ready."}
                    ]
                }
            },
            status_code=400,
        )
    else:
        flavor.transport.enqueue(
            {
                "title": "Bad Request",
                "status": 400,
                "detail": "Not ready.",
                "instance": "https://ksef.example/errors/upo",
                "errors": [{"code": code, "description": "Not ready."}],
                "timestamp": "2026-06-25T12:00:00Z",
                "traceId": "trace-upo",
            },
            status_code=400,
            headers={"content-type": "application/problem+json"},
        )

    with pytest.raises(KSeFNotReadyError) as exc_info:
        _ = flavor.run(auth.invoice_sessions.download_upo(SESSION_REF, **selector))

    assert exc_info.value.ksef_code == code
    assert exc_info.value.status_code == 400
    assert exc_info.value.hint is not None
    assert len(flavor.transport.calls) == 1


def test_plain_404_is_not_not_ready(
    auth: AuthenticatedClient | AsyncAuthenticatedClient,
    flavor: Flavor,
    selector: dict[str, str],
) -> None:
    flavor.transport.enqueue(status_code=404, content=b"")
    with pytest.raises(KSeFApiError) as exc_info:
        _ = flavor.run(auth.invoice_sessions.download_upo(SESSION_REF, **selector))
    assert not isinstance(exc_info.value, KSeFNotReadyError)
    assert exc_info.value.status_code == 404
    assert len(flavor.transport.calls) == 1


def test_authorization_failure_is_preserved(
    auth: AuthenticatedClient | AsyncAuthenticatedClient,
    flavor: Flavor,
    selector: dict[str, str],
) -> None:
    flavor.transport.enqueue(status_code=403, content=b"")
    with pytest.raises(KSeFAuthError):
        _ = flavor.run(auth.invoice_sessions.download_upo(SESSION_REF, **selector))
    assert len(flavor.transport.calls) == 1


def test_transport_failure_is_preserved(
    auth: AuthenticatedClient | AsyncAuthenticatedClient,
    flavor: Flavor,
    selector: dict[str, str],
) -> None:
    error = httpx.ConnectError("Connection failed.")
    flavor.transport.enqueue_error(error)
    with pytest.raises(httpx.ConnectError) as exc_info:
        _ = flavor.run(auth.invoice_sessions.download_upo(SESSION_REF, **selector))
    assert exc_info.value is error
    assert len(flavor.transport.calls) == 1
