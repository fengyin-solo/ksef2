"""Machine-readable description of the public synchronous SDK.

``ksef2.bridge`` gives a non-Python caller everything it needs to drive the SDK
without a Python type in sight. ``manifest()`` describes every operation the
public synchronous surface offers, and ``call()`` runs one of them, taking
arguments and state as JSON and answering in JSON. Nothing here talks to KSeF when
the module is imported or when the manifest is built: only ``call()`` makes a
request, and only the request the named operation makes.

A caller that never keeps state can ignore the second half of this module and use
the convenience operations, which authenticate and run in one call. A caller that
keeps state passes each result's ``state`` straight back into the next ``call()``,
and closes the clients when it is done.
"""

from ksef2.bridge._dispatch import run
from ksef2.bridge._manifest import build_manifest
from ksef2.bridge._runtime import close_clients

__all__ = ["call", "close", "manifest"]


def manifest() -> dict[str, object]:
    """Return the machine-readable map of the public synchronous API.

    The document describes every operation the public synchronous surface offers and
    every operation that is deliberately out, so a binding can cover the API surface
    it is given and explain the rest of it. Read it at startup rather than
    hard-coding a snapshot, because it is what the installed version really
    publishes.

    What it reports:

    - ``format_version``: ``1`` today. It changes only when the shape of the
      document changes.
    - ``ksef2_version``: the version of the installed SDK, which a binding can
      compare against to know whether it needs new bindings.
    - ``operations``: every reachable operation, each with its ``id``, the kind of
      ``receiver`` it is reached from, a one-line ``summary``, its ``parameters``
      (name, ``required``, JSON ``schema``, and ``default`` when the SDK has one),
      the ``returns`` schema and, where the call needs one, the ``state_schema``
      that rebuilds its receiver.
    - ``excluded``: every public method that is not an operation, each with a
      ``reason`` and the exception type it raises when reached. A method that
      returns an async object, takes a callback, a transport or a live session
      client belongs here, and so does anything marked private.
    - ``classes``: the input and result models named by those schemas, listed by
      class name.
    - ``exceptions``: the SDK exception hierarchy, each entry with its ``code`` and
      its ``parent``, so a binding can build a matching hierarchy and branch on the
      codes rather than on message text.

    Returns:
        The manifest as a JSON-compatible dict, ready for ``json.dumps``.
    """
    return build_manifest()


def call(op: str, args_json: str, state_json: str | None = None) -> str:
    """Run one manifest operation, taking and returning JSON.

    This is the only entry point a binding needs in order to work: no Python object
    crosses the boundary in either direction. ``op`` is an ``id`` from
    ``manifest()``, ``args_json`` holds its arguments and ``state_json`` holds the
    state of the session the operation belongs to. The state is what carries a
    session across calls, including across processes and restarts: feed the ``state``
    of each answer straight back into the next call.

    Every call answers with one JSON document and nothing else, so a binding that
    keeps no error handling of its own still works. A call that ran answers::

        {"ok": true, "result": <what the operation returned>, "state": <state>}

    A call that did not answer::

        {"ok": false, "error": {"type": ..., "code": ..., "message": ...,
                                "hint": ..., "context": {...}}}

    ``code`` is what to branch on: ``UNKNOWN_OPERATION`` for an id the manifest does
    not report, ``ARGUMENT_ERROR`` for arguments, state or a cursor the operation
    cannot use, ``NOT_BINDABLE`` for an operation no saved state rebuilds (a pager),
    and otherwise the code of the SDK exception that was raised. For an error that
    came back from KSeF the object also carries ``status_code``, ``ksef_code``,
    ``trace_id``, ``details`` and ``exception_code``. Arguments, state, response
    bodies and request details are never repeated in an error: an argument can be a
    private key and a presigned URL is a capability.

    Bytes go in and out as standard Base64 with ``=`` padding, matching the
    ``contentEncoding`` the manifest gives them. A collection operation takes a
    ``cursor`` argument besides its declared parameters: omit it or send ``null`` for
    the first page, then send back the ``next_cursor`` of the page just read.

    Args:
        op: The ``id`` of one operation from ``manifest()``, such as
            ``invoices.download``.
        args_json: The arguments as a JSON object, following that operation's
            ``parameters``. ``None`` means no arguments.
        state_json: The state as a JSON object, following that operation's
            ``state_schema``. Its five slots are ``environment``, ``authentication``,
            ``online_session``, ``batch_session`` and ``handle``; ``environment`` is
            ``test``, ``demo`` or ``production``, and the rest are ``null`` until a
            call fills them. ``None`` is rejected: send the envelope with the slots
            you have.

    Returns:
        One JSON document: the success envelope, or the failure envelope of the
        reason the call did not run.

    Raises:
        Exception: Anything the SDK raises that is not a ``KSeFException``, a
            ``pydantic.ValidationError`` or a ``json.JSONDecodeError``. A failure of
            that kind is a bug or an environment problem, not a rejected call, and
            the dispatcher does not decide on its own what a binding should do about
            it.
    """
    return run(op, args_json, state_json)


def close() -> None:
    """Close the clients the dispatcher built, and forget them.

    Each environment keeps one client, with its connection pool and its cached
    public-key certificates, from the first call that needed it. They hold network
    resources, so a program that works through a dispatcher at the end of its work
    should call this. A call afterwards builds what it needs again, so this is a
    release, not a shutdown.

    ``client.close`` closes the client of one environment and drops it from the
    cache, which is the same thing seen from inside a call.
    """
    close_clients()
