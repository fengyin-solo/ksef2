import pytest

from ksef2._services.builders.fa3.root import StandardInvoiceBuilder


def test_buyer_without_address_line_1_is_rejected_instead_of_dropping_address() -> None:
    builder = StandardInvoiceBuilder()

    with pytest.raises(ValueError, match="address_line_1 is required"):
        builder.buyer(
            name="Buyer",
            country_code="PL",
            address_line_1=None,
            address_line_2="00-001 Warszawa",
            tax_id="123",
        )
