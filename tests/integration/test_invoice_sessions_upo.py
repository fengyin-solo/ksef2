"""Download UPO after a restart from stored references only (#172).

The sender process keeps plain strings -- session reference, invoice reference,
KSeF number and session UPO page reference -- and exits. A new process with a new
``Client`` and a new authentication downloads each UPO through
``auth.invoice_sessions.download_upo`` with no session handle and no
``OnlineSessionResumeState``.

Run with:
    uv run pytest tests/integration/test_invoice_sessions_upo.py -v -m integration
"""

import pytest

from ksef2 import Client, Environment, FormSchema
from ksef2._core.exceptions import (
    ExceptionCode,
    KSeFInvoiceRejectedError,
    KSeFNotReadyError,
    KSeFValidationError,
)
from ksef2.xades import generate_test_certificate
from scripts.examples._common import example_invoice_xml
from tests.integration.conftest import KSeFCredentials
from tests.integration.invoice_payload import invoice_seller_nip


@pytest.mark.integration
def test_download_upo_after_restart_from_stored_references(
    ksef_credentials: KSeFCredentials,
) -> None:
    """Every selector returns UPO XML, and a UPO KSeF does not have is not ready."""
    seller_nip = invoice_seller_nip(ksef_credentials.subject_nip)
    invoice_xml = example_invoice_xml(seller_nip=seller_nip)

    # Sender process: everything it keeps is a string.
    with Client(environment=Environment.TEST) as client:
        cert, private_key = generate_test_certificate(seller_nip)
        auth = client.authentication.with_xades(
            nip=seller_nip, cert=cert, private_key=private_key
        )
        with auth.online_session(form_code=FormSchema.FA3) as session:
            session_reference_number = session.reference_number
            accepted = session.send_invoice(invoice_xml)
            # Asked straight away, KSeF has no UPO yet. Fast processing may
            # already have one, but it is never a bare HTTP error.
            try:
                early_upo = auth.invoice_sessions.download_upo(
                    session_reference_number,
                    invoice_reference_number=accepted.reference_number,
                )
            except KSeFNotReadyError as error:
                assert error.ksef_code == ExceptionCode.UPO_NOT_FOUND
            else:
                assert early_upo.lstrip().startswith(b"<")
            ksef_number = accepted.wait(timeout=90.0).ksef_number
            duplicate = session.send_invoice(invoice_xml)
            with pytest.raises(KSeFInvoiceRejectedError):
                _ = duplicate.wait(timeout=90.0)

        status = session.wait(timeout=90.0)
        assert status.upo is not None
        assert status.upo.pages
        invoice_reference_number = accepted.reference_number
        rejected_reference_number = duplicate.reference_number
        upo_reference_number = status.upo.pages[0].reference_number

    assert ksef_number

    # Restarted process: a new client and a new authentication, no session handle.
    with Client(environment=Environment.TEST) as client:
        cert, private_key = generate_test_certificate(seller_nip)
        auth = client.authentication.with_xades(
            nip=seller_nip, cert=cert, private_key=private_key
        )

        by_reference = auth.invoice_sessions.download_upo(
            session_reference_number,
            invoice_reference_number=invoice_reference_number,
        )
        by_ksef_number = auth.invoice_sessions.download_upo(
            session_reference_number, ksef_number=ksef_number
        )
        session_upo_page = auth.invoice_sessions.download_upo(
            session_reference_number, upo_reference_number=upo_reference_number
        )

        for upo_xml in (by_reference, by_ksef_number, session_upo_page):
            assert isinstance(upo_xml, bytes)
            assert upo_xml.lstrip().startswith(b"<")
        assert ksef_number.encode() in by_reference
        assert ksef_number.encode() in by_ksef_number
        assert ksef_number.encode() in session_upo_page

        # KSeF never issues a UPO for the rejected duplicate: 21178, as when too early.
        with pytest.raises(KSeFNotReadyError) as exc_info:
            _ = auth.invoice_sessions.download_upo(
                session_reference_number,
                invoice_reference_number=rejected_reference_number,
            )
        assert exc_info.value.ksef_code == ExceptionCode.UPO_NOT_FOUND
        assert exc_info.value.trace_id

        with pytest.raises(KSeFValidationError):
            _ = auth.invoice_sessions.download_upo(session_reference_number)
