"""Shared bytes analysis for manifest schemas and bridge value conversion."""

from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path, PosixPath, PurePath, PureWindowsPath
from typing import Annotated, TypeVar, get_args, get_origin

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretBytes
from pydantic.alias_generators import to_camel

from ksef2.bridge._bytes import (
    BYTES,
    FieldsPlan,
    ItemsPlan,
    UnionPlan,
    ValuesPlan,
    bytes_plan,
    without_text_alternative,
)
from ksef2.bridge._errors import ManifestError
from ksef2.bridge._schemas import SchemaBuilder
from ksef2.models import BatchInvoice, ExportedInvoicesData, PreparedBatch
from ksef2.xades import XAdESCredentials

type PayloadAlias = list[bytes]
type BytesAlternatives = bytes | list[bytes]


@pytest.mark.parametrize("annotation", [bytes, bytearray, SecretBytes, bytes | None])
def test_bytes_leaves(annotation: object) -> None:
    assert bytes_plan(annotation) is BYTES


@pytest.mark.parametrize("annotation", [str, int, TypeVar("T")])
def test_annotations_without_bytes(annotation: object) -> None:
    assert bytes_plan(annotation) is None


@pytest.mark.parametrize(
    "annotation",
    [
        list[bytes],
        set[bytes],
        frozenset[bytes],
        Sequence[bytes],
        Iterable[bytes],
        Collection[bytes],
    ],
)
def test_items(annotation: object) -> None:
    assert bytes_plan(annotation) == ItemsPlan(BYTES)


@pytest.mark.parametrize("annotation", [dict[str, bytes], Mapping[str, bytes]])
def test_mapping_values(annotation: object) -> None:
    assert bytes_plan(annotation) == ValuesPlan(BYTES)


def test_mapping_keys_do_not_hold_bytes() -> None:
    assert bytes_plan(dict[bytes, str]) is None


@pytest.mark.parametrize("annotation", [tuple[bytes, ...], tuple[bytes, bytes]])
def test_tuple_items(annotation: object) -> None:
    assert bytes_plan(annotation) == ItemsPlan(BYTES)


def test_fixed_tuple_requires_a_shared_plan() -> None:
    assert bytes_plan(tuple[bytes, str]) is None


def test_sdk_models_include_excluded_fields() -> None:
    assert bytes_plan(XAdESCredentials) == FieldsPlan(
        {"cert_pem": BYTES, "key_pem": BYTES}
    )
    assert bytes_plan(ExportedInvoicesData) == FieldsPlan({"archive": BYTES})
    assert bytes_plan(BatchInvoice) == FieldsPlan({"content": BYTES})
    assert bytes_plan(PreparedBatch) == FieldsPlan(
        {"parts": ItemsPlan(FieldsPlan({"content": BYTES}))}
    )


def test_union_uses_distinct_json_shapes() -> None:
    assert bytes_plan(list[BatchInvoice | bytes]) == ItemsPlan(
        UnionPlan((FieldsPlan({"content": BYTES}), BYTES))
    )
    assert bytes_plan(bytes | list[bytes] | dict[str, bytes]) == UnionPlan(
        (BYTES, ItemsPlan(BYTES), ValuesPlan(BYTES))
    )


@pytest.mark.parametrize(
    "annotation",
    [
        BatchInvoice | XAdESCredentials,
        bytes | SecretBytes,
        bytes | bytearray,
        list[bytes] | set[bytes],
        BatchInvoice | dict[str, bytes],
    ],
)
def test_union_rejects_ambiguous_json_shapes(annotation: object) -> None:
    with pytest.raises(ManifestError) as raised:
        _ = bytes_plan(annotation)
    assert repr(annotation) in str(raised.value)


def test_aliased_union_shapes_are_checked_together() -> None:
    assert bytes_plan(BytesAlternatives | BatchInvoice) == UnionPlan(
        (BYTES, ItemsPlan(BYTES), FieldsPlan({"content": BYTES}))
    )
    with pytest.raises(ManifestError, match="BytesAlternatives"):
        _ = bytes_plan(BytesAlternatives | bytearray)


def test_recursive_model_terminates_and_does_not_poison_cached_plans() -> None:
    class Node(BaseModel):
        content: bytes
        children: list["Node"] = Field(default_factory=list)

    assert bytes_plan(Node) == FieldsPlan({"content": BYTES})
    assert bytes_plan(list[Node]) == ItemsPlan(FieldsPlan({"content": BYTES}))


def test_models_without_bytes_have_no_plan() -> None:
    class Text(BaseModel):
        value: str
        child: "Text | None" = None

    assert bytes_plan(Text) is None


def test_aliases_and_annotated_metadata() -> None:
    assert bytes_plan(PayloadAlias) == ItemsPlan(BYTES)
    assert bytes_plan(Annotated[PayloadAlias, "metadata"]) == ItemsPlan(BYTES)
    annotation = Annotated[bytes, {"unhashable": []}]
    assert bytes_plan(annotation) is BYTES
    assert bytes_plan(annotation) is BYTES
    assert bytes_plan(XAdESCredentials) is bytes_plan(XAdESCredentials)


def test_without_text_alternative() -> None:
    assert without_text_alternative(bytes | str) is bytes
    assert without_text_alternative(str | bytes | None) == bytes | None
    assert without_text_alternative(bytearray | str) is bytearray


def test_without_text_alternative_inside_containers() -> None:
    annotation = Iterable[bytes | str | Path | BatchInvoice]
    narrowed = without_text_alternative(annotation)
    assert get_origin(narrowed) is Iterable
    assert get_args(narrowed) == (bytes | BatchInvoice,)
    assert (
        without_text_alternative(dict[str, list[bytes | str]]) == dict[str, list[bytes]]
    )


@pytest.mark.parametrize("path", [Path, PurePath, PosixPath, PureWindowsPath])
def test_without_path_alternatives(path: type[PurePath]) -> None:
    assert without_text_alternative(bytes | path | str) is bytes


@pytest.mark.parametrize("annotation", [list[str], str | None, int | str, Path | str])
def test_without_changes_preserves_identity(annotation: object) -> None:
    assert without_text_alternative(annotation) is annotation


def test_without_text_alternative_keeps_annotated_metadata() -> None:
    metadata: dict[str, list[object]] = {"keep": []}
    annotation = Annotated[list[bytes | str], metadata]
    narrowed = without_text_alternative(annotation)
    assert get_args(narrowed)[0] == list[bytes]
    assert get_args(narrowed)[1] is metadata
    unchanged = Annotated[list[str], metadata]
    assert without_text_alternative(unchanged) is unchanged


def test_schema_builder_rewrites_nested_bytes_and_preserves_metadata() -> None:
    class Payload(BaseModel):
        content: bytes = Field(
            default=b"", title="Payload bytes", description="Binary input"
        )
        password: SecretBytes
        optional: bytes | None
        items: list[bytes]
        values: dict[str, bytes]
        pair: tuple[bytes, bytes]
        either: bytes | list[bytes]
        text: str

    builder = SchemaBuilder()
    _ = builder.model_ref(Payload)
    properties = builder.defs["Payload"]["properties"]
    assert isinstance(properties, dict)
    assert properties["content"] == {
        "type": "string",
        "contentEncoding": "base64",
        "title": "Payload bytes",
        "description": "Binary input",
        "default": "",
    }
    assert properties["password"] == {
        "type": "string",
        "contentEncoding": "base64",
        "title": "Password",
        "writeOnly": True,
    }
    assert properties["optional"] == {
        "anyOf": [
            {"type": "string", "contentEncoding": "base64"},
            {"type": "null"},
        ],
        "title": "Optional",
    }
    assert properties["items"] == {
        "type": "array",
        "items": {"type": "string", "contentEncoding": "base64"},
        "title": "Items",
    }
    assert properties["values"] == {
        "type": "object",
        "additionalProperties": {"type": "string", "contentEncoding": "base64"},
        "title": "Values",
    }
    assert properties["pair"]["prefixItems"] == [
        {"type": "string", "contentEncoding": "base64"},
        {"type": "string", "contentEncoding": "base64"},
    ]
    assert properties["either"] == {
        "anyOf": [
            {"type": "string", "contentEncoding": "base64"},
            {"type": "array", "items": {"type": "string", "contentEncoding": "base64"}},
        ],
        "title": "Either",
    }
    assert properties["text"] == {"type": "string", "title": "Text"}


def test_schema_builder_uses_aliases_in_nested_model_definitions() -> None:
    class Aliased(BaseModel):
        model_config = ConfigDict(alias_generator=to_camel)
        some_bytes: bytes
        other_bytes: bytes = Field(alias="payload")

    class Envelope(BaseModel):
        nested: Aliased

    builder = SchemaBuilder()
    _ = builder.model_ref(Envelope)
    assert builder.defs["Aliased"]["properties"] == {
        "someBytes": {
            "type": "string",
            "contentEncoding": "base64",
            "title": "Somebytes",
        },
        "payload": {"type": "string", "contentEncoding": "base64", "title": "Payload"},
    }
    assert builder.defs["Envelope"]["properties"] == {
        "nested": {"$ref": "#/$defs/Aliased"}
    }
