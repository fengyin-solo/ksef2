"""Opaque, versioned cursors that make a paged collection resumable.

A cursor is the SDK's own page state, serialised to a single string so a caller can
fetch the next page later, from another process, or across a language boundary that
only carries JSON. The classes here own that shape: ``encode()`` produces the string
and ``decode()`` reads it back, rejecting anything the SDK did not issue before any
request is sent.
"""

import base64
import binascii
import hashlib
import json
import re
from datetime import date, datetime
from typing import Literal, Self, cast

from pydantic import Field, ValidationError, field_validator

from ksef2._core.exceptions import KSeFArgumentError
from ksef2._domain.models.base import KSeFPersistedModel
from ksef2._domain.models.invoices import InvoicesFilter
from ksef2._domain.models.pagination import InvoiceMetadataParams

CURSOR_VERSION: Literal[1] = 1
"""Wire format version this SDK writes, and the only one it reads."""

_CURSOR_HINT = (
    "Pass a next_cursor value returned by the same collection operation, or None to "
    "start from the first page."
)

# The characters URL-safe Base64 may use for the payload; padding is checked separately.
_BASE64_BODY = re.compile(r"[A-Za-z0-9_-]+")


class _PaginationCursor(KSeFPersistedModel):
    """Base of the versioned state carried by a pagination cursor."""

    v: Literal[1]
    """Wire format version of the cursor. Required on the wire, so a cursor that names
    no version is refused instead of being read with whatever the SDK happens to write
    today; encoders pass ``CURSOR_VERSION``."""
    operation: str = Field(min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    """SDK operation that issued the cursor."""

    @field_validator("v", mode="before")
    @classmethod
    def _reject_non_integer_version(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("cursor version must be the integer 1")
        return value

    def encode(self) -> str:
        """Return this state as an opaque cursor string.

        Returns:
            A URL-safe string holding the cursor state, which ``decode`` accepts back.
        """
        payload = self.model_dump_json().encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii")

    @classmethod
    def decode(cls, cursor: str, *, operation: str) -> Self:
        """Read a cursor issued for one operation.

        Args:
            cursor: Cursor string returned by ``encode``.
            operation: Operation the caller is resuming; a cursor from another operation is rejected.

        Returns:
            The decoded cursor state.

        Raises:
            KSeFArgumentError: If the cursor is malformed, carries an unsupported format
                version, or belongs to another operation. The cursor itself is never
                echoed back.
        """
        state = _read_state(cursor)
        try:
            decoded = cls.model_validate(state)
        except ValidationError as exc:
            raise _invalid_cursor(_validation_reason(exc)) from exc

        if decoded.operation != operation:
            raise _invalid_cursor(
                f"it was issued for {decoded.operation}, not for {operation}"
            )
        return decoded


class ContinuationCursor(_PaginationCursor):
    """Cursor holding the KSeF continuation token of the page to fetch next."""

    continuation_token: str = Field(min_length=1)
    """Continuation token returned by the previous page."""

    @classmethod
    def encode_next(
        cls, *, operation: str, continuation_token: str | None
    ) -> str | None:
        """Return the cursor for the page a continuation token points at.

        Args:
            operation: Operation the collection is paging through.
            continuation_token: Token from the page just fetched; ``None`` or empty when KSeF reported no further pages.

        Returns:
            The next cursor, or ``None`` when the collection is exhausted.
        """
        if not continuation_token:
            return None
        return cls(
            v=CURSOR_VERSION,
            operation=operation,
            continuation_token=continuation_token,
        ).encode()


class OffsetCursor(_PaginationCursor):
    """Cursor holding the page offset of the page to fetch next."""

    page_offset: int = Field(strict=True, ge=0)
    """Zero-based offset of the page the next request asks for."""

    @classmethod
    def encode_next(
        cls, *, operation: str, page_offset: int, has_more: bool
    ) -> str | None:
        """Return the cursor for the page after the one just fetched.

        Args:
            operation: Operation the collection is paging through.
            page_offset: Offset of the page just fetched.
            has_more: Whether KSeF reported further pages.

        Returns:
            The next cursor, or ``None`` when the collection is exhausted.
        """
        if not has_more:
            return None
        return cls(
            v=CURSOR_VERSION,
            operation=operation,
            page_offset=page_offset + 1,
        ).encode()


class InvoiceSearchCursor(_PaginationCursor):
    """Cursor holding a whole invoice metadata request, including its boundary.

    Invoice search follows page offsets and KSeF truncation boundaries, so resuming
    it needs the filters and parameters of the next request rather than a single
    token. A resumed search therefore keeps working after the date range shifts.
    """

    search: str = Field(pattern=r"^[0-9a-f]{64}$")
    """Fingerprint of the search that issued this cursor, from ``search_fingerprint``.
    It stays the same while the search narrows its own date range, so a pager can refuse
    a cursor that belongs to another search."""
    filters: InvoicesFilter
    """Criteria selecting the invoices for the page to fetch."""
    params: InvoiceMetadataParams
    """Page size, page offset and sort order for the page to fetch."""
    previous_truncation_boundary: date | datetime | None = None
    """Boundary the previous page truncated at, used to detect a stalled search."""
    stalled: Literal["no_invoices", "no_advance"] | None = None
    """Why the search cannot continue past the page that issued this cursor, or ``None``.
    The page was still returned in full; resuming this cursor raises the pagination error
    instead of sending a request, so the failure is reported after the invoices are."""

    @classmethod
    def decode_search(cls, cursor: str, *, operation: str, search: str) -> Self:
        """Read a cursor and check that the given search issued it.

        Args:
            cursor: Cursor string returned by ``encode``.
            operation: Operation the caller is resuming.
            search: Fingerprint of the search the caller is resuming, from ``search_fingerprint``.

        Returns:
            The decoded cursor state.

        Raises:
            KSeFArgumentError: If the cursor is malformed, belongs to another operation, or was issued by a different search. The cursor itself is never echoed back.
        """
        decoded = cls.decode(cursor, operation=operation)
        if decoded.search != search:
            raise _invalid_cursor(
                "it was issued by a different search than the one this pager runs"
            )
        return decoded

    @field_validator("previous_truncation_boundary", mode="before")
    @classmethod
    def _read_boundary_kind(cls, value: object) -> object:
        """Read stored boundary text back as the kind of value it was written from.

        Pydantic happily fills a ``date | datetime`` field with a ``date`` read from a
        midnight timestamp, and a ``date`` never compares equal to the timestamp at that
        same instant. The search compares consecutive boundaries to notice that KSeF
        stopped advancing, so a boundary that came back as the other kind would hide a
        stalled search. Stored ISO text names its own kind: a calendar date is exactly
        ten characters, and anything longer carries a time after the ``T`` separator (or
        the space some writers put there instead). Values that are not text keep the kind
        they came in with.

        Raises:
            ValueError: If the stored text is neither an ISO date nor an ISO timestamp.
        """
        if not isinstance(value, str):
            return value
        if len(value) > 10 and value[10] in "Tt ":
            return datetime.fromisoformat(value)
        return date.fromisoformat(value)


def search_fingerprint(filters: InvoicesFilter, params: InvoiceMetadataParams) -> str:
    """Identify an invoice search independently of how far it has progressed.

    The fingerprint covers the filters, the page size and the sort order. It leaves out
    the page offset, which moves with every page, and ``date_to``, which defaults to the
    moment the filters were built, so a pager rebuilt after a restart with the same
    criteria still recognises its own cursors.

    Args:
        filters: Filters the search started with.
        params: Parameters the search started with.

    Returns:
        A SHA-256 hex digest.
    """
    identity = {
        "filters": filters.model_dump(mode="json", exclude={"date_to"}),
        "page_size": params.page_size,
        "sort_order": params.sort_order,
    }
    text = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_state(cursor: str) -> dict[str, object]:
    """Decode the JSON object stored inside a cursor string.

    Raises:
        KSeFArgumentError: If the cursor is not URL-safe Base64 UTF-8 JSON.
    """
    payload = _decode_base64(cursor)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _invalid_cursor("its payload is not valid UTF-8") from exc

    try:
        parsed = cast(object, json.loads(text))
    except json.JSONDecodeError as exc:
        raise _invalid_cursor("its payload is not valid JSON") from exc

    if not isinstance(parsed, dict):
        raise _invalid_cursor("its payload is not a JSON object")

    state = cast(dict[object, object], parsed)
    return {str(key): value for key, value in state.items()}


def _decode_base64(cursor: str) -> bytes:
    """Decode the payload of a URL-safe Base64 cursor, padded or unpadded.

    The SDK writes canonical padding and a caller who stripped it is still accepted, so
    that a cursor survives a store that trims trailing ``=``. Every other spelling is
    refused before a request goes out: characters outside the URL-safe alphabet (``+``,
    ``/``, whitespace, non-ASCII), padding inside the payload, and a padding run that is
    not the exact one a payload of that length gets.

    Raises:
        KSeFArgumentError: If the cursor is empty or is not spelled as URL-safe Base64.
    """
    if not cursor:
        raise _invalid_cursor("it is empty")

    head, equals, tail = cursor.partition("=")
    if equals and set(tail) - {"="}:
        raise _invalid_cursor("its Base64 padding is misplaced")
    padding = 0 if not equals else 1 + len(tail)

    if _BASE64_BODY.fullmatch(head) is None:
        raise _invalid_cursor("it is not URL-safe Base64")
    if len(head) % 4 == 1:
        raise _invalid_cursor("it is not valid Base64")
    # A Base64 payload of this length takes exactly this much padding, and a cursor either
    # carries that or carries none of it.
    expected_padding = -len(head) % 4
    if padding not in (0, expected_padding):
        raise _invalid_cursor("its Base64 padding is malformed")

    try:
        return base64.b64decode(
            head + "=" * expected_padding, altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError) as exc:
        raise _invalid_cursor("it is not valid Base64") from exc


def _validation_reason(exc: ValidationError) -> str:
    """Describe the first validation failure without quoting the caller's cursor."""
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"]) or "cursor"
    problem = "is missing" if error["type"] == "missing" else "is invalid"
    return f"its {location} {problem} ({error['msg']})"


def _invalid_cursor(reason: str) -> KSeFArgumentError:
    """Build the error reported for a cursor the SDK did not issue."""
    return KSeFArgumentError(
        f"Invalid pagination cursor because {reason}.", hint=_CURSOR_HINT
    )
