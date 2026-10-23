"""JSON-compatible data helpers used to build the manifest.

The manifest is plain data: ``None``, ``bool``, ``int``, ``float``, ``str``,
lists and dictionaries. Every value in it survives ``json.dumps`` unchanged, so
a binding generator never receives a Python object it cannot serialize.
"""

import math
import re
from collections.abc import Iterable, Mapping
from typing import cast

from ksef2._core import exceptions

type JsonValue = object
"""Any JSON value. The manifest keeps its values opaque on purpose: a nested
dictionary is data, whatever its declared value type happens to be."""

type JsonObject = dict[str, object]
"""A JSON object, the shape of every manifest section and every schema."""

BYTES_CONTENT_ENCODING = "base64"
"""Encoding the manifest announces for Python ``bytes`` values."""

_ARGUMENT_RE = re.compile(r"^\*{0,2}(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$")
_SECTION_RE = re.compile(
    r"^(\s*)(Args|Arguments|Returns|Yields|Raises|Example|Examples|Note|Attributes):"
    r"\s*$"
)


def _unsupported(value: object, expected: str) -> exceptions.KSeFException:
    """Build the error that names the value the manifest cannot carry.

    Args:
        value: Value found where the manifest expected plain JSON data.
        expected: Shape the builder wanted.

    Returns:
        The error to raise.
    """
    return exceptions.KSeFException(
        "The bridge manifest cannot carry a value that is not JSON data.",
        hint=f"Give {type(value).__name__} a JSON-compatible form ({expected}).",
        value_type=type(value).__name__,
        expected=expected,
    )


def require_json(value: object) -> JsonValue:
    """Return ``value`` after checking that the manifest may carry it.

    Args:
        value: Value produced by pydantic or by the manifest builder.

    Returns:
        ``value`` itself for a scalar, an object or a list, or the list a tuple
        stands for. Every returned value is data ``json.dumps`` writes as is.

    Raises:
        KSeFException: If ``value`` is not one of the JSON data types, is a
            number JSON has no text for, or is an unordered collection.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise _unsupported(value, "a finite number")
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        # A tuple default is one JSON array; a set has no order to write it in,
        # so it is refused below rather than emitted in an arbitrary order.
        items = cast("Iterable[object]", value)
        return [require_json(item) for item in items]
    if isinstance(value, dict):
        for key, item in cast("Mapping[object, object]", value).items():
            if not isinstance(key, str):
                raise _unsupported(key, "an object key that is a string")
            _ = require_json(item)
        return cast("JsonValue", value)
    raise _unsupported(value, "a scalar, a list or an object")


def as_object(value: object) -> JsonObject:
    """Return ``value`` as a JSON object.

    Args:
        value: Value read from pydantic or from a manifest section.

    Returns:
        The same value as a dictionary keyed by strings.

    Raises:
        KSeFException: If ``value`` is not a JSON object.
    """
    if isinstance(value, dict):
        result: JsonObject = {}
        for key, item in cast("Mapping[object, object]", value).items():
            if not isinstance(key, str):
                raise _unsupported(key, "an object key that is a string")
            result[key] = item
        return result
    raise _unsupported(value, "an object")


def as_list(value: object) -> list[object]:
    """Return ``value`` as a list.

    Args:
        value: Value read from a manifest section.

    Returns:
        The same value as a list.

    Raises:
        KSeFException: If ``value`` is not a list.
    """
    if isinstance(value, list):
        return cast("list[object]", value)
    raise _unsupported(value, "a list")


def encode_bytes_schemas(value: object) -> JsonValue:
    """Replace pydantic's binary strings with base64 string schemas.

    ``bytes`` is not JSON data, so the manifest transports it as a base64
    encoded string. Pydantic writes ``{"type": "string", "format": "binary"}``
    for those values; this rewrites every such schema in a copy, keeping sibling
    keywords such as ``description``.

    Args:
        value: Schema or schema subtree to rewrite.

    Returns:
        The same subtree with binary string annotations replaced.
    """
    if isinstance(value, dict):
        entries = cast("Mapping[str, object]", value)
        result: JsonObject = {key: item for key, item in entries.items()}
        if result.get("type") == "string" and result.get("format") == "binary":
            _ = result.pop("format")
            result["contentEncoding"] = BYTES_CONTENT_ENCODING
        for key, item in list(result.items()):
            result[key] = encode_bytes_schemas(item)
        return result
    if isinstance(value, list):
        return [encode_bytes_schemas(item) for item in cast("list[object]", value)]
    return value


def collect_refs(value: object, destination: set[str]) -> set[str]:
    """Collect every ``$ref`` pointer used below ``value``.

    Args:
        value: Schema or schema subtree to walk.
        destination: Set the pointers are added to.

    Returns:
        The same set, for chaining.
    """
    if isinstance(value, dict):
        entries = cast("Mapping[str, object]", value)
        reference = entries.get("$ref")
        if isinstance(reference, str):
            _ = destination.add(reference)
        for item in entries.values():
            _ = collect_refs(item, destination)
    elif isinstance(value, list):
        for item in cast("list[object]", value):
            _ = collect_refs(item, destination)
    return destination


def without_titles(value: object) -> JsonValue:
    """Return ``value`` without the labels pydantic gives each schema.

    pydantic labels every model and every field with a prettified ``title``, such
    as ``"Reference Number"`` for ``reference_number``. The manifest names its
    types through ``$defs`` and its fields through the property keys, so those
    labels repeat what the document already says.

    Args:
        value: Schema or schema subtree to clean.

    Returns:
        The same data with every ``title`` entry removed.

    Raises:
        KSeFException: If the value holds something that is not JSON data.
    """
    data = require_json(value)
    if isinstance(data, dict):
        entries = cast("dict[str, object]", data)
        _ = entries.pop("title", None)
        for key in list(entries):
            entries[key] = without_titles(entries[key])
        return entries
    if isinstance(data, list):
        items = cast("list[object]", data)
        for index, item in enumerate(items):
            items[index] = without_titles(item)
        return items
    return data


def first_summary(docstring: str | None) -> str:
    """Return the one-line summary of a docstring.

    Args:
        docstring: Docstring of a class, method or property, or ``None``.

    Returns:
        Its first non-empty line; empty when there is no docstring.
    """
    if not docstring:
        return ""
    for line in docstring.strip().splitlines():
        text = line.strip()
        if text:
            return text
    return ""


def argument_descriptions(docstring: str | None) -> dict[str, str]:
    """Return the ``Args`` descriptions of a Google-style docstring.

    Only the argument section is read, and each entry is joined into one line so
    a generated signature stays readable. The docstring gate in
    ``tests/unit/test_public_docstrings.py`` keeps those sections complete.

    Args:
        docstring: Docstring of a method, or ``None``.

    Returns:
        Descriptions keyed by parameter name; empty when there is no ``Args``
        section.
    """
    if not docstring:
        return {}
    descriptions: dict[str, str] = {}
    indent: int | None = None
    for line in docstring.expandtabs().splitlines():
        stripped = line.strip()
        if indent is None:
            section = _SECTION_RE.match(line)
            if section is not None and section.group(2) in ("Args", "Arguments"):
                indent = len(section.group(1))
            continue
        if not stripped:
            continue
        if len(line) - len(line.lstrip()) <= indent:
            break
        match = _ARGUMENT_RE.match(stripped)
        if match is None:
            break
        descriptions[match.group(1)] = " ".join(match.group(2).split())
    return descriptions
