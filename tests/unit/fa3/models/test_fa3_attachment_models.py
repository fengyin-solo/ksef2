import re

import pytest

from ksef2 import KSeFValidationError
from ksef2._domain.models.fa3.attachment import AttachmentTable, ValueType


def test_attachment_table_accepts_column_names_matching_column_format() -> None:
    table = AttachmentTable(
        columns_names=["Service", "Amount", "SupplyDate"],
        columns_format=["txt", "decimal", "date"],
        rows=[["Consulting", "100.00", "2026-04-03"]],
    )

    assert table.columns_names == ["Service", "Amount", "SupplyDate"]


def test_attachment_table_rejects_column_names_count_mismatch() -> None:
    with pytest.raises(
        KSeFValidationError,
        match="Column names count does not match column format count",
    ):
        AttachmentTable(
            columns_names=["Service", "Amount"],
            columns_format=["txt", "decimal", "date"],
            rows=[["Consulting", "100.00", "2026-04-03"]],
        )


def test_attachment_table_accepts_finite_decimal_and_integer_cells() -> None:
    table = AttachmentTable(
        columns_format=["decimal", "integer"],
        rows=[["100.00", "2"], ["-0.25", "-5"], ["0.9000", "0"]],
    )

    assert table.summary == ["100.6500", "-3"]


def test_attachment_table_accepts_integral_decimal_text_in_integer_columns() -> None:
    table = AttachmentTable(
        columns_format=["integer"],
        rows=[["1.0"], ["5."]],
    )

    assert table.rows == [["1.0"], ["5."]]
    assert table.summary == ["6.0"]


@pytest.mark.parametrize("value", ["1.5", "0.25", "1.5e-2"])
def test_attachment_table_rejects_fractional_integer_cells(value: str) -> None:
    with pytest.raises(
        KSeFValidationError,
        match=rf"Cell \(0, 0\) of value `{re.escape(value)}` is not an integer",
    ):
        AttachmentTable(columns_format=["integer"], rows=[[value]])


@pytest.mark.parametrize(
    "value", ["NaN", "sNaN", "-NaN", "Infinity", "-Infinity", "inf"]
)
def test_attachment_table_rejects_non_finite_decimal_cells(value: str) -> None:
    with pytest.raises(
        KSeFValidationError,
        match=rf"Cell \(0, 0\) of value `{re.escape(value)}` is not a finite decimal number",
    ):
        AttachmentTable(columns_format=["decimal"], rows=[[value]])


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_attachment_table_rejects_non_finite_integer_cells(value: str) -> None:
    with pytest.raises(
        KSeFValidationError,
        match=rf"Cell \(0, 0\) of value `{re.escape(value)}` is not a finite integer",
    ):
        AttachmentTable(columns_format=["integer"], rows=[[value]])


@pytest.mark.parametrize(
    ("column_type", "value"),
    [
        ("decimal", "1e3"),
        ("decimal", "1.5e2"),
        ("integer", "1e3"),
        ("integer", "1.5e2"),
    ],
)
def test_attachment_table_accepts_finite_exponential_notation(
    column_type: ValueType, value: str
) -> None:
    table = AttachmentTable(columns_format=[column_type], rows=[[value], ["2"]])

    assert table.rows[0] == [value]


def test_attachment_table_includes_exponential_values_in_auto_summary() -> None:
    decimal_table = AttachmentTable(
        columns_format=["decimal"],
        rows=[["1e2"], ["199.00"]],
    )
    integer_table = AttachmentTable(
        columns_format=["integer"],
        rows=[["1e3"], ["2"]],
    )

    assert decimal_table.summary == ["299.00"]
    assert integer_table.summary == ["1002"]


def test_attachment_table_rejects_non_numeric_decimal_text() -> None:
    with pytest.raises(
        KSeFValidationError,
        match=r"Cell \(0, 0\) of value `abc` is not numeric",
    ):
        AttachmentTable(columns_format=["decimal"], rows=[["abc"]])


@pytest.mark.parametrize("marker", ["", "-"])
def test_attachment_table_accepts_missing_markers_in_numeric_cells(marker: str) -> None:
    table = AttachmentTable(
        columns_format=["decimal", "integer"],
        rows=[[marker, "-"], ["10.00", marker]],
        summary=["-", "-"],
    )

    assert table.rows == [[marker, "-"], ["10.00", marker]]
    assert table.summary == ["-", "-"]


def test_attachment_table_reports_the_offending_cell_indices() -> None:
    with pytest.raises(
        KSeFValidationError,
        match=r"Cell \(1, 1\) of value `1.5` is not an integer",
    ):
        AttachmentTable(
            columns_format=["txt", "integer", "decimal"],
            rows=[
                ["ok", "2", "1.00"],
                ["bad", "1.5", "NaN"],
            ],
        )

    with pytest.raises(
        KSeFValidationError,
        match=r"Cell \(0, 2\) of value `NaN` is not a finite decimal number",
    ):
        AttachmentTable(
            columns_format=["txt", "integer", "decimal"],
            rows=[["ok", "2", "NaN"]],
        )

    with pytest.raises(
        KSeFValidationError,
        match=r"Cell \(2, 0\) of value `oops` is not numeric",
    ):
        AttachmentTable(
            columns_format=["decimal", "txt"],
            rows=[["1.00", "a"], ["2.00", "b"], ["oops", "c"]],
        )


def test_attachment_table_keeps_validating_other_column_types() -> None:
    table = AttachmentTable(
        columns_format=["date", "datetime", "time", "txt"],
        rows=[["2026-04-03", "2026-04-03T10:15:00", "10:15", "free text"]],
    )

    assert table.summary == ["-", "-", "-", "-"]

    with pytest.raises(
        KSeFValidationError,
        match=r"Cell \(0, 0\) of value `not-a-date` is not a valid date",
    ):
        AttachmentTable(columns_format=["date"], rows=[["not-a-date"]])
