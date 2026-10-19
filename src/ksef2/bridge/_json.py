"""Plain JSON in and out of the dispatcher, without carrying secrets.

Three jobs live here. A JSON document is read and checked for being an object. A
Python result is written as JSON data. A failure is written as the one error
object a binding branches on.

Nothing a caller sent is ever repeated back in a message. Pydantic quotes the value
it rejected, and an argument can be a private key, so the descriptions built here
name the parameter and the kind of error, which is what a caller needs in order to
fix the call. Request details stay out of the error object too: an ``httpx``
exception can name a presigned URL, and a response body can hold anything.
"""

import base64
import datetime
import decimal
import enum
import inspect
import json
import pathlib
import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Final, cast

from pydantic import (
    BaseModel,
    PydanticSchemaGenerationError,
    SecretBytes,
    SecretStr,
    TypeAdapter,
    ValidationError,
)
from pydantic_core import PydanticSerializationError

from ksef2._core.exceptions import KSeFApiError, KSeFArgumentError
from ksef2.bridge._bytes import bytes_plan
from ksef2.bridge._codec import encode_base64 as encode_model_base64

ARGUMENT_ERROR: Final = "ARGUMENT_ERROR"
"""The code of an argument, state or cursor the dispatcher cannot use."""

UNKNOWN_OPERATION: Final = "UNKNOWN_OPERATION"
"""The code of an id the manifest does not report as an operation."""

VALIDATION_ERROR: Final = "VALIDATION_ERROR"
"""The code of a ``ValidationError`` that reaches the boundary from inside the SDK."""

SDK_ERROR: Final = "SDK_ERROR"
"""The code of a failure that carries no code of its own."""

#: Names whose values are credentials, keys, payloads or presigned URLs. A context
#: entry under any of them is dropped from the error JSON at every depth, so a
#: failure cannot smuggle one into a log the binding writes from it.
SECRET_NAMES: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "aes_key",
        "authorization",
        "cert",
        "cert_pem",
        "content",
        "cookies",
        "credentials",
        "encrypted_key",
        "headers",
        "iv",
        "key",
        "key_password",
        "key_pem",
        "part_upload_requests",
        "password",
        "payload",
        "presigned_url",
        "private_key",
        "refresh_token",
        "secret",
        "token",
        "url",
    }
)


def argument_error(
    op: str, problem: str, *, hint: str | None = None
) -> KSeFArgumentError:
    """Build the error for a document the dispatcher cannot use.

    The dispatcher reports its own stable code rather than the class default, so a
    binding that never looks at a message can still tell an unusable argument from an
    unknown operation. The error type stays ``KSeFArgumentError`` either way: the call
    is wrong in the same way, and one exception says it.

    Args:
        op: The operation the caller asked for.
        problem: What is wrong, in one sentence. Names only, never a value.
        hint: The next step, or ``None`` when there is nothing to suggest.

    Returns:
        The error, with *problem* as its message and *hint* as its hint.
    """
    return dispatcher_error(op, ARGUMENT_ERROR, problem, hint=hint)


def dispatcher_error(
    op: str, code: str, problem: str, *, hint: str | None = None
) -> KSeFArgumentError:
    """Build a rejected call that reports one of the dispatcher's own codes.

    ``KSeFArgumentError.code`` is the code of the class, and every code here says the
    same thing about the call: it was wrong before the SDK could use it. The code is
    replaced on the instance, so the class default never reaches a binding for these.

    Args:
        op: The operation the caller asked for.
        code: The code to report.
        problem: What is wrong, in one sentence. Names only, never a value.
        hint: The next step, or ``None`` when there is nothing to suggest.

    Returns:
        The error, reporting *code* as its code.
    """
    error = KSeFArgumentError(f"{op}: {problem}", hint=hint)
    error.code = code
    error.context["code"] = code
    return error


def unknown_operation(op: str, reason: str | None = None) -> KSeFArgumentError:
    """Build the error for an unknown or deliberately excluded id.

    Args:
        op: The id the caller asked for.
        reason: The manifest's exclusion reason, when it lists this id.

    Returns:
        The error, whose hint points at the manifest.
    """
    return dispatcher_error(
        op,
        UNKNOWN_OPERATION,
        (
            "no operation carries this id."
            if reason is None
            else f"this operation is listed in the manifest's excluded members: {reason}"
        ),
        hint="Read ksef2.bridge.manifest() for the ids, their arguments and their state.",
    )


def read_json_object(op: str, text: str | None, *, field: str) -> dict[str, object]:
    """Read one JSON document that has to be an object.

    Args:
        op: The operation the document belongs to, used only in messages.
        text: The document as JSON text, or ``None``.
        field: The name of the document, ``args_json`` or ``state_json``.

    Returns:
        The decoded object.

    Raises:
        KSeFArgumentError: The document is absent, is not JSON, or is JSON that is not
            an object.
    """
    if text is None:
        raise argument_error(
            op, f"{field} is missing.", hint=f"Send {field} as a JSON object."
        )
    try:
        decoded = cast("object", json.loads(text))
    except json.JSONDecodeError as exc:
        raise argument_error(
            op,
            f"{field} is not valid JSON, at line {exc.lineno} column {exc.colno}.",
            hint=f"Send {field} as one JSON object built from that operation's schema.",
        ) from exc
    if not isinstance(decoded, dict):
        raised = type(decoded).__name__
        raise argument_error(
            op,
            f"{field} is {raised}, not a JSON object.",
            hint=f"Send {field} as a JSON object.",
        )
    return cast("dict[str, object]", decoded)


def describe_validation(
    op: str,
    field: str,
    error: ValidationError,
    *,
    expected: str | None = None,
) -> KSeFArgumentError:
    """Turn a ``ValidationError`` into an argument error that quotes no input.

    Args:
        op: The operation the value belongs to.
        field: What was being read, an argument name or a state slot.
        error: The failure Pydantic reported.
        expected: The state that belongs in a state slot, when one was being read.
            Naming the class is the shortest way to say what the slot has to hold.

    Returns:
        The error to raise, naming each rejected location and its error kind.
    """
    parts: list[str] = []
    for entry in error.errors(include_url=False, include_context=False):
        location = ".".join(str(part) for part in entry["loc"])
        parts.append(f"{field}.{location}" if location else field)
        parts[-1] = f"{parts[-1]} is not valid ({entry['type']})"
    listed = ", ".join(dict.fromkeys(parts))
    hint = (
        f"Send back the {expected} the previous call returned, unchanged."
        if expected is not None
        else "Compare the call with that operation's schemas in ksef2.bridge.manifest()."
    )
    return argument_error(op, f"{listed} for this operation.", hint=hint)


def encode_base64(value: bytes) -> str:
    """Write bytes the way the manifest describes them.

    Args:
        value: The bytes to write.

    Returns:
        Standard Base64 text, ``=`` padding included.
    """
    return base64.b64encode(value).decode("ascii")


def dump_state(state: BaseModel, *, sensitive: bool = True) -> dict[str, object]:
    """Write a saved state as the JSON the next call reads back.

    ``model_dump()`` keeps a bearer token and a session key redacted, which is right
    for a log and useless for state that has to work again, so a persisted model goes
    through its own ``to_dict()`` or ``to_sensitive_dict()``. These deliberate exports
    also preserve package part URLs that generic dumps omit, so an export handle can
    be rebuilt. This envelope holds credential material.

    Args:
        state: The state to write.
        sensitive: Use deliberate credential exports rather than a redacted dump.

    Returns:
        JSON data holding the fields of that state.
    """
    data = _export_model(state, sensitive=sensitive)
    return cast(
        "dict[str, object]", encode_model_base64(data, state, bytes_plan(type(state)))
    )


def _export_model(state: BaseModel, *, sensitive: bool) -> dict[str, object]:
    """Select the model's deliberate export, or its redacted JSON dump."""
    if sensitive:
        to_dict = getattr(state, "to_dict", None)
        if callable(to_dict):
            return cast("dict[str, object]", to_dict(mode="json"))
        to_sensitive_dict = getattr(state, "to_sensitive_dict", None)
        if callable(to_sensitive_dict):
            if "mode" in inspect.signature(to_sensitive_dict).parameters:
                return cast("dict[str, object]", to_sensitive_dict(mode="json"))
            return cast("dict[str, object]", to_sensitive_dict())
    return cast("dict[str, object]", state.model_dump(mode="json"))


def as_bytes(value: object) -> bytes | None:
    """Return the bytes one value holds, whatever buffer type it used.

    Args:
        value: The value to read.

    Returns:
        Its bytes, or ``None`` when it holds none.
    """
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return None


_SCALAR_ADAPTERS = dict[type[object], TypeAdapter[object]]()


def encode(op: str, value: object) -> object:
    """Turn one Python result into JSON data.

    Args:
        op: The operation the value came from, used only in messages.
        value: Whatever the member returned.

    Returns:
        Data ``json.dumps`` writes unchanged.

    Raises:
        TypeError: The value has no JSON form, which means the dispatcher met a result
            the manifest does not describe.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if (raw := as_bytes(value)) is not None:
        return encode_base64(raw)
    if isinstance(value, SecretStr | SecretBytes):
        return encode(op, cast("object", value.get_secret_value()))
    if isinstance(value, BaseModel):
        return dump_state(value)
    if isinstance(value, Mapping):
        items = cast("Mapping[object, object]", value).items()
        return {str(key): encode(op, item) for key, item in items}
    if isinstance(value, Sequence | Iterable):
        return [encode(op, item) for item in cast("Iterable[object]", value)]
    try:
        cls = type(value)
        adapter = _SCALAR_ADAPTERS.get(cls)
        if adapter is None:
            adapter = TypeAdapter(cls)
            _SCALAR_ADAPTERS[cls] = adapter
        return cast("object", adapter.dump_python(value, mode="json"))
    except (PydanticSchemaGenerationError, PydanticSerializationError):
        raise TypeError(
            f"{op} returned a {type(value).__name__}, which has no JSON form"
        ) from None


def state_data(model: BaseModel) -> dict[str, object]:
    """Write error-context models with secrets still redacted."""
    return dump_state(model, sensitive=False)


def error_of(exc: BaseException) -> dict[str, object]:
    """Build the error object one failed call reports.

    The response body, the ``httpx`` exception behind a transport failure and
    everything the caller sent stay out of it. A context entry whose name is a known
    secret is dropped, and bytes are never written out.

    Args:
        exc: The failure to report.

    Returns:
        A JSON object with ``type``, ``code``, ``message``, ``hint`` and ``context``,
        plus the KSeF fields when the failure came back from the API.
    """
    error: dict[str, object] = {
        "type": type(exc).__name__,
        "code": _code_of(exc),
        "message": _message_of(exc),
        "hint": getattr(exc, "hint", None),
        "context": cast("dict[str, object]", _plain(_context_of(exc))),
    }
    if isinstance(exc, KSeFApiError):
        error["status_code"] = exc.status_code
        error["ksef_code"] = exc.ksef_code
        error["trace_id"] = exc.trace_id
        error["details"] = [_plain(detail) for detail in exc.details]
        error["exception_code"] = {
            "name": exc.exception_code.name,
            "value": int(exc.exception_code),
        }
    return error


def _code_of(exc: BaseException) -> str:
    """Return the stable code of one failure.

    Args:
        exc: The failure.

    Returns:
        The code its class carries, or the code of the family it belongs to when it
        carries none.
    """
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    if isinstance(exc, ValidationError):
        return VALIDATION_ERROR
    if isinstance(exc, json.JSONDecodeError):
        return ARGUMENT_ERROR
    return SDK_ERROR


def _message_of(exc: BaseException) -> str:
    """Return the message of one failure, without its hint line or its arguments.

    Args:
        exc: The failure.

    Returns:
        The message the exception was built with.
    """
    if isinstance(exc, ValidationError):
        locations = [
            ".".join(str(part) for part in entry["loc"])
            for entry in exc.errors(include_url=False, include_context=False)
        ]
        named = ", ".join(dict.fromkeys(location for location in locations if location))
        return (
            f"a KSeF response did not match the SDK models at {named}"
            if named
            else ("a KSeF response did not match the SDK models")
        )
    first = exc.args[0] if exc.args else None
    return first if isinstance(first, str) else type(exc).__name__


def _context_of(exc: BaseException) -> dict[str, object]:
    """Return the structured context of one failure.

    Args:
        exc: The failure.

    Returns:
        The context the SDK recorded, empty when there is none.
    """
    context = getattr(exc, "context", None)
    if isinstance(context, Mapping):
        items = cast("Mapping[object, object]", context)
        return {str(key): item for key, item in items.items()}
    return {}


def _plain(value: object) -> object:
    """Reduce one value to JSON data, dropping anything a secret could hide in.

    Args:
        value: The value to reduce.

    Returns:
        Data ``json.dumps`` writes: scalars, lists of them and objects of them. Bytes
        and anything the SDK keeps secret become nothing at all rather than a value.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Mapping):
        kept: dict[str, object] = {}
        for key, item in cast("Mapping[object, object]", value).items():
            if str(key).lower() in SECRET_NAMES:
                continue
            kept[str(key)] = _plain(item)
        return kept
    if isinstance(value, BaseModel):
        return _plain(state_data(value))
    if isinstance(value, enum.Enum):
        return _plain(cast("object", value.value))
    if as_bytes(value) is not None or isinstance(value, SecretStr | SecretBytes):
        return None
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, uuid.UUID | pathlib.PurePath):
        return str(value)
    if isinstance(value, Iterable):
        return [_plain(item) for item in value]
    return type(value).__name__
