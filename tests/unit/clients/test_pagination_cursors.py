"""Resumable cursors: every collection continues from a stored cursor with one request."""

import base64
import json
from datetime import date, datetime
from typing import Any

import pytest
from polyfactory.factories.pydantic_factory import ModelFactory

from ksef2._clients._pagination_cursor import InvoiceSearchCursor, OffsetCursor
from ksef2._core.exceptions import KSeFArgumentError
from ksef2._domain.models.invoices import InvoicesFilter
from ksef2._domain.models.pagination import (
    CollectiveIdentifierParams,
    InvoiceMetadataParams,
    ListSessionsQuery,
    OffsetPaginationParams,
    Page,
    PermissionsQueryParams,
    TokenListParams,
)
from tests.unit.clients.test_paging import (
    COLLECTIONS,
    CURSOR,
    OFFSET,
    Collection,
    _client,
    _page,
)
from tests.unit.factories.auth import DomainAuthTokensFactory
from tests.unit.factories.permissions import (
    DomainAuthorizationPermissionsQueryFactory,
    DomainEntityPermissionsQueryFactory,
    DomainEuEntityPermissionsQueryFactory,
    DomainPersonalPermissionsQueryFactory,
    DomainPersonPermissionsQueryFactory,
    DomainSubordinateEntityRolesQueryFactory,
    DomainSubunitPermissionsQueryFactory,
)
from tests.unit.flavors import Flavor

COLLECTIONS_BY_ID: dict[str, Collection] = {c.id: c for c in COLLECTIONS}
PERMISSION_COLLECTION_IDS = sorted(
    collection_id
    for collection_id in COLLECTIONS_BY_ID
    if collection_id.startswith("permissions.")
)
OFFSET_COLLECTIONS = [c for c in COLLECTIONS if c.paging == OFFSET]
CURSOR_COLLECTIONS = [c for c in COLLECTIONS if c.paging == CURSOR]

# The JSON keys a cursor may carry, and nothing else.
CURSOR_STATE_FIELDS = {
    "v",
    "operation",
    "continuation_token",
    "page_offset",
    "filters",
    "params",
    "previous_truncation_boundary",
}

# Non-default page size for every collection, plus non-default filters or identifiers
# where the method takes them, so a resumed request proves the SDK kept the caller's
# own query rather than a default one.
_COLLECTION_KWARGS: dict[str, dict[str, Any]] = {
    "tokens.list": {
        "params": TokenListParams(
            page_size=15, description="nightly", author_identifier="1234567890"
        )
    },
    "sessions.list": {"page_size": 15},
    "invoice_sessions.list": {
        "params": ListSessionsQuery(
            session_type="online", reference_number="ref-7", page_size=15
        )
    },
    "collective_identifiers.list": {"params": CollectiveIdentifierParams(page_size=15)},
    "collective_identifiers.list_for_invoice": {
        "params": CollectiveIdentifierParams(page_size=15)
    },
    "collective_identifiers.list_invoices": {
        "params": CollectiveIdentifierParams(page_size=15)
    },
    "certificates.list": {"params": OffsetPaginationParams(page_size=15)},
    "peppol.list": {"params": OffsetPaginationParams(page_size=15)},
}

_PERMISSION_QUERY_FACTORIES: dict[str, type[ModelFactory[Any]]] = {
    "permissions.list_authorizations": DomainAuthorizationPermissionsQueryFactory,
    "permissions.list_entities": DomainEntityPermissionsQueryFactory,
    "permissions.list_eu_entities": DomainEuEntityPermissionsQueryFactory,
    "permissions.list_personal": DomainPersonalPermissionsQueryFactory,
    "permissions.list_persons": DomainPersonPermissionsQueryFactory,
    "permissions.list_subordinate_entities": DomainSubordinateEntityRolesQueryFactory,
    "permissions.list_subunits": DomainSubunitPermissionsQueryFactory,
}


def _kwargs(collection: Collection) -> dict[str, Any]:
    """Return the non-default keyword arguments for calling one collection."""
    if collection.id in _PERMISSION_QUERY_FACTORIES:
        return {"params": PermissionsQueryParams(page_size=15, page_offset=2)}
    return dict(_COLLECTION_KWARGS.get(collection.id, {}))


def _call(collection: Collection, client: Any, **overrides: Any) -> Any:
    """Call a collection method the way a caller would, with its own arguments."""
    kwargs = _kwargs(collection)
    kwargs.update(overrides)
    return getattr(client, collection.method)(*collection.args(), **kwargs)


def _page_at(
    flavor: Flavor,
    collection: Collection,
    client: Any,
    cursor: str | None,
    **overrides: Any,
) -> Page[Any]:
    """Fetch one page in this flavour; the async pager returns an awaitable."""
    pager = _call(collection, client, **overrides)
    return flavor.run(pager.page(cursor))


def _shape(items: list[Any]) -> list[str]:
    """Render items so pages parsed by two different clients can be compared."""
    return [item.model_dump_json() for item in items]


def _carry(cursor: str) -> str:
    """Send a cursor through JSON the way a language binding would, and read it back."""
    return str(json.loads(json.dumps({"cursor": cursor}))["cursor"])


def _paging_detail(collection: Collection, call: Any) -> str:
    """Describe the paging state one recorded request carried."""
    if collection.paging == CURSOR:
        return str((call.headers or {}).get("x-continuation-token"))
    params = call.params
    return "" if params is None else str(params.get("pageOffset"))


def _cursor_payload(cursor: str) -> str:
    """Return the JSON text stored inside a cursor."""
    return base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")


def _tampered_cursor(state: dict[str, Any]) -> str:
    """Build a cursor string from raw JSON state, as a caller tampering with one would."""
    return base64.urlsafe_b64encode(json.dumps(state).encode("utf-8")).decode("ascii")


class TestCollectionCursors:
    @pytest.mark.parametrize("collection", COLLECTIONS, ids=lambda c: c.id)
    def test_every_collection_resumes_with_one_request(
        self, collection: Collection, flavor: Flavor
    ) -> None:
        pages = [_page(collection, more=more) for more in (True, True, False)]
        for page in pages:
            assert page[collection.items_field], "factory must build at least one item"

        # Walking the collection gives the pages a resumed walk has to reproduce.
        walking = _client(collection, flavor)
        for page in pages:
            flavor.transport.enqueue(page)
        traversal = flavor.collect(_call(collection, walking).pages())
        assert len(flavor.transport.calls) == 3
        initial_paging = _paging_detail(collection, flavor.transport.calls[0])
        start = 0 if collection.paging == CURSOR else int(initial_paging or "0")

        cursor: str | None = None
        for index, walked_items in enumerate(traversal):
            flavor.transport.clear()
            client = _client(collection, flavor)
            flavor.transport.enqueue(pages[index])

            page = _page_at(
                flavor,
                collection,
                client,
                None if cursor is None else _carry(cursor),
            )

            assert isinstance(page, Page)
            assert _shape(page.items) == _shape(walked_items)
            assert len(flavor.transport.calls) == 1
            if collection.paging == CURSOR:
                expected_paging = "None" if index == 0 else "next-page"
            else:
                expected_paging = str(start + index)
            assert (
                _paging_detail(collection, flavor.transport.calls[0]) == expected_paging
            )
            if index + 1 < len(traversal):
                assert page.next_cursor is not None
                cursor = page.next_cursor
            else:
                assert page.next_cursor is None

    def test_page_rejects_a_cursor_from_another_collection(
        self, flavor: Flavor
    ) -> None:
        """Two continuation-token collections must not accept each other's cursors."""
        collection = COLLECTIONS_BY_ID["tokens.list"]
        other = COLLECTIONS_BY_ID["sessions.list"]
        flavor.transport.enqueue(_page(collection, more=True))

        first = _page_at(flavor, collection, _client(collection, flavor), None)

        assert first.next_cursor is not None
        with pytest.raises(KSeFArgumentError, match="not for sessions.list"):
            _page_at(flavor, other, _client(other, flavor), first.next_cursor)
        assert len(flavor.transport.calls) == 1

    def test_page_rejects_a_cursor_of_another_paging_style(
        self, flavor: Flavor
    ) -> None:
        """An offset collection rejects a continuation cursor before sending anything."""
        collection = COLLECTIONS_BY_ID["tokens.list"]
        other = COLLECTIONS_BY_ID["peppol.list"]
        flavor.transport.enqueue(_page(collection, more=True))

        first = _page_at(flavor, collection, _client(collection, flavor), None)

        assert first.next_cursor is not None
        with pytest.raises(KSeFArgumentError, match="Invalid pagination cursor"):
            _page_at(flavor, other, _client(other, flavor), first.next_cursor)
        assert len(flavor.transport.calls) == 1

    @pytest.mark.parametrize("method", PERMISSION_COLLECTION_IDS)
    def test_cursor_wrong_operation_is_rejected(
        self, method: str, flavor: Flavor
    ) -> None:
        """The permissions queries share one pager builder, so their cursors must not mix."""
        collection = COLLECTIONS_BY_ID[method]
        flavor.transport.enqueue(_page(collection, more=True))

        first = _page_at(flavor, collection, _client(collection, flavor), None)

        assert first.next_cursor is not None
        other_id = next(other for other in PERMISSION_COLLECTION_IDS if other != method)
        other = COLLECTIONS_BY_ID[other_id]
        with pytest.raises(KSeFArgumentError, match=f"not for {other_id}"):
            _page_at(flavor, other, _client(other, flavor), first.next_cursor)
        assert len(flavor.transport.calls) == 1

    @pytest.mark.parametrize("collection", OFFSET_COLLECTIONS, ids=lambda c: c.id)
    def test_resume_uses_the_cursor_offset_not_the_new_pagers_offset(
        self, collection: Collection, flavor: Flavor
    ) -> None:
        flavor.transport.enqueue(_page(collection, more=True))
        first = _page_at(
            flavor,
            collection,
            _client(collection, flavor),
            None,
            params=OffsetPaginationParams(page_size=15, page_offset=2),
        )

        assert _paging_detail(collection, flavor.transport.calls[0]) == "2"
        assert first.next_cursor is not None

        flavor.transport.enqueue(_page(collection, more=False))
        resumed = _page_at(
            flavor,
            collection,
            _client(collection, flavor),
            first.next_cursor,
            params=OffsetPaginationParams(page_size=15, page_offset=9),
        )

        assert resumed.next_cursor is None
        assert len(flavor.transport.calls) == 2
        assert _paging_detail(collection, flavor.transport.calls[1]) == "3"

    @pytest.mark.parametrize("collection", CURSOR_COLLECTIONS, ids=lambda c: c.id)
    def test_resume_sends_ksefs_continuation_token(
        self, collection: Collection, flavor: Flavor
    ) -> None:
        flavor.transport.enqueue(_page(collection, more=True))
        first = _page_at(flavor, collection, _client(collection, flavor), None)

        assert first.next_cursor is not None
        assert _paging_detail(collection, flavor.transport.calls[0]) == "None"

        flavor.transport.enqueue(_page(collection, more=False))
        resumed = _page_at(
            flavor, collection, _client(collection, flavor), first.next_cursor
        )

        assert resumed.next_cursor is None
        assert len(flavor.transport.calls) == 2
        assert _paging_detail(collection, flavor.transport.calls[1]) == "next-page"

    def test_cursor_carries_pagination_state_and_no_credentials(
        self, flavor: Flavor
    ) -> None:
        tokens = DomainAuthTokensFactory.build()
        client = flavor.authenticated(tokens)
        flavor.transport.enqueue(_page(COLLECTIONS_BY_ID["tokens.list"], more=True))

        page = flavor.run(client.tokens.list().page(None))

        assert page.next_cursor is not None
        payload = _cursor_payload(page.next_cursor)
        assert set(json.loads(payload)) <= CURSOR_STATE_FIELDS
        assert tokens.access_token.token not in page.next_cursor
        assert tokens.access_token.token not in payload
        assert tokens.refresh_token.token not in payload
        assert "authorization" not in payload.lower()
        assert "bearer" not in payload.lower()
        recorded = flavor.transport.calls[0].headers or {}
        assert recorded["Authorization"].endswith(tokens.access_token.token)

    def test_cursor_payload_is_decoded_by_the_same_sdk_only(
        self, flavor: Flavor
    ) -> None:
        collection = COLLECTIONS_BY_ID["peppol.list"]
        flavor.transport.enqueue(_page(collection, more=True))

        page = _page_at(
            flavor,
            collection,
            _client(collection, flavor),
            None,
            params=OffsetPaginationParams(page_offset=1),
        )

        assert page.next_cursor is not None
        assert (
            OffsetCursor.decode(page.next_cursor, operation="peppol.list").page_offset
            == 2
        )


class TestCursorValidation:
    @pytest.mark.parametrize(
        ("cursor", "reason"),
        [
            ("", "it is empty"),
            ("not a cursor!!", "not valid Base64"),
            ("a", "not valid Base64"),
            ("bm90IGpzb24=", "not valid JSON"),
            ("Imp1c3QgYSBzdHJpbmci", "not a JSON object"),
        ],
        ids=["empty", "bad-alphabet", "bad-length", "not-json", "not-an-object"],
    )
    def test_malformed_cursor_is_rejected(self, cursor: str, reason: str) -> None:
        with pytest.raises(KSeFArgumentError, match=reason):
            OffsetCursor.decode(cursor, operation="peppol.list")

    @pytest.mark.parametrize(
        "version", [2, True, "1", 1.0], ids=["two", "bool", "str", "float"]
    )
    def test_cursor_with_an_unsupported_version_is_rejected(self, version: Any) -> None:
        cursor = _tampered_cursor(
            {"v": version, "operation": "peppol.list", "page_offset": 1}
        )

        with pytest.raises(KSeFArgumentError, match="its v is invalid"):
            OffsetCursor.decode(cursor, operation="peppol.list")

    @pytest.mark.parametrize(
        "page_offset", [-1, "3", True, 1.5], ids=["negative", "str", "bool", "float"]
    )
    def test_cursor_with_an_invalid_page_offset_is_rejected(
        self, page_offset: Any
    ) -> None:
        cursor = _tampered_cursor(
            {"v": 1, "operation": "peppol.list", "page_offset": page_offset}
        )

        with pytest.raises(KSeFArgumentError, match="its page_offset is invalid"):
            OffsetCursor.decode(cursor, operation="peppol.list")

    def test_cursor_with_an_unknown_field_is_rejected(self) -> None:
        cursor = _tampered_cursor(
            {
                "v": 1,
                "operation": "peppol.list",
                "page_offset": 1,
                "page_size": 999,
            }
        )

        with pytest.raises(KSeFArgumentError, match="its page_size is invalid"):
            OffsetCursor.decode(cursor, operation="peppol.list")

    def test_cursor_missing_a_field_is_rejected(self) -> None:
        cursor = _tampered_cursor({"v": 1, "operation": "peppol.list"})

        with pytest.raises(KSeFArgumentError, match="its page_offset is invalid"):
            OffsetCursor.decode(cursor, operation="peppol.list")

    def test_error_never_echoes_the_cursor(self) -> None:
        cursor = _tampered_cursor(
            {"v": 1, "operation": "peppol.list", "page_offset": -5}
        )

        with pytest.raises(KSeFArgumentError) as caught:
            OffsetCursor.decode(cursor, operation="peppol.list")

        assert cursor not in str(caught.value)
        assert cursor not in str(caught.value.context)


class TestInvoiceSearchCursorState:
    """Invoice search resumes with the request and boundary it stopped on."""

    @pytest.mark.parametrize(
        "boundary",
        [date(2026, 1, 5), datetime(2026, 1, 5, 12, 30, 45)],
        ids=["date", "datetime"],
    )
    def test_boundary_keeps_its_own_type_through_a_cursor(
        self, boundary: date | datetime
    ) -> None:
        """A resumed search compares date with date and timestamp with timestamp.

        A boundary that came back as the other type would never compare equal to the
        next one, so the search would miss that KSeF stopped advancing.
        """
        cursor = InvoiceSearchCursor(
            operation="invoices.search",
            filters=InvoicesFilter(
                role="seller",
                date_type="issue_date",
                date_from=datetime(2026, 1, 1),
            ),
            params=InvoiceMetadataParams(page_size=10, page_offset=1),
            previous_truncation_boundary=boundary,
        )

        resumed = InvoiceSearchCursor.decode(
            cursor.encode(), operation="invoices.search"
        )

        assert resumed.previous_truncation_boundary == boundary
        assert type(resumed.previous_truncation_boundary) is type(boundary)
