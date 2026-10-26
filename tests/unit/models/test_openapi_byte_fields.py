"""All OpenAPI byte fields must preserve Base64 wire text, including hashes."""

import base64
import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from ksef2._infra.schema.api.spec import models


def _byte_fields() -> list[tuple[str, str, bool]]:
    source = Path(__file__).resolve().parents[3] / "openapi.json"
    schemas = cast(
        dict[str, dict[str, Any]],
        json.loads(source.read_text())["components"]["schemas"],
    )
    fields: list[tuple[str, str, bool]] = []
    for model_name, schema in schemas.items():
        for field_name, definition in schema.get("properties", {}).items():
            if "allOf" in definition:
                definition = definition["allOf"][0]
            if "$ref" in definition:
                definition = schemas[definition["$ref"].rsplit("/", 1)[1]]
            if definition.get("format") == "byte":
                fields.append(
                    (model_name, field_name, definition.get("minLength") == 44)
                )
    return fields


BYTE_FIELDS = _byte_fields()


@pytest.mark.parametrize(
    "model_name,field_name", [(model, field) for model, field, _ in BYTE_FIELDS]
)
@pytest.mark.parametrize("content", [b"\xff" * 32, b"a" * 32], ids=["binary", "ascii"])
def test_byte_field_preserves_wire_text(
    model_name: str, field_name: str, content: bytes
) -> None:
    model = cast(type[BaseModel], getattr(models, model_name))
    adapter = TypeAdapter[object](model.model_fields[field_name].rebuild_annotation())
    encoded = base64.b64encode(content).decode("ascii")

    value = adapter.validate_python(encoded)

    assert value == encoded
    assert json.loads(adapter.dump_json(value)) == encoded


@pytest.mark.parametrize(
    "model_name,field_name",
    [(model, field) for model, field, is_hash in BYTE_FIELDS if is_hash],
)
@pytest.mark.parametrize("length", [43, 45])
def test_hash_fields_retain_wire_length_constraints(
    model_name: str, field_name: str, length: int
) -> None:
    model = cast(type[BaseModel], getattr(models, model_name))
    adapter = TypeAdapter[object](model.model_fields[field_name].rebuild_annotation())

    with pytest.raises(ValidationError):
        _ = adapter.validate_python("A" * length)
