from decimal import Decimal
from typing import cast, get_args, get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ksef2._clients.async_authenticated import AsyncAuthenticatedClient
from ksef2._clients.async_online import AsyncOnlineSessionClient
from ksef2._clients.authenticated import AuthenticatedClient
from ksef2._clients.online import OnlineSessionClient
from ksef2._core.exceptions import KSeFArgumentError
from ksef2._domain.models.compression import normalize_compression_type
from ksef2._domain.models.fa3.body.tax import (
    SaleCategory,
    TaxRegime,
    VatClassification,
    VatRate,
    VatTreatment,
    coerce_vat_rate,
    parse_sale_category,
)
from ksef2._domain.models.invoices import normalize_sort_order
from ksef2._domain.models.pagination import InvoiceMetadataParams
from ksef2._domain.models.session import FormSchema
from ksef2.fa3 import InvoiceBuilder
from ksef2._domain.models._enum import coerce_enum
from ksef2._services.renderers import pdf
from ksef2._services.renderers.pdf import InvoicePDFExporter, PDFPageSize


@pytest.mark.parametrize(
    ("client_type", "is_async"),
    [(AuthenticatedClient, False), (AsyncAuthenticatedClient, True)],
)
@pytest.mark.parametrize("form_code", ["fa3", "FA3"])
async def test_online_session_string_acceptance_matches_annotation(
    client_type: type[AuthenticatedClient] | type[AsyncAuthenticatedClient],
    is_async: bool,
    form_code: str,
) -> None:
    annotation = get_type_hints(client_type.online_session)["form_code"]
    input_alias = get_args(annotation)[0]
    input_args = get_args(input_alias.__value__)
    assert FormSchema in input_args
    assert str in input_args

    client = object.__new__(client_type)
    if is_async:
        async_client = cast(AsyncAuthenticatedClient, client)
        with patch.object(
            async_client, "_open_online_session", new_callable=AsyncMock
        ) as opener:
            opener.return_value = MagicMock(spec=AsyncOnlineSessionClient)
            session = async_client.online_session(form_code=form_code)
            await session
            opener.assert_awaited_once_with(form_code=FormSchema.FA3)
    else:
        sync_client = cast(AuthenticatedClient, client)
        with patch.object(
            sync_client,
            "_open_online_session",
            return_value=MagicMock(spec=OnlineSessionClient),
        ) as opener:
            sync_client.online_session(form_code=form_code)
            opener.assert_called_once_with(form_code=FormSchema.FA3)


def test_enum_inputs_are_case_insensitive_and_invalid_values_are_sdk_errors() -> None:
    assert normalize_compression_type("ZIP") == "zip"
    assert normalize_compression_type("TaR_Gz") == "tar_gz"
    assert normalize_sort_order("DESC") == "desc"
    assert InvoiceMetadataParams(sort_order="ASC").sort_order == "asc"
    assert coerce_vat_rate("ZW") is VatRate.EXEMPT
    assert parse_sale_category("RATE_23")[0] is SaleCategory.RATE_23
    assert coerce_enum(TaxRegime, "MARGIN") is TaxRegime.MARGIN
    classification = VatClassification.model_validate(
        {"treatment": "TAXABLE", "rate": Decimal("23")}
    )
    assert classification.treatment is VatTreatment.TAXABLE
    assert coerce_enum(PDFPageSize, "a4") is PDFPageSize.A4

    with pytest.raises(KSeFArgumentError, match="Valid values"):
        normalize_compression_type("rar")

    with (
        patch.object(pdf, "_load_weasyprint", return_value=object()),
        patch.object(pdf, "InvoiceXSLTRenderer", return_value=object()),
    ):
        exporter = InvoicePDFExporter(page_size="a4")
        assert isinstance(exporter, InvoicePDFExporter)
        with pytest.raises(KSeFArgumentError, match="Valid values"):
            InvoicePDFExporter(page_size="A0")


@pytest.mark.parametrize("numeric_rate", [23, 0.23, Decimal("0.23")])
def test_numeric_vat_rates_are_rejected_with_string_marker_hint(
    numeric_rate: object,
) -> None:
    with pytest.raises(KSeFArgumentError, match="VAT marker as a string"):
        coerce_vat_rate(numeric_rate)


def test_public_invoice_builder_accepts_case_insensitive_enum_values() -> None:
    body = InvoiceBuilder().standard()
    body.rows().add_line(
        name="Consulting service",
        quantity=Decimal("1"),
        unit_price_net=Decimal("100"),
        vat_rate="zw",
        sale_category="EXEMPT",
        tax_regime="STANDARD",
    )
