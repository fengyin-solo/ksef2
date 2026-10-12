import pytest

from ksef2._domain.models.fa3.body import InvoiceType

from tests.e2e.mappers.fa3._roundtrip import assert_roundtrip, roundtrip


CORRECTION_SAMPLES = [
    "FA_3_Przykład_2.xml",
    "FA_3_Przykład_3.xml",
    "FA_3_Przykład_5.xml",
    "FA_3_Przykład_6.xml",
    "FA_3_Przykład_7.xml",
    "KSEF_02_KOR.xml",
]


@pytest.mark.parametrize("sample_name", CORRECTION_SAMPLES)
def test_fa3_correction_samples_roundtrip(sample_name: str) -> None:
    assert_roundtrip(sample_name, InvoiceType.CORRECTING)


def test_fa3_correction_roundtrip_keeps_original_row_numbers() -> None:
    original, domain_invoice, result, _ = roundtrip("KSEF_02_KOR.xml")

    assert [row.nr_wiersza_fa for row in original.fa.fa_wiersz] == [1, 1]
    assert [row.row_number for row in domain_invoice.body.rows] == [1, 1]
    assert [row.nr_wiersza_fa for row in result.fa.fa_wiersz] == [1, 1]
