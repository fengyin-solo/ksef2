"""Caller-facing diagnostics for content inputs and async lifecycle misuse."""

import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from polyfactory import BaseFactory

from ksef2 import AsyncClient, Environment, KSeFArgumentError
from ksef2.clients import AsyncBatchSessionClient, AsyncOnlineSessionClient
from ksef2._core.async_http import AsyncHttpTransport
from ksef2._domain.models.batch import BatchSessionResumeState
from ksef2._domain.models.session import OnlineSessionResumeState
from ksef2._services.batch_preparation import load_batch_items
from ksef2.fa3 import parse_invoice_xml
from ksef2.xades import (
    load_certificate_and_key_from_p12,
    load_certificate_from_pem,
    load_private_key_from_pem,
)
from tests.unit.fakes.transport import AsyncFakeTransport


@pytest.mark.parametrize(
    "loader",
    [
        load_certificate_from_pem,
        load_private_key_from_pem,
        load_certificate_and_key_from_p12,
    ],
)
@pytest.mark.parametrize(
    "filename",
    [
        "company.pem",
        "company.crt",
        "company.cer",
        "company.key",
        "company.p12",
        "company.pfx",
        "missing/company",
        r"missing\company",
    ],
)
def test_missing_certificate_filename_has_path_hint(loader, filename: str) -> None:
    with pytest.raises(KSeFArgumentError, match="looks like a file path") as error:
        loader(filename)
    assert "Path(" in str(error.value)
    assert "content" in str(error.value)


@pytest.mark.parametrize(
    "source",
    [
        "sensitive/key.pem\nsecret",
        "-----BEGIN PRIVATE KEY-----/secret.pem",
        "secret/" * 100,
    ],
)
def test_malformed_certificate_content_is_not_echoed(source: str) -> None:
    with pytest.raises(ValueError) as error:
        load_certificate_from_pem(source)
    assert source not in str(error.value)


def test_explicit_missing_path_keeps_filesystem_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_certificate_from_pem(tmp_path / "missing.pem")


@pytest.mark.parametrize("filename", ["missing.xml", "missing/invoice"])
def test_invoice_content_inputs_have_path_hint(filename: str) -> None:
    with pytest.raises(KSeFArgumentError, match="looks like a file path"):
        load_batch_items([filename])
    with pytest.raises(KSeFArgumentError, match="looks like a file path"):
        parse_invoice_xml(filename)


def test_async_close_guards_leave_sessions_and_transport_open(
    domain_online_session_state: BaseFactory[OnlineSessionResumeState],
    domain_batch_session_state: BaseFactory[BatchSessionResumeState],
) -> None:
    transport = AsyncFakeTransport()
    online = AsyncOnlineSessionClient(transport, domain_online_session_state.build())
    batch = AsyncBatchSessionClient(transport, domain_batch_session_state.build())
    root = AsyncClient(Environment.TEST)
    http = AsyncHttpTransport(httpx.AsyncClient(), headers={})
    for target in (root, online, batch, http):
        aclose = AsyncMock()
        original_aclose = target.aclose
        target.aclose = aclose
        assert not inspect.iscoroutinefunction(target.close)
        with pytest.raises(KSeFArgumentError, match=r"await .*\.aclose\(\)"):
            target.close()
        aclose.assert_not_called()
        target.aclose = original_aclose
    assert transport.calls == []
    assert online._closed is False
    assert batch._closed is False
    assert root._lifecycle_state.closed is False
    asyncio.run(root.aclose())
    asyncio.run(http.aclose())


def test_online_filename_hint_precedes_encryption_and_upload(
    domain_online_session_state: BaseFactory[OnlineSessionResumeState],
) -> None:
    transport = AsyncFakeTransport()
    session = AsyncOnlineSessionClient(transport, domain_online_session_state.build())
    with pytest.raises(KSeFArgumentError, match="looks like a file path"):
        asyncio.run(session.send_invoice("missing.xml"))
    assert transport.calls == []


def test_renderer_filename_hints(monkeypatch: pytest.MonkeyPatch) -> None:
    from ksef2.renderers import InvoicePDFExporter, InvoiceXSLTRenderer

    monkeypatch.setattr(
        "ksef2._services.renderers.pdf._load_weasyprint", lambda: object()
    )
    html = InvoiceXSLTRenderer()
    pdf = InvoicePDFExporter(verification_environment=Environment.TEST)
    with pytest.raises(KSeFArgumentError, match="looks like a file path"):
        html.render_from_string("missing.xml")
    with pytest.raises(KSeFArgumentError, match="looks like a file path"):
        pdf.export_from_string("missing.xml")
