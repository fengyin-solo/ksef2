"""Run one manifest operation from JSON, and answer in JSON.

A call is read in four steps. The operation is looked up in the table built from
the manifest. The state envelope is turned into the client the operation belongs
to, resuming a session only when that operation needs one. The arguments are
validated against the types the member itself declares. The result is written
back together with the state that rebuilds whatever the call left running.

A wrong id, an argument the operation does not take and a missing session are all
reported the same way a rejected API call is: a failure envelope on the wire, not
an exception across the boundary. Anything else the SDK raises travels on, because
a dispatcher that swallows an unexpected exception hides a bug in the SDK from the
binding that hit it.
"""

import json
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, TypeVar, cast

from pydantic import BaseModel, ValidationError

from ksef2._clients._pager import Pager
from ksef2._clients.authenticated import AuthenticatedClient
from ksef2._clients.base import Client
from ksef2._clients.batch import BatchSessionClient
from ksef2._clients.exported_invoices import ExportedInvoices
from ksef2._clients.online import OnlineSessionClient
from ksef2._clients.tokens import GeneratedToken
from ksef2._config import Environment
from ksef2._core.exceptions import KSeFException
from ksef2._domain.models.auth import AuthenticationResumeState
from ksef2._domain.models.batch import BatchSessionResumeState, PreparedBatch
from ksef2._domain.models.certificates import CertificateEnrollmentResumeState
from ksef2._domain.models.invoices import (
    ExportedInvoicesData,
    ExportResumeState,
    InvoiceSubmissionResumeState,
)
from ksef2._domain.models.permissions import PermissionOperationResumeState
from ksef2._domain.models.session import OnlineSessionResumeState
from ksef2._domain.models.tokens import GeneratedTokenResumeState
from ksef2.bridge._bytes import bytes_plan
from ksef2.bridge._codec import decode_base64
from ksef2.bridge._catalog import RESUME_STATE_BY_CLASS
from ksef2.bridge._json import (
    argument_error,
    describe_validation,
    dump_state,
    encode,
    error_of,
    read_json_object,
    unknown_operation,
)
from ksef2.bridge._operations import (
    CURSOR,
    Operation,
    class_of,
    excluded_reasons,
    lookup,
)
from ksef2.bridge._runtime import acquire, close_environment, release

_StateT = TypeVar("_StateT", bound=BaseModel)

ENVIRONMENTS: Final[dict[str, Environment]] = {
    "test": Environment.TEST,
    "demo": Environment.DEMO,
    "production": Environment.PRODUCTION,
}
"""The environment names a state envelope may carry."""

SLOTS: Final[tuple[str, ...]] = (
    "environment",
    "authentication",
    "online_session",
    "batch_session",
    "handle",
)
"""The five slots of a state envelope, in the order a binding reads them."""

_SESSION_SLOT_BY_CLASS: Final[dict[type[BaseModel], str]] = {
    AuthenticationResumeState: "authentication",
    OnlineSessionResumeState: "online_session",
    BatchSessionResumeState: "batch_session",
}
"""The three slots that hold a session, and the state each one holds."""

_SESSION_SLOTS: Final[dict[str, type[BaseModel]]] = {
    slot: state for state, slot in _SESSION_SLOT_BY_CLASS.items()
}
"""The same three slots, read by name."""

_HANDLE_STATES: Final[frozenset[type[BaseModel]]] = frozenset(
    RESUME_STATE_BY_CLASS.values()
) - frozenset(_SESSION_SLOT_BY_CLASS)
"""Every state that rebuilds a handle, which is what the handle slot holds."""

_SAVED_FORM: Final[dict[type[object], str]] = {
    **dict.fromkeys(RESUME_STATE_BY_CLASS, "resume_state"),
    ExportedInvoices: "to_model",
}
"""How each live handle writes the state that rebuilds it later."""

_UNAUTHENTICATED: Final[dict[str, str]] = {
    "auth": "authentication",
    "encryption": "encryption",
    "peppol": "peppol",
    "testdata": "testdata",
}
"""Prefixes reachable without credentials, and the accessor that reaches them."""

_AUTHENTICATED: Final[dict[str, str]] = {
    "batch_service": "batch",
    "tokens": "tokens",
    "certificates": "certificates",
    "permissions": "permissions",
    "invoices": "invoices",
    "limits": "limits",
    "collective_identifiers": "collective_identifiers",
    "sessions": "sessions",
    "invoice_sessions": "invoice_sessions",
}
"""Prefixes that need a session, and the accessor that reaches them on it."""

_HANDLES: Final[frozenset[str]] = frozenset(
    {
        "generated_token",
        "certificate_enrollment",
        "permission_operation",
        "invoice_submission",
        "export_job",
        "exported_invoices",
    }
)
"""Prefixes whose receiver is rebuilt from a saved handle."""

_GENERATED_TOKEN: Final[str] = "token"
"""The attribute of a generated token that holds the one-time credential."""

_CLOSE: Final[str] = "client.close"
"""The operation that closes the client of its own environment."""


@dataclass(frozen=True)
class Outcome:
    """One call that ran, ready to be written out.

    Attributes:
        result: The JSON data the operation produced.
        state: The state envelope a binding sends to the next call.
    """

    result: object
    state: dict[str, object]


def run(op: str, args_json: str | None, state_json: str | None) -> str:
    """Run one operation and answer with exactly one JSON document.

    Calls run concurrently on shared clients. Each scope counts its use so closing
    an environment waits until its calls have finished.

    Args:
        op: The manifest id of the operation.
        args_json: Its arguments as a JSON object.
        state_json: The state of the session it belongs to.

    Returns:
        A success envelope holding the result and the next state, or a failure
        envelope holding the error.
    """
    try:
        outcome = _call(op, args_json, state_json)
    except (KSeFException, ValidationError, json.JSONDecodeError) as exc:
        return json.dumps({"ok": False, "error": error_of(exc)}, ensure_ascii=False)
    return json.dumps(
        {"ok": True, "result": outcome.result, "state": outcome.state},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _call(op: str, args_json: str | None, state_json: str | None) -> Outcome:
    """Do the work behind one call.

    Args:
        op: The manifest id of the operation.
        args_json: Its arguments as a JSON object.
        state_json: The state of the session it belongs to.

    Returns:
        The result data and the state that follows it.

    Raises:
        KSeFArgumentError: The id is unknown or the documents do not describe a call.
        KSeFException: Anything the operation itself raises.
    """
    operation = lookup(op)
    if operation is None:
        raise unknown_operation(op, excluded_reasons().get(op))
    envelope = read_envelope(op, state_json)
    scope = _Scope(operation, envelope)
    try:
        arguments, cursor = read_arguments(operation, args_json)
        for parameter in operation.parameters:
            if parameter.client is not None and parameter.name in arguments:
                arguments[parameter.name] = scope.rebuild(
                    parameter.client, arguments[parameter.name], arguments
                )
        if operation.id == _CLOSE:
            close_environment(scope.environment)
            value = None
        else:
            value = invoke(operation, _receiver(operation, scope), arguments, cursor)
        return Outcome(result=encode_result(op, value), state=updated(envelope, value))
    finally:
        scope.release()


class _Scope:
    """The clients one call needs, resumed only as far as that call asks.

    Attributes:
        operation: The operation being called.
        envelope: The state envelope it was given, already decoded.
    """

    def __init__(self, operation: Operation, envelope: dict[str, object]) -> None:
        """Record the call this scope serves.

        Args:
            operation: The operation being called.
            envelope: The decoded state envelope.
        """
        self.operation = operation
        self.envelope = envelope
        self._client: Client | None = None
        self._authenticated: AuthenticatedClient | None = None

    @property
    def environment(self) -> Environment:
        """The environment this call works against."""
        return ENVIRONMENTS[cast("str", self.envelope["environment"])]

    def client(self) -> Client:
        """Return the root client of this call's environment.

        Returns:
            The shared client for that environment.
        """
        if self._client is None:
            self._client = acquire(self.environment)
        return self._client

    def release(self) -> None:
        """Release this scope's use of its shared client, if acquired."""
        if self._client is not None:
            release(self.environment)
            self._client = None

    def authenticated(self) -> AuthenticatedClient:
        """Return the client of the saved session, resumed once per call.

        Returns:
            The authenticated client the operation belongs to.

        Raises:
            KSeFArgumentError: The state carries no session.
        """
        if self._authenticated is None:
            state = self.session("authentication", AuthenticationResumeState)
            self._authenticated = self.client().authentication.resume(state)
        return self._authenticated

    def online(self) -> OnlineSessionClient:
        """Return the online session the state names.

        Returns:
            A session handle rebuilt from saved state.

        Raises:
            KSeFArgumentError: The state carries no session or no online session.
        """
        state = self.session("online_session", OnlineSessionResumeState)
        return self.authenticated().online_session(state=state)

    def batch(self) -> BatchSessionClient:
        """Return the batch session rebuilt from its saved state.

        Returns:
            The session without an attached upload payload.
        """
        return self.authenticated().batch_session(
            state=self.session("batch_session", BatchSessionResumeState)
        )

    def rebuild(
        self, client: type[object], state: object, arguments: dict[str, object]
    ) -> object:
        """Rebuild a client argument from its validated state and optional payload.

        Args:
            client: The declared live client class.
            state: Its validated resume state.
            arguments: The validated arguments of this call.

        Returns:
            The client the SDK member accepts.

        Raises:
            RuntimeError: The bridge cannot rebuild the declared client class.
        """
        if client is BatchSessionClient:
            resume = cast("BatchSessionResumeState", state)
            if "prepared_batch" in arguments:
                return self.authenticated().batch_session(
                    state=resume,
                    prepared_batch=cast("PreparedBatch", arguments["prepared_batch"]),
                )
            return self.authenticated().batch_session(state=resume)
        raise RuntimeError(f"the dispatcher cannot rebuild client {client.__name__}")

    def handle(self, expected: type[_StateT]) -> _StateT:
        """Return the handle the state names, as the state this operation continues.

        Args:
            expected: The state this operation continues.

        Returns:
            The saved state of the handle.

        Raises:
            KSeFArgumentError: The state carries no handle, or one that is not this state.
        """
        raw = self.envelope["handle"]
        if raw is None:
            raise argument_error(
                self.operation.id,
                "state_json carries no handle, and this operation continues one.",
                hint="Send back the state of the handle the call that created it returned.",
            )
        declared = self.operation.state_model
        if declared is not expected:
            named = (
                "does not continue a handle at all"
                if declared is None
                else (f"continues a {declared.__name__}, not a {expected.__name__}")
            )
            raise argument_error(
                self.operation.id,
                f"state_json carries a handle, and this operation {named}.",
                hint="Send back the state the call that created this handle returned, unchanged.",
            )
        return read_state(self.operation.id, "handle", raw, expected)

    def session(self, slot: str, expected: type[_StateT]) -> _StateT:
        """Return the session one slot of the state holds.

        Args:
            slot: The slot to read.
            expected: The state that operation needs there.

        Returns:
            The session state from that slot.

        Raises:
            KSeFArgumentError: That slot is empty.
        """
        raw = self.envelope[slot]
        if raw is None:
            raise argument_error(
                self.operation.id,
                f"state_json carries no {slot}, and this operation needs one.",
                hint=f"Send back the {expected.__name__} the previous call returned in {slot}.",
            )
        return read_state(self.operation.id, slot, raw, expected)


def read_envelope(op: str, state_json: str | None) -> dict[str, object]:
    """Read and check a state envelope.

    The envelope is kept as the JSON the caller sent, because a call that changes no
    state answers with the envelope it was given. The models behind those values are
    read by ``_Scope`` when the operation actually needs one.

    Args:
        op: The operation the state belongs to, used only in messages.
        state_json: The envelope as JSON text.

    Returns:
        The envelope, with every slot the caller left out set to ``None``.

    Raises:
        KSeFArgumentError: The document is absent, is not JSON, is not an object,
            names an environment the SDK cannot reach, has a slot no envelope has, or
            holds something that is not the state its slot names.
    """
    document = read_json_object(op, state_json, field="state_json")
    unknown = sorted(set(document) - set(SLOTS))
    if unknown:
        raise argument_error(
            op,
            f"state_json has slots no envelope has: {', '.join(unknown)}.",
            hint=f"An envelope has {', '.join(SLOTS)} and nothing else.",
        )
    name = document.get("environment")
    if not isinstance(name, str) or name not in ENVIRONMENTS:
        raise argument_error(
            op,
            "state_json.environment is not an environment the SDK reaches.",
            hint=f"Send environment as one of: {', '.join(ENVIRONMENTS)}.",
        )
    envelope: dict[str, object] = {slot: document.get(slot) for slot in SLOTS}
    for slot, model in _SESSION_SLOTS.items():
        if envelope[slot] is not None:
            _ = read_state(op, slot, envelope[slot], model)
    handle = envelope["handle"]
    if handle is not None and op.partition(".")[0] in _HANDLES:
        _read_handle(op, handle)
    return envelope


def read_state(op: str, slot: str, raw: object, model: type[_StateT]) -> _StateT:
    """Read one slot of the envelope as the state it names.

    Args:
        op: The operation the state belongs to.
        slot: The slot being read, for the message.
        raw: The JSON value in that slot.
        model: The state model that slot holds.

    Returns:
        The state.

    Raises:
        KSeFArgumentError: The value is not that state.
    """
    try:
        return model.model_validate(
            decode_base64(raw, bytes_plan(model), op=op, where=f"state_json.{slot}")
        )
    except ValidationError as exc:
        raise describe_validation(
            op, f"state_json.{slot}", exc, expected=model.__name__
        ) from exc


def _read_handle(op: str, handle: object) -> None:
    """Check the handle slot against the state the operation continues.

    The kind of handle an operation continues is part of the manifest, so an envelope
    does not have to name it, and a binding cannot send a batch session handle to an
    export.

    Args:
        op: The operation the state belongs to.
        handle: The JSON value in the handle slot.

    Raises:
        KSeFArgumentError: This operation continues no handle, or the value is not the
            state this operation continues.
    """
    operation = lookup(op)
    expected = None if operation is None else operation.state_model
    if expected is None or operation is None or operation.prefix not in _HANDLES:
        raise argument_error(
            op,
            "state_json carries a handle, and this operation does not continue one.",
            hint="Send handle only for an operation that continues a handle.",
        )
    _ = read_state(op, "handle", handle, expected)


def read_arguments(
    operation: Operation, args_json: str | None
) -> tuple[dict[str, object], str | None]:
    """Validate the arguments of one call.

    Args:
        operation: The operation being called.
        args_json: The arguments as JSON text.

    Returns:
        The arguments to pass by keyword, and the cursor for a page.

    Raises:
        KSeFArgumentError: The document is absent, is not JSON, is not an object,
            omits a required argument, names one the operation does not take, gives a
            cursor that is neither text nor null, or gives an argument a value its own
            schema rejects.
    """
    op = operation.id
    document = read_json_object(op, args_json, field="args_json")
    unknown = sorted(set(document) - operation.names)
    if unknown:
        raise argument_error(
            op,
            f"args_json names arguments this operation does not take: {', '.join(unknown)}.",
            hint="Compare the call with that operation's parameters in ksef2.bridge.manifest().",
        )
    missing = sorted(operation.required - set(document))
    if missing:
        raise argument_error(
            op,
            f"args_json leaves out arguments this operation requires: {', '.join(missing)}.",
            hint="Send every parameter the manifest marks required.",
        )
    arguments: dict[str, object] = {}
    for parameter in operation.parameters:
        if parameter.name not in document:
            continue
        try:
            checked = parameter.validator.validate_python(
                decode_base64(
                    document[parameter.name],
                    parameter.plan,
                    op=op,
                    where=parameter.name,
                )
            )
        except ValidationError as exc:
            raise describe_validation(op, parameter.name, exc) from exc
        arguments[parameter.name] = checked
    return arguments, _read_cursor(operation, document)


def _read_cursor(operation: Operation, document: dict[str, object]) -> str | None:
    """Return the cursor a page was asked for.

    Args:
        operation: The operation being called.
        document: The decoded arguments.

    Returns:
        The cursor, or ``None`` for the first page.

    Raises:
        KSeFArgumentError: The cursor is neither text nor null. An operation that
            pages no more than this refuses it as an argument it does not take.
    """
    if CURSOR not in document:
        return None
    raw = document[CURSOR]
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise argument_error(
            operation.id,
            "the cursor argument is neither a string nor null.",
            hint="Send the next_cursor of the previous page, or null for the first page.",
        )
    return raw


def invoke(
    operation: Operation,
    receiver: object,
    arguments: dict[str, object],
    cursor: str | None,
) -> object:
    """Call one member, and take a page when the operation pages.

    Args:
        operation: The operation being called.
        receiver: The object that carries the member.
        arguments: The validated arguments, passed by keyword.
        cursor: The cursor of the page asked for, ``None`` for the first.

    Returns:
        Whatever the member returned, with a collection reduced to one page.
    """
    member = cast("object", getattr(receiver, operation.member))
    value: object = (
        member
        if operation.attribute
        else cast("Callable[..., object]", member)(**arguments)
    )
    if isinstance(value, Pager):
        return cast("Pager[object]", value).page(cursor)
    return value


def encode_result(op: str, value: object) -> object:
    """Turn one result into JSON data.

    A handle writes the state that rebuilds it, because that is the form the caller
    can keep and send back. A generated token is the one result written by hand, since
    the credential it carries is shown once and is not part of that state.

    Args:
        op: The operation the value came from, used only in messages.
        value: Whatever the member returned.

    Returns:
        Data ``json.dumps`` writes unchanged.

    Raises:
        TypeError: The value has no JSON form, which means the dispatcher met a result
            the manifest does not describe.
    """
    if isinstance(value, GeneratedToken):
        return {"state": dump_state(value.resume_state()), "token": _token_of(value)}
    saved = saved_form(value)
    if isinstance(saved, BaseModel):
        return dump_state(saved)
    return encode(op, value)


def updated(envelope: dict[str, object], value: object) -> dict[str, object]:
    """Return the state envelope after one result.

    Args:
        envelope: The envelope the call was made with.
        value: The result it produced.

    Returns:
        A copy of the envelope with the slot the result fills written out, or the
        envelope unchanged when the result carries no state to save.
    """
    if isinstance(value, GeneratedToken):
        # Its own state is the handle; the credential beside it is shown once and
        # is deliberately not part of what a later call rebuilds.
        return _write(envelope, "handle", dump_state(value.resume_state()))
    saved = saved_form(value)
    slot = None if saved is None else _slot_of(type(saved))
    if saved is None or slot is None:
        return dict(envelope)
    return _write(envelope, slot, dump_state(cast("BaseModel", saved)))


def _write(
    envelope: dict[str, object], slot: str, data: dict[str, object]
) -> dict[str, object]:
    """Return the envelope with one slot written out.

    Args:
        envelope: The envelope the call was made with.
        slot: The slot the result fills.
        data: The state to leave there.

    Returns:
        A copy of the envelope holding that state in that slot.
    """
    written = dict(envelope)
    written[slot] = data
    return written


def saved_form(value: object) -> object | None:
    """Return the portable state a result carries, when it carries one.

    A handle that holds live keys or a one-time credential does not travel as an
    object: its saved form is what an envelope holds and what the next call rebuilds
    the handle from.

    Args:
        value: The result to inspect.

    Returns:
        A state model, or ``None`` when the result is neither a state nor a handle.
    """
    if isinstance(value, BaseModel):
        return value
    attribute = _SAVED_FORM.get(type(value))
    if attribute is None:
        return None
    return cast("typing.Callable[[], object]", getattr(value, attribute))()


def _slot_of(kind: type[object]) -> str | None:
    """Return the envelope slot that holds one kind of state.

    Args:
        kind: The class of the state.

    Returns:
        The slot name, or ``None`` when no slot holds that kind of state.
    """
    for cls in kind.__mro__:
        state = cast("type[BaseModel]", cls)
        slot = _SESSION_SLOT_BY_CLASS.get(state)
        if slot is not None:
            return slot
        if state in _HANDLE_STATES:
            return "handle"
    return None


def _token_of(token: GeneratedToken) -> str | None:
    """Return the one-time credential of a generated token, if it still holds one.

    A handle rebuilt from saved state cannot recover that credential: KSeF shows it
    once. The result says so with ``null`` instead of failing the call.

    Args:
        token: The handle to read.

    Returns:
        The credential, or ``None`` when the handle no longer holds it.
    """
    value = getattr(token, _GENERATED_TOKEN, None)
    return value if isinstance(value, str) else None


_RESOLVERS: Final[dict[str, Callable[[_Scope], object]]] = {
    "client": lambda scope: scope.client(),
    "temporal_testdata": lambda scope: scope.client().testdata.temporal(),
    **{
        prefix: (lambda scope, a=accessor: cast("object", getattr(scope.client(), a)))
        for prefix, accessor in _UNAUTHENTICATED.items()
    },
    "authenticated": lambda scope: scope.authenticated(),
    **{
        prefix: (
            lambda scope, a=accessor: cast("object", getattr(scope.authenticated(), a))
        )
        for prefix, accessor in _AUTHENTICATED.items()
    },
    "online": lambda scope: scope.online(),
    "batch": lambda scope: scope.batch(),
    "generated_token": lambda scope: scope.authenticated().tokens.generation(
        state=scope.handle(GeneratedTokenResumeState)
    ),
    "certificate_enrollment": lambda scope: (
        scope.authenticated().certificates.enrollment(
            state=scope.handle(CertificateEnrollmentResumeState)
        )
    ),
    "permission_operation": lambda scope: scope.authenticated().permissions.operation(
        state=scope.handle(PermissionOperationResumeState)
    ),
    "invoice_submission": lambda scope: scope.online().submission(
        state=scope.handle(InvoiceSubmissionResumeState)
    ),
    "export_job": lambda scope: scope.authenticated().invoices.export(
        state=scope.handle(ExportResumeState)
    ),
    "exported_invoices": lambda scope: ExportedInvoices.from_model(
        scope.handle(ExportedInvoicesData)
    ),
}
"""The receiver resolver for each published prefix."""


def _receiver(operation: Operation, scope: _Scope) -> object:
    """Return the object one operation is called on.

    Args:
        operation: The operation being called.
        scope: The call, which resumes whatever the receiver needs.

    Returns:
        The client, session or handle that carries the member.

    Raises:
        KSeFArgumentError: The state does not rebuild that receiver.
        RuntimeError: The dispatcher has no resolver for a published prefix.
    """
    prefix = operation.prefix
    if operation.constructor:
        return cast("object", class_of(prefix))
    resolver = _RESOLVERS.get(prefix)
    if resolver is None:
        raise RuntimeError(f"the dispatcher has no receiver for {prefix!r}")
    return resolver(scope)
