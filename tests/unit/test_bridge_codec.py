"""Standard Base64 at every bytes position, independent of model JSON settings."""

import base64
from typing import cast

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretBytes, TypeAdapter
from pydantic.alias_generators import to_camel

from ksef2._core.exceptions import KSeFArgumentError
from ksef2.bridge._bytes import (
    BYTES,
    FieldsPlan,
    ItemsPlan,
    UnionPlan,
    ValuesPlan,
    bytes_plan,
)
from ksef2.bridge._codec import decode_base64, encode_base64
from ksef2.bridge._json import dump_state, state_data
from ksef2.models import ExportedInvoicesData
from ksef2.xades import XAdESCredentials


class Payload(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, ser_json_bytes="base64"
    )
    some_bytes: bytes


@pytest.mark.parametrize("length", range(6))
def test_decode_round_trips_standard_base64(length: int) -> None:
    raw = b"\xfb\xff\x00\xfb\xff"[:length]
    assert (
        decode_base64(base64.b64encode(raw).decode(), BYTES, op="test", where="payload")
        == raw
    )


@pytest.mark.parametrize(
    "value",
    [
        "-_8=",
        "+_8=",
        "-_9v",
        "+/8",
        "+/8==",
        "AAAA====",
        "+ /8",
        "+/8=\n",
        "ąAAA",
        "//5=",
    ],
)
def test_decode_refuses_other_spellings_without_repeating_them(value: str) -> None:
    with pytest.raises(KSeFArgumentError) as raised:
        _ = decode_base64(value, BYTES, op="test", where="credentials.key_pem")
    assert raised.value.code == "ARGUMENT_ERROR"
    assert "credentials.key_pem is not standard Base64" in str(raised.value)
    assert value not in str(raised.value)


@pytest.mark.parametrize("value", [None, 123, [], {}, b"raw"])
def test_non_strings_are_left_for_validation(value: object) -> None:
    assert decode_base64(value, BYTES, op="test", where="payload") is value


def test_decode_items_accepts_aliases_and_names() -> None:
    plan = bytes_plan(list[Payload])
    assert isinstance(plan, ItemsPlan)
    assert isinstance(plan.item, FieldsPlan)
    assert decode_base64(
        [{"someBytes": "+/8="}, {"some_bytes": "//4="}], plan, op="test", where="items"
    ) == [{"someBytes": b"\xfb\xff"}, {"some_bytes": b"\xff\xfe"}]


def test_decode_nested_error_names_the_path() -> None:
    with pytest.raises(KSeFArgumentError, match=r"items\[1\].someBytes"):
        _ = decode_base64(
            [{"some_bytes": ""}, {"someBytes": "-_8="}],
            bytes_plan(list[Payload]),
            op="test",
            where="items",
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("//4=", b"\xff\xfe"),
        (["//4="], [b"\xff\xfe"]),
        ({"raw": "//4="}, {"raw": b"\xff\xfe"}),
        (None, None),
    ],
)
def test_decode_union_picks_by_shape(value: object, expected: object) -> None:
    plan = UnionPlan((BYTES, ItemsPlan(BYTES), ValuesPlan(BYTES)))
    assert decode_base64(value, plan, op="test", where="payload") == expected


def test_decode_union_selects_model_shape() -> None:
    plan = bytes_plan(bytes | Payload)
    assert decode_base64({"someBytes": "//4="}, plan, op="test", where="payload") == {
        "someBytes": b"\xff\xfe"
    }


@pytest.mark.parametrize(
    "source", [b"\xff\xfe", bytearray(b"\xff\xfe"), SecretBytes(b"\xff\xfe")]
)
def test_encode_non_utf8_bytes(source: object) -> None:
    assert encode_base64("__4=", source, BYTES) == "//4="


def test_masked_and_omitted_secrets_stay_hidden() -> None:
    class Secrets(BaseModel):
        masked: SecretBytes
        omitted: SecretBytes = Field(exclude=True)

    source = Secrets(masked=SecretBytes(b"\xff\xfe"), omitted=SecretBytes(b"private"))
    data = source.model_dump(mode="json")
    assert encode_base64(data, source, bytes_plan(Secrets)) == {"masked": "**********"}
    assert dump_state(source) == {"masked": "**********"}
    assert state_data(source) == {"masked": "**********"}


@pytest.mark.parametrize("by_alias", [True, False])
def test_lists_of_models_encode_by_index_and_serialized_key(by_alias: bool) -> None:
    source = [Payload(some_bytes=b"\xfb\xff"), Payload(some_bytes=b"\xff\xfe")]
    data = [item.model_dump(mode="json", by_alias=by_alias) for item in source]
    key = "someBytes" if by_alias else "some_bytes"
    assert encode_base64(data, source, bytes_plan(list[Payload])) == [
        {key: "+/8="},
        {key: "//4="},
    ]


def test_encode_uses_serialization_alias() -> None:
    class Aliased(BaseModel):
        content: bytes = Field(validation_alias="input", serialization_alias="output")
        model_config = ConfigDict(ser_json_bytes="base64")

    source = Aliased.model_validate({"input": b"\xfb\xff"})
    assert encode_base64(
        source.model_dump(mode="json", by_alias=True), source, bytes_plan(Aliased)
    ) == {"output": "+/8="}


@pytest.mark.parametrize(
    ("data", "source", "expected"),
    [
        ("__4=", b"\xff\xfe", "//4="),
        (["__4="], (b"\xff\xfe",), ["//4="]),
        ({"raw": "__4="}, {"raw": b"\xff\xfe"}, {"raw": "//4="}),
    ],
)
def test_encode_union_picks_by_python_type(
    data: object, source: object, expected: object
) -> None:
    assert (
        encode_base64(
            data, source, UnionPlan((BYTES, ItemsPlan(BYTES), ValuesPlan(BYTES)))
        )
        == expected
    )


def test_encode_union_selects_model_type() -> None:
    source = Payload(some_bytes=b"\xfb\xff")
    assert encode_base64(
        source.model_dump(mode="json"), source, bytes_plan(bytes | Payload)
    ) == {"some_bytes": "+/8="}


def test_models_validate_raw_bytes_unchanged() -> None:
    class DefaultConfig(BaseModel):
        content: bytes

    raw = b"\xfb\xff\x00"
    exported = TypeAdapter(ExportedInvoicesData).validate_python(
        {"archive": raw, "package": None, "metadata": None}
    )
    default = TypeAdapter(DefaultConfig).validate_python({"content": raw})
    credentials = TypeAdapter(XAdESCredentials).validate_python(
        {"cert_pem": raw, "key_pem": raw}
    )
    assert exported.archive == raw
    assert default.content == raw
    assert credentials.cert_pem == raw
    assert credentials.key_pem.get_secret_value() == raw
    decoded = cast(
        "dict[str, object]",
        decode_base64(
            {"cert_pem": "+/8A", "key_pem": "+/8A"},
            bytes_plan(XAdESCredentials),
            op="test",
            where="credentials",
        ),
    )
    assert (
        TypeAdapter(XAdESCredentials)
        .validate_python(decoded)
        .key_pem.get_secret_value()
        == raw
    )
