"""Unit tests for the FA(3) payment sub-builder reached from the public builder."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from ksef2.fa3 import FA3InvoiceBuilder


def started_payment_builder() -> Any:
    """Open the payment sub-builder on an invoice whose header, seller and buyer are set."""
    builder = FA3InvoiceBuilder()
    _ = builder.header(system_info="billing-service")
    _ = builder.seller(
        name="ACME S.A.",
        tax_id="1234567890",
        country_code="PL",
        address_line_1="ul. Przykladowa 123",
    )
    _ = builder.buyer(
        name="XYZ Sp. z o.o.",
        country_code="PL",
        address_line_1="ul. Inna 1",
    )
    return builder.standard().payment()


def test_partial_payment_marker_and_entries_are_required_together() -> None:
    entries_without_marker = started_payment_builder().add_partial_payment(
        amount=Decimal("10.00"),
        payment_date=date(2026, 4, 10),
    )
    with pytest.raises(
        ValueError,
        match="partial_payment_status is required when partial payments are added",
    ):
        _ = entries_without_marker.done()

    marker_without_entries = started_payment_builder().partial_payment_status("partial")
    with pytest.raises(
        ValueError,
        match="At least one partial payment is required when partial_payment_status is set",
    ):
        _ = marker_without_entries.done()

    payment = (
        started_payment_builder()
        .partial_payment_status("partial")
        .add_partial_payment(amount=Decimal("10.00"), payment_date=date(2026, 4, 10))
    )
    invoice_payment = payment.build()

    assert invoice_payment.partial_payment_status == "partial"
    assert invoice_payment.partial_payments[0].amount == Decimal("10.00")


def test_build_rejects_mutually_exclusive_statuses_and_forms() -> None:
    with pytest.raises(ValueError, match="paid and partial_payment_status"):
        (
            started_payment_builder()
            .already_paid(date(2026, 4, 15))
            .partial_payment_status("partial")
            .add_partial_payment(
                amount=Decimal("1.00"),
                payment_date=date(2026, 4, 15),
            )
            .build()
        )

    with pytest.raises(ValueError, match="payment_form and other_payment_form"):
        (
            started_payment_builder()
            .via("cash")
            .other_form()
            .description("custom")
            .build()
        )
