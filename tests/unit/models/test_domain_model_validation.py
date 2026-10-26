from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ValidationError

from ksef2._domain.models.batch import BatchFileInfo, BatchFilePart
from ksef2._domain.models.invoices import InvoicesFilter
from ksef2._domain.models.pagination import InvoiceMetadataParams
from ksef2.models import PersonPermissionsQuery
from ksef2._core.exceptions import KSeFException, KSeFValidationError


def test_public_model_validation_wraps_pydantic_errors() -> None:
    with pytest.raises(
        KSeFValidationError, match="Invalid InvoiceMetadataParams"
    ) as caught:
        InvoiceMetadataParams(page_size=5)

    assert isinstance(caught.value.__cause__, ValidationError)
    assert caught.value.errors()[0]["loc"] == ("page_size",)
    assert isinstance(caught.value, ValueError)


@pytest.mark.parametrize("json_data", ["{", "null", '{"page_size":5}'])
def test_public_model_json_validation_wraps_pydantic_errors(json_data: str) -> None:
    with pytest.raises(KSeFException) as caught:
        InvoiceMetadataParams.model_validate_json(json_data)

    assert isinstance(caught.value, KSeFValidationError)
    assert isinstance(caught.value.__cause__, ValidationError)
    assert caught.value.errors()


def _batch_part(
    *,
    ordinal_number: int = 1,
    file_size: int = 1,
) -> BatchFilePart:
    return BatchFilePart(
        ordinal_number=ordinal_number,
        file_size=file_size,
        file_hash="hash",
    )


def _invoice_filter(**overrides: object) -> InvoicesFilter:
    data: dict[str, object] = {
        "role": "seller",
        "date_type": "issue_date",
        "date_from": "2026-01-01T00:00:00",
        "date_to": "2026-01-02T00:00:00",
    }
    data.update(overrides)
    return InvoicesFilter.model_validate(data)


def test_batch_file_info_rejects_file_larger_than_5gb() -> None:
    with pytest.raises(KSeFValidationError, match="less than or equal to 5000000000"):
        BatchFileInfo(
            file_size=5_000_000_001,
            file_hash="hash",
            parts=[_batch_part()],
        )


def test_invoice_filter_rejects_ranges_longer_than_100_days() -> None:
    with pytest.raises(
        KSeFValidationError,
        match="Invalid InvoicesFilter input:.*must not exceed 100 days",
    ) as caught:
        _invoice_filter(date_to="2026-04-12T00:00:00")

    assert isinstance(caught.value.__cause__, ValidationError)
    assert caught.value.errors()
    assert str(caught.value).count("Invalid InvoicesFilter input") == 1


def test_batch_file_info_rejects_more_than_50_parts() -> None:
    parts = [
        _batch_part(ordinal_number=ordinal_number) for ordinal_number in range(1, 52)
    ]

    with pytest.raises(KSeFValidationError, match="at most 50"):
        BatchFileInfo(file_size=1, file_hash="hash", parts=parts)


def test_batch_file_part_rejects_negative_size() -> None:
    with pytest.raises(KSeFValidationError, match="greater than or equal to 0"):
        _batch_part(file_size=-1)


def test_batch_file_part_rejects_encrypted_size_above_represented_limit() -> None:
    with pytest.raises(KSeFValidationError, match="less than or equal to 100000016"):
        _batch_part(file_size=100_000_017)


def test_batch_file_part_rejects_zero_ordinal_number() -> None:
    with pytest.raises(KSeFValidationError, match="greater than or equal to 1"):
        _batch_part(ordinal_number=0)


def test_invoices_filter_rejects_amount_min_greater_than_amount_max() -> None:
    with pytest.raises(
        KSeFValidationError,
        match="amount_min must be less than or equal to amount_max",
    ):
        _invoice_filter(amount_type="brutto", amount_min=100.0, amount_max=10.0)


def test_invoices_filter_allows_missing_amount_type_without_amount_range() -> None:
    filters = _invoice_filter()

    assert filters.amount_type is None


def test_invoices_filter_requires_amount_type_with_amount_range() -> None:
    with pytest.raises(
        KSeFValidationError,
        match="amount_type must be specified when amount_min or amount_max is used",
    ):
        _invoice_filter(amount_min=10.0)


def test_invoices_filter_rejects_multiple_buyer_identifiers() -> None:
    with pytest.raises(
        KSeFValidationError,
        match="Only one buyer identifier can be specified: buyer_nip, buyer_vat_ue",
    ):
        _invoice_filter(buyer_nip="1234567890", buyer_vat_ue="PL1234567890")


def test_invoices_filter_buyer_constructor_sets_role_and_identifier() -> None:
    filters = InvoicesFilter.for_buyer(
        date_from="2026-01-01T00:00:00",
        date_to="2026-01-02T00:00:00",
        buyer_nip="1234567890",
        invoice_types=["vat"],
    )

    assert filters.role == "buyer"
    assert filters.date_type == "issue_date"
    assert filters.buyer_nip == "1234567890"
    assert filters.invoice_types == ["vat"]


def test_invoices_filter_seller_constructor_sets_role_and_counterparty() -> None:
    filters = InvoicesFilter.for_seller(
        date_from="2026-01-01T00:00:00",
        date_to="2026-01-02T00:00:00",
        seller_nip="1234567890",
        buyer_other_id="client-1",
    )

    assert filters.role == "seller"
    assert filters.seller_nip == "1234567890"
    assert filters.buyer_other_id == "client-1"


def test_invoices_filter_rejects_reversed_parseable_date_strings() -> None:
    with pytest.raises(
        KSeFValidationError,
        match="date_from must be less than or equal to date_to",
    ):
        _invoice_filter(
            date_from="2026-02-01T00:00:00",
            date_to="2026-01-01T00:00:00",
        )


def test_invoices_filter_rejects_reversed_datetime_values() -> None:
    with pytest.raises(
        KSeFValidationError,
        match="date_from must be less than or equal to date_to",
    ):
        _invoice_filter(
            date_from=datetime(2026, 2, 1),
            date_to=datetime(2026, 1, 1),
        )


def test_invoices_filter_normalizes_naive_warsaw_dates_to_utc() -> None:
    filters = _invoice_filter(
        date_from="2026-01-01T00:00:00",
        date_to="2026-01-02T00:00:00",
    )

    assert filters.date_from == datetime(2025, 12, 31, 23, tzinfo=timezone.utc)
    assert filters.date_to == datetime(2026, 1, 1, 23, tzinfo=timezone.utc)


def test_invoices_filter_normalizes_explicit_offsets_to_utc() -> None:
    filters = _invoice_filter(
        date_from="2026-01-01T01:00:00+01:00",
        date_to="2026-01-01T03:00:00+02:00",
    )

    assert filters.date_from == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert filters.date_to == datetime(2026, 1, 1, 1, tzinfo=timezone.utc)


def test_invoices_filter_accepts_equal_instants_with_different_offsets() -> None:
    filters = _invoice_filter(
        date_from="2026-01-01T00:00:00+00:00",
        date_to="2026-01-01T01:00:00+01:00",
    )

    assert filters.date_from == filters.date_to


def test_invoices_filter_rejects_reversed_mixed_timezone_range() -> None:
    with pytest.raises(
        KSeFValidationError,
        match="date_from must be less than or equal to date_to",
    ):
        _invoice_filter(
            date_from="2026-01-02T00:00:00+00:00",
            date_to="2026-01-01T00:00:00",
        )


def test_invoices_filter_rejects_invalid_datetime_string() -> None:
    with pytest.raises(KSeFValidationError, match="Input should be a valid datetime"):
        _invoice_filter(date_from="not-a-datetime")


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("2026-03-29T02:30:00", "does not exist in Europe/Warsaw"),
        ("2026-10-25T02:30:00", "is ambiguous in Europe/Warsaw"),
    ],
)
def test_invoices_filter_requires_offset_for_dst_transition_times(
    value: str,
    message: str,
) -> None:
    with pytest.raises(KSeFValidationError, match=message):
        _invoice_filter(date_from=value)


def test_invoices_filter_accepts_explicit_offset_during_dst_overlap() -> None:
    filters = _invoice_filter(
        date_from="2026-10-25T02:30:00+02:00",
        date_to="2026-10-25T02:30:00+01:00",
    )

    assert filters.date_from == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    assert filters.date_to == datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)


def _public_pydantic_models() -> list[type[BaseModel]]:
    import inspect
    import ksef2.models as models

    return sorted(
        {
            value
            for name in models.__all__
            if inspect.isclass(value := getattr(models, name))
            and issubclass(value, BaseModel)
        },
        key=lambda model: model.__name__,
    )


@pytest.mark.parametrize(
    "model", _public_pydantic_models(), ids=lambda model: model.__name__
)
@pytest.mark.parametrize("entry", ["constructor", "object", "json", "strings"])
def test_every_public_model_wraps_invalid_input(
    model: type[BaseModel],
    entry: str,
) -> None:
    if entry == "constructor":
        # None is invalid for each declared field; models with no fields have no
        # invalid constructor input because they deliberately ignore extras.
        if not model.model_fields:
            return
        invalid = {name: None for name in model.model_fields}
        try:
            model(**invalid)
        except KSeFValidationError as error:
            assert isinstance(error.__cause__, ValidationError)
        else:
            # Fully optional query models accept None. Malformed JSON below
            # exercises their validation boundary without inventing constraints.
            assert all(not field.is_required() for field in model.model_fields.values())
    else:
        with pytest.raises(KSeFValidationError) as caught:
            if entry == "object":
                model.model_validate(None)
            elif entry == "strings":
                model.model_validate_strings(None)
            else:
                model.model_validate_json("{")
        assert isinstance(caught.value.__cause__, ValidationError)


@pytest.mark.parametrize(
    "value", ["garbage", "", "5261040828-20260101-abcdefABCDEF-AA"]
)
def test_invoice_filter_validates_ksef_number_at_construction(value: str) -> None:
    with pytest.raises(KSeFValidationError) as caught:
        _invoice_filter(ksef_number=value)
    assert caught.value.errors()[0]["loc"] == ("ksef_number",)


@pytest.mark.parametrize(
    "value",
    [
        "5261040828-20260101-ABCDEF123456-AA",
        "5261040828-20260101-ABCDEF-123456-AA",
    ],
)
def test_invoice_filter_accepts_both_spec_ksef_number_formats(value: str) -> None:
    assert _invoice_filter(ksef_number=value).ksef_number == value


def test_missing_person_query_type_uses_sdk_exception_hierarchy() -> None:
    with pytest.raises(KSeFException, match="query_type") as caught:
        PersonPermissionsQuery()  # pyright: ignore[reportCallIssue]
    assert isinstance(caught.value, KSeFValidationError)
    assert isinstance(caught.value.__cause__, ValidationError)
    assert caught.value.errors()[0]["loc"] == ("query_type",)
