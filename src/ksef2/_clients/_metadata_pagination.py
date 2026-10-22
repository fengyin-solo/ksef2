"""Shared helpers for KSeF metadata pagination."""

from datetime import date, datetime
from typing import Literal, assert_never

from ksef2._core.exceptions import KSeFMetadataPaginationError
from ksef2._domain.models.invoices import (
    InvoiceMetadata,
    InvoicesFilter,
    QueryInvoicesMetadataResponse,
)
from ksef2._domain.models.pagination import InvoiceMetadataParams

type MetadataBoundary = date | datetime
type MetadataDateType = Literal["issue_date", "invoicing_date", "permanent_storage"]
type MetadataPageRequest = tuple[
    InvoicesFilter, InvoiceMetadataParams, MetadataBoundary | None
]
type MetadataStall = Literal["no_invoices", "no_advance"]
"""Why a truncated page cannot be continued: it held no invoices to take a boundary from, or its boundary equals the previous one."""


def metadata_stall(
    *,
    filters: InvoicesFilter,
    response: QueryInvoicesMetadataResponse,
    previous_truncation_boundary: MetadataBoundary | None,
) -> MetadataStall | None:
    """Tell whether a response ends the search because it cannot advance safely.

    Args:
        filters: Filters the response answered.
        response: Response to inspect.
        previous_truncation_boundary: Boundary the previous page truncated at.

    Returns:
        The reason the search cannot continue, or ``None`` when it can.
    """
    if not (response.has_more and response.is_truncated):
        return None
    if not response.invoices:
        return "no_invoices"
    boundary = _metadata_boundary(filters.date_type, response.invoices[-1])
    return "no_advance" if boundary == previous_truncation_boundary else None


def metadata_stall_error(
    reason: MetadataStall,
    *,
    filters: InvoicesFilter,
    params: InvoiceMetadataParams,
    boundary: MetadataBoundary | None,
) -> KSeFMetadataPaginationError:
    """Build the error for a search that cannot advance.

    Args:
        reason: Why the search stalled.
        filters: Filters of the request that stalled.
        params: Parameters of the request that stalled.
        boundary: Boundary the stalled page truncated at; unused when the page held no invoices.

    Returns:
        The error to raise.
    """
    if reason == "no_invoices":
        return KSeFMetadataPaginationError(
            "KSeF returned a truncated metadata page without invoices",
            date_type=filters.date_type,
        )
    return KSeFMetadataPaginationError(
        "KSeF metadata pagination did not advance after truncation",
        date_type=filters.date_type,
        sort_order=params.sort_order,
        boundary=boundary,
    )


def next_metadata_page_request(
    *,
    filters: InvoicesFilter,
    params: InvoiceMetadataParams,
    response: QueryInvoicesMetadataResponse,
    previous_truncation_boundary: MetadataBoundary | None,
) -> MetadataPageRequest | None:
    """Return the next metadata request needed to continue pagination.

    Raises:
        KSeFMetadataPaginationError: If KSeF reports a truncated page that cannot
            advance safely.
    """
    if not response.has_more:
        return None

    if response.is_truncated:
        stall = metadata_stall(
            filters=filters,
            response=response,
            previous_truncation_boundary=previous_truncation_boundary,
        )
        if stall is not None:
            raise metadata_stall_error(
                stall,
                filters=filters,
                params=params,
                boundary=previous_truncation_boundary,
            )
        boundary = _last_metadata_boundary(filters=filters, response=response)
        return (
            _narrow_filters_to_boundary(
                filters=filters,
                params=params,
                boundary=boundary,
            ),
            params.with_page_offset(0),
            boundary,
        )

    return filters, params.next_page(), previous_truncation_boundary


def _last_metadata_boundary(
    *,
    filters: InvoicesFilter,
    response: QueryInvoicesMetadataResponse,
) -> MetadataBoundary:
    return _metadata_boundary(filters.date_type, response.invoices[-1])


def _metadata_boundary(
    date_type: MetadataDateType,
    invoice: InvoiceMetadata,
) -> MetadataBoundary:
    match date_type:
        case "issue_date":
            return invoice.issue_date
        case "invoicing_date":
            return invoice.invoicing_date
        case "permanent_storage":
            return invoice.permanent_storage_date
        case _ as unreachable:
            assert_never(unreachable)


def _narrow_filters_to_boundary(
    *,
    filters: InvoicesFilter,
    params: InvoiceMetadataParams,
    boundary: MetadataBoundary,
) -> InvoicesFilter:
    filter_data = filters.model_dump()
    if params.sort_order == "asc":
        filter_data["date_from"] = boundary
    elif params.sort_order == "desc":
        filter_data["date_to"] = boundary
    else:
        raise KSeFMetadataPaginationError(
            "Unsupported metadata sort order",
            sort_order=params.sort_order,
        )

    return InvoicesFilter.model_validate(filter_data)
