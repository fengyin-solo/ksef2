"""Translate bytes positions between bridge Base64 and Python values."""

# The error-only local import of _json is safe after module initialization.
# pyright: reportImportCycles=false

import base64
import binascii
from collections.abc import Iterable, Mapping
from typing import cast

from pydantic import BaseModel, SecretBytes

from ksef2.bridge._bytes import (
    BytesLeaf,
    FieldsPlan,
    ItemsPlan,
    Plan,
    UnionPlan,
    ValuesPlan,
    field_keys,
)


def decode_base64(value: object, plan: Plan | None, *, op: str, where: str) -> object:
    """Decode standard Base64 at bytes positions before Python validation."""
    if isinstance(plan, BytesLeaf) and isinstance(value, str):
        try:
            if len(value) % 4:
                raise ValueError
            raw = base64.b64decode(value, validate=True)
            if base64.b64encode(raw).decode("ascii") != value:
                raise ValueError
        except (ValueError, binascii.Error):
            # Import only on failure: the JSON exporter uses this codec too.
            from ksef2.bridge._json import argument_error

            raise argument_error(op, f"{where} is not standard Base64") from None
        return raw
    if isinstance(plan, UnionPlan):
        for alternative in plan.alternatives:
            if (
                isinstance(value, str)
                and isinstance(alternative, BytesLeaf)
                or isinstance(value, list)
                and isinstance(alternative, ItemsPlan)
                or isinstance(value, dict)
                and isinstance(alternative, FieldsPlan | ValuesPlan)
            ):
                return decode_base64(
                    cast("object", value), alternative, op=op, where=where
                )
    if isinstance(plan, ItemsPlan) and isinstance(value, list):
        return [
            decode_base64(item, plan.item, op=op, where=f"{where}[{index}]")
            for index, item in enumerate(cast("list[object]", value))
        ]
    if isinstance(value, dict):
        data = cast("dict[str, object]", value)
        if isinstance(plan, ValuesPlan):
            return {
                key: decode_base64(item, plan.value, op=op, where=f"{where}.{key}")
                for key, item in data.items()
            }
        if isinstance(plan, FieldsPlan):
            decoded = dict(data)
            for name, field_plan in plan.fields.items():
                for key in field_keys(plan.model, name):
                    if key in decoded:
                        decoded[key] = decode_base64(
                            decoded[key], field_plan, op=op, where=f"{where}.{key}"
                        )
            return decoded
    return cast("object", value)


def encode_base64(data: object, source: object, plan: Plan | None) -> object:
    """Rewrite exported bytes positions using the original Python bytes."""
    if isinstance(plan, BytesLeaf):
        if data is None or data == "**********":
            return cast("object", data)
        raw = source.get_secret_value() if isinstance(source, SecretBytes) else source
        if isinstance(raw, bytes | bytearray):
            return base64.b64encode(raw).decode("ascii")
    if isinstance(plan, UnionPlan):
        for alternative in plan.alternatives:
            if (
                isinstance(source, bytes | bytearray | SecretBytes)
                and isinstance(alternative, BytesLeaf)
                or isinstance(source, BaseModel)
                and isinstance(alternative, FieldsPlan)
                or isinstance(source, Mapping)
                and isinstance(alternative, ValuesPlan)
                or isinstance(source, Iterable)
                and not isinstance(
                    source, str | bytes | bytearray | Mapping | BaseModel
                )
                and isinstance(alternative, ItemsPlan)
            ):
                return encode_base64(data, cast("object", source), alternative)
    if (
        isinstance(plan, ItemsPlan)
        and isinstance(data, list)
        and isinstance(source, Iterable)
    ):
        return [
            encode_base64(item, original, plan.item)
            for item, original in zip(
                cast("list[object]", data),
                cast("Iterable[object]", source),
                strict=True,
            )
        ]
    if isinstance(data, dict):
        exported = cast("dict[str, object]", data)
        if isinstance(plan, ValuesPlan) and isinstance(source, Mapping):
            originals = cast("Mapping[object, object]", source)
            encoded = dict(exported)
            for key, item in originals.items():
                if str(key) in encoded:
                    encoded[str(key)] = encode_base64(
                        encoded[str(key)], item, plan.value
                    )
            return encoded
        if isinstance(plan, FieldsPlan) and isinstance(source, BaseModel):
            encoded = dict(exported)
            for name, field_plan in plan.fields.items():
                for key in field_keys(type(source), name, serialization=True):
                    if key in encoded:
                        encoded[key] = encode_base64(
                            encoded[key],
                            cast("object", getattr(source, name)),
                            field_plan,
                        )
            return encoded
    return cast("object", data)
