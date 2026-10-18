"""Generic paging object returned by collection operations."""

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
import typing
from typing import Generic, TypeVar

from ksef2._clients._pagination_cursor import OffsetCursor
from ksef2._core import exceptions
from ksef2._core.polling import async_poll_until
from ksef2._domain.models.pagination import Page

_T = TypeVar("_T")

_LEGACY_OPERATION = "pager.pages"


class AsyncPager(Generic[_T]):
    """Lazy view over a paged collection in KSeF.

    Iterating the pager yields every item across all pages, requesting pages as
    needed. ``pages()`` yields one list of items per page, and ``first_page()``
    fetches only the first. Nothing is requested until the pager is consumed, and
    every iteration starts from the first page again.

    ``page()`` is the resumable form of the same walk: it fetches one page and
    returns it with ``next_cursor``, an opaque string that a later call, a
    restarted process or another language binding passes back to continue where
    this page ended. Keep the cursor as a string and treat its contents as SDK
    state.

    Raises:
        KSeFApiError: If KSeF returns an API error response while a page is
            fetched.
        KSeFValidationError: If a KSeF response cannot be parsed into SDK models.
        httpx.HTTPError: If the HTTP transport fails before KSeF returns a response.
    """

    def __init__(
        self,
        pages: Callable[[], AsyncGenerator[list[_T], None]] | None = None,
        *,
        timeout_error: Callable[[float], BaseException] | None = None,
        fetch_page: Callable[[str | None], Awaitable[Page[_T]]] | None = None,
    ) -> None:
        """Create the pager.

        Args:
            pages: Factory returning a fresh generator over the pages, each one a list of items. Callers that already own a generator supply it here; SDK collections do not. When ``fetch_page`` is also supplied, the pager uses it and ignores this factory.
            timeout_error: Builds the exception ``wait()`` raises from its timeout; ``None`` raises ``TimeoutError``.
            fetch_page: Fetches exactly one page for a cursor, where ``None`` asks for the first page. Every SDK collection supplies this, so paging never replays earlier requests.

        Raises:
            KSeFArgumentError: If neither ``pages`` nor ``fetch_page`` is supplied.
        """
        if fetch_page is None:
            if pages is None:
                raise exceptions.KSeFArgumentError(
                    "A pager needs a source of pages.",
                    hint="Pass a pages factory or a fetch_page callback.",
                )
            self._pages = pages
            self._fetch_page = self._build_legacy_page_source(pages)
        else:
            self._pages = None
            self._fetch_page = fetch_page
        self._timeout_error = timeout_error

    def __aiter__(self) -> AsyncIterator[_T]:
        return self._items()

    async def _items(self) -> AsyncGenerator[_T, None]:
        async for page in self.pages():
            for item in page:
                yield item

    def pages(self) -> AsyncIterator[list[_T]]:
        """Iterate over the collection one page at a time.

        Returns:
            An iterator yielding the items of each page as a list, in order.
        """
        if self._pages is None:
            return self._pages_from_cursor()
        return self._pages()

    async def first_page(self) -> list[_T]:
        """Fetch only the first page.

        Returns:
            The items of the first page; empty if the collection is empty.
        """
        pages = self._pages
        if pages is None:
            return (await self._fetch_page(None)).items

        generator = pages()
        try:
            async for page in generator:
                return page
            return []
        finally:
            await generator.aclose()

    # Runtime checks are off for this one method on purpose. Beartype compares a return
    # value against the Page[...] class object the annotation denoted, and Page[_T] here
    # denotes the pager's own unresolved type variable, which no page can be an instance
    # of. Every fetch_page callback keeps its concrete Page[Item] annotation and stays
    # checked; static typing checks this signature as usual.
    @typing.no_type_check
    async def page(self, cursor: str | None = None) -> Page[_T]:
        """Fetch one page and the cursor that resumes the collection after it.

        Call it with ``None`` for the first page, then with the ``next_cursor`` of
        the page just read. Any pager of the same collection operation, built in
        another process or after a restart, accepts the cursor; a non-invoice
        collection must be rebuilt with the same filters, identifiers and page
        size, because its cursor carries only KSeF's continuation state. Passing
        ``None`` as ``next_cursor`` means the collection ended.

        Args:
            cursor: Cursor from a previous page, or ``None`` for the first page.

        Returns:
            The requested page, with its items and the cursor for the page after it.

        Raises:
            KSeFArgumentError: If ``cursor`` was not issued by this collection operation.
            KSeFApiError: If KSeF returns an API error response while the page is fetched.
        """
        return await self._fetch_page(cursor)

    async def _pages_from_cursor(self) -> AsyncGenerator[list[_T], None]:
        cursor: str | None = None
        while True:
            page = await self._fetch_page(cursor)
            yield page.items
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

    async def wait(
        self,
        *,
        timeout: float = 120.0,
        poll_interval: float = 2.0,
    ) -> "AsyncPager[_T]":
        """Poll until the collection contains at least one item.

        Use it when KSeF indexes items with a delay, for example invoices that were
        accepted a moment ago and are not searchable yet.

        Args:
            timeout: Maximum number of seconds to wait before giving up.
            poll_interval: Delay in seconds between checks.

        Returns:
            This pager, now known to be non-empty. Iterating it requests the pages again.

        Raises:
            KSeFInvoiceQueryTimeoutError: For invoice searches, if no invoice appears within ``timeout``.
            TimeoutError: For other collections, if no item appears within ``timeout``.
        """
        _ = await async_poll_until(
            operation=self.first_page,
            retry_predicate=lambda page: not page,
            poll_interval=poll_interval,
            timeout_seconds=timeout,
            timeout_error_factory=lambda: self._build_timeout_error(timeout),
        )
        return self

    def _build_timeout_error(self, timeout: float) -> BaseException:
        if self._timeout_error is not None:
            return self._timeout_error(timeout)
        return TimeoutError(f"No items appeared after {timeout}s")

    def _build_legacy_page_source(
        self, pages: Callable[[], AsyncGenerator[list[_T], None]]
    ) -> Callable[[str | None], Awaitable[Page[_T]]]:
        """Adapt a caller-supplied generator to the cursor-based page source.

        A generator has no way to name its next page, so this adapter counts pages
        and stores the count in the cursor. Reading page N replays the caller's
        generator up to page N, which a live KSeF collection never does.

        Args:
            pages: Factory returning a fresh generator over the caller's pages.

        Returns:
            A page source that resumes a generator-supplied collection by page index.
        """
        # Built through the same Page[_T] the annotations below denote, so a page this
        # adapter returns is an instance of exactly the class runtime checks expect.
        page_type = Page[_T]

        async def _page_by_index(cursor: str | None) -> Page[_T]:
            index = (
                0
                if cursor is None
                else OffsetCursor.decode(
                    cursor, operation=_LEGACY_OPERATION
                ).page_offset
            )
            items: list[_T] = []
            has_next = False
            generator = pages()
            try:
                seen = 0
                async for page in generator:
                    seen += 1
                    if seen == index + 1:
                        items = list(page)
                        continue
                    if seen > index + 1:
                        has_next = True
                        break
            finally:
                await generator.aclose()

            return page_type(
                items=items,
                next_cursor=OffsetCursor.encode_next(
                    operation=_LEGACY_OPERATION, page_offset=index, has_more=has_next
                ),
            )

        return _page_by_index
