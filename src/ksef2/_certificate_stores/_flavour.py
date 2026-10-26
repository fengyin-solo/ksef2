"""Checks that a signing-certificate store matches the client that uses it."""

import inspect

from ksef2._certificate_stores.async_protocols import (
    AsyncSigningCertificateStoreProtocol,
)
from ksef2._certificate_stores.protocols import SigningCertificateStoreProtocol
from ksef2._core import exceptions

_STORE_METHODS = ("save", "load", "list", "delete")


def require_async_store(store: object) -> None:
    """Raise unless ``store`` is an async signing-certificate store.

    Both store protocols declare the same method names, so ``isinstance`` alone cannot
    tell a sync store from an async one: either satisfies the other structurally. This
    check also looks at whether the four store methods are coroutine functions, which
    is what decides whether a client can ``await`` them.

    Args:
        store: Value passed by the caller as ``store``.

    Raises:
        KSeFArgumentError: If ``store`` is not an async signing-certificate store.
    """
    if not isinstance(store, AsyncSigningCertificateStoreProtocol) or not all(
        inspect.iscoroutinefunction(
            getattr(store, name)  # pyright: ignore[reportAny]
        )
        for name in _STORE_METHODS
    ):
        raise exceptions.KSeFArgumentError(
            "An async client needs an async signing certificate store.",
            hint="Pass an AsyncSigningCertificateStoreProtocol implementation, such as "
            "AsyncInMemorySigningCertificateStore.",
        )


def require_sync_store(store: object) -> None:
    """Raise unless ``store`` is a sync signing-certificate store.

    Both store protocols declare the same method names, so ``isinstance`` alone cannot
    tell a sync store from an async one: either satisfies the other structurally. This
    check also looks at whether the four store methods are coroutine functions, which
    is what decides whether a client receives records or coroutines from them.

    Args:
        store: Value passed by the caller as ``store``.

    Raises:
        KSeFArgumentError: If ``store`` is not a sync signing-certificate store.
    """
    if not isinstance(store, SigningCertificateStoreProtocol) or any(
        inspect.iscoroutinefunction(
            getattr(store, name)  # pyright: ignore[reportAny]
        )
        for name in _STORE_METHODS
    ):
        raise exceptions.KSeFArgumentError(
            "A sync client needs a sync signing certificate store.",
            hint="Pass a SigningCertificateStoreProtocol implementation, such as "
            "InMemorySigningCertificateStore.",
        )
