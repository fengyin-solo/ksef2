"""Share root clients across concurrent calls and close them once idle.

One ``Client`` per ``Environment`` is built on first use and kept until
``close()``. Reusing them matters because a binding calls through the dispatcher
many times, and each root client owns a connection pool and a public-key
certificate store. A condition guards the cache, the number of calls using each
environment and the environments being closed. It is never held during requests
or while a client closes. Calls for an environment being closed wait until it is
available, then build a fresh client. Other environments can keep working.

Nothing here is exported: a caller either dispatches an operation or closes.
"""

import threading
from typing import Final

from ksef2._clients.base import Client
from ksef2._config import Environment

_CONDITION: Final = threading.Condition()
"""Guards the registries, never held during requests or client closure."""

_CLIENTS: Final[dict[Environment, Client]] = {}
"""The clients built so far, keyed by the environment they talk to."""

_IN_FLIGHT: Final[dict[Environment, int]] = {}
"""The number of calls currently using each environment's client."""

_CLOSING: Final[set[Environment]] = set()
"""The environments whose clients are being closed."""


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


def acquire(environment: Environment) -> Client:
    """Return the environment's shared client and count this call as using it.

    Args:
        environment: KSeF environment the caller is working against.

    Returns:
        The client this environment uses.
    """
    with _CONDITION:
        while environment in _CLOSING:
            _ = _CONDITION.wait()
        client = _CLIENTS.get(environment)
        if client is None:
            client = build_client(environment)
            _ = client.authentication, client.encryption, client.peppol
            if environment is Environment.TEST:
                _ = client.testdata
            _CLIENTS[environment] = client
        _IN_FLIGHT[environment] = _IN_FLIGHT.get(environment, 0) + 1
        return client


def release(environment: Environment) -> None:
    """Stop counting one call as using the environment's client.

    Args:
        environment: KSeF environment the call was using.
    """
    with _CONDITION:
        remaining = _IN_FLIGHT[environment] - 1
        if remaining:
            _IN_FLIGHT[environment] = remaining
        else:
            del _IN_FLIGHT[environment]
        _CONDITION.notify_all()


def close_environment(environment: Environment) -> None:
    """Close one environment's client once no call is using it.

    Args:
        environment: KSeF environment whose client should be closed.
    """
    with _CONDITION:
        if environment in _CLOSING:
            return
        _CLOSING.add(environment)
        while _IN_FLIGHT.get(environment, 0) > 0:
            _ = _CONDITION.wait()
        client = _CLIENTS.pop(environment, None)
    try:
        if client is not None:
            client.close()
    finally:
        with _CONDITION:
            _CLOSING.discard(environment)
            _CONDITION.notify_all()


def close_clients() -> None:
    """Close every cached client once no call is using it.

    Every cached environment is attempted even when another client fails. Clients
    are forgotten before closing, so a later call cannot reach a half-closed client.

    Raises:
        Exception: Whatever a client raised while closing.
    """
    with _CONDITION:
        environments = list(_CLIENTS)
    errors: list[Exception] = []
    for environment in environments:
        try:
            close_environment(environment)
        except Exception as exc:
            errors.append(exc)
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise ExceptionGroup("closing bridge clients failed", errors)
