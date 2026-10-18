"""Opaque, versioned cursors that make a paged collection resumable.

A cursor is the SDK's own page state, serialised to a single string so a caller can
fetch the next page later, from another process, or across a language boundary that
only carries JSON. The classes here own that shape: ``encode()`` produces the string
and ``decode()`` reads it back, rejecting anything the SDK did not issue before any
request is sent.
"""

import base64
import binascii
import json
from datetime import date, datetime
from typing import Literal, Self, cast

from pydantic import Field, ValidationError, field_validator, model_validator

from ksef2._core.exceptions import KSeFArgumentError
from ksef2._domain.models.base import KSeFPersistedModel
from ksef2._domain.models.invoices import InvoicesFilter
from ksef2._domain.models.pagination import InvoiceMetadataParams

_CURSOR_HINT = (
    "Pass a next_cursor value returned by the same collection operation, or None to "
    "start from the first page."
)


class _PaginationCursor(KSeFPersistedModel):
    """Base of the versioned state carried by a pagination cursor."""

    v: Literal[1] = 1
    """Wire format version of the cursor."""
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
        return cls(operation=operation, continuation_token=continuation_token).encode()


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
        return cls(operation=operation, page_offset=page_offset + 1).encode()


class InvoiceSearchCursor(_PaginationCursor):
    """Cursor holding a whole invoice metadata request, including its boundary.

    Invoice search follows page offsets and KSeF truncation boundaries, so resuming
    it needs the filters and parameters of the next request rather than a single
    token. A resumed search therefore keeps working after the date range shifts.
    """

    filters: InvoicesFilter
    """Criteria selecting the invoices for the page to fetch."""
    params: InvoiceMetadataParams
    """Page size, page offset and sort order for the page to fetch."""
    previous_truncation_boundary: date | datetime | None = None
    """Boundary the previous page truncated at, used to detect a stalled search."""

    @model_validator(mode="before")
    @classmethod
    def _restore_boundary_type(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        state = cast(dict[str, object], data)
        raw_boundary = state.get("previous_truncation_boundary")
        if not isinstance(raw_boundary, str):
            return state
        restored: dict[str, object] = {
            **state,
            "previous_truncation_boundary": _parse_boundary(raw_boundary),
        }
        return restored


def _parse_boundary(text: str) -> date | datetime:
    """Read a truncation boundary back as the date or datetime KSeF reported."""
    try:
        return date.fromisoformat(text)
    except ValueError:
        return datetime.fromisoformat(text)


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
    """Decode a URL-safe Base64 cursor payload with or without its padding.

    Raises:
        KSeFArgumentError: If the cursor is empty or uses characters outside the alphabet.
    """
    if not cursor:
        raise _invalid_cursor("it is empty")

    body = cursor.rstrip("=")
    if len(body) % 4 == 1:
        raise _invalid_cursor("it is not valid Base64")

    try:
        return base64.b64decode(
            body + "=" * (-len(body) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError) as exc:
        raise _invalid_cursor("it is not valid Base64") from exc


def _validation_reason(exc: ValidationError) -> str:
    """Describe the first validation failure without quoting the caller's cursor."""
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"]) or "cursor"
    return f"its {location} is invalid ({error['msg']})"


def _invalid_cursor(reason: str) -> KSeFArgumentError:
    """Build the error reported for a cursor the SDK did not issue."""
    return KSeFArgumentError(
        f"Invalid pagination cursor because {reason}.", hint=_CURSOR_HINT
    )
