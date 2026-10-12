"""Unit tests for the FA(3) payment sub-builder."""

from datetime import date
from decimal import Decimal

import pytest

from ksef2._services.builders.fa3.sub.payment import PaymentBuilder


def started_payment() -> PaymentBuilder[None]:
    """Return a detached payment builder."""
    return PaymentBuilder(None, lambda payment: None)


def test_build_rejects_mutually_exclusive_statuses_and_forms() -> None:
    """Reject the combinations the FA(3) XSD keeps in separate choices."""
    with pytest.raises(ValueError, match="paid and partial_payment_status"):
        (
            started_payment()
            .already_paid(date(2026, 4, 15))
            .partial_payment_status("partial")
            .add_partial_payment(
                amount=Decimal("1.00"),
                payment_date=date(2026, 4, 15),
            )
            .build()
        )

    with pytest.raises(ValueError, match="payment_form and other_payment_form"):
        (started_payment().via("cash").other_form().description("custom").build())
