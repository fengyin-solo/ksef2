"""The root clients the dispatcher reuses, and the lock that guards them.

One ``Client`` per ``Environment`` is built on first use and kept until
``close()``. Reusing them matters because a binding calls through the dispatcher
many times, and each root client owns a connection pool and a public-key
certificate store. Every access to this cache happens under ``lock()``, which
``call()`` holds for the whole operation, so a Rust caller that spreads calls
over ``spawn_blocking`` never sees two threads build the same client.

Nothing here is exported: a caller either dispatches an operation or closes.
"""

import threading
from typing import Final

from ksef2._clients.base import Client
from ksef2._config import Environment

_LOCK: Final = threading.RLock()
"""Held by ``call()`` for the whole operation, and by ``close_clients()``."""

_CLIENTS: Final[dict[Environment, Client]] = {}
"""The clients built so far, keyed by the environment they talk to."""


def lock() -> threading.RLock:
    """Return the lock every dispatcher entry point takes.

    Returns:
        The reentrant lock around the client cache. It is reentrant so an
        operation that closes its own environment can reuse the held lock.
    """
    return _LOCK


def build_client(environment: Environment) -> Client:
    """Build the root client of one environment.

    A test replaces this one function to hand the dispatcher a client over its
    own ``httpx.Client``, which is why ``call()`` takes no transport argument of
    its own.

    Args:
        environment: KSeF environment the client talks to.

    Returns:
        A root client that owns its connection pool.
    """
    return Client(environment)


def client_for(environment: Environment) -> Client:
    """Return the shared client of one environment, building it once.

    The caller holds ``lock()``; that is what keeps a second thread from
    building a client that is then thrown away.

    Args:
        environment: KSeF environment the caller is working against.

    Returns:
        The client this environment uses.
    """
    client = _CLIENTS.get(environment)
    if client is None:
        client = build_client(environment)
        _CLIENTS[environment] = client
    return client


def drop_client(environment: Environment) -> None:
    """Forget the client of one environment, which the caller has just closed.

    ``client.close`` is an operation like any other, and a binding is allowed to
    close the client it was handed. Forgetting it is what lets the next call
    against that environment work instead of meeting a closed client.

    Args:
        environment: KSeF environment whose client is gone.
    """
    _ = _CLIENTS.pop(environment, None)


def close_clients() -> None:
    """Close every cached client and drop the cache.

    Each client is closed, and the cache is emptied even when one of them fails,
    so a later call cannot reach a half-closed client.

    Raises:
        Exception: Whatever a client raised while closing.
    """
    with _LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
        errors: list[Exception] = []
        for client in clients:
            try:
                client.close()
            except Exception as exc:
                errors.append(exc)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("closing bridge clients failed", errors)
