"""The guards that keep a sync store out of an async client and the reverse."""

from collections.abc import Callable

import pytest

from ksef2._certificate_stores._flavour import require_async_store, require_sync_store
from ksef2._certificate_stores.async_memory import AsyncInMemorySigningCertificateStore
from ksef2._certificate_stores.memory import InMemorySigningCertificateStore
from ksef2._core.exceptions import KSeFArgumentError


def test_async_guard_accepts_the_async_store() -> None:
    require_async_store(AsyncInMemorySigningCertificateStore())


def test_sync_guard_accepts_the_sync_store() -> None:
    require_sync_store(InMemorySigningCertificateStore())


def test_async_guard_rejects_the_sync_store() -> None:
    # Both stores satisfy both protocols structurally, so the coroutine check is
    # what tells them apart.
    with pytest.raises(KSeFArgumentError, match="needs an async signing certificate"):
        require_async_store(InMemorySigningCertificateStore())


def test_sync_guard_rejects_the_async_store() -> None:
    with pytest.raises(KSeFArgumentError, match="needs a sync signing certificate"):
        require_sync_store(AsyncInMemorySigningCertificateStore())


@pytest.mark.parametrize(
    ("guard", "store"),
    [(require_async_store, object()), (require_sync_store, object())],
    ids=["async-guard", "sync-guard"],
)
def test_both_guards_reject_a_value_that_is_not_a_store(
    guard: Callable[[object], None], store: object
) -> None:
    with pytest.raises(KSeFArgumentError, match="signing certificate store"):
        guard(store)
