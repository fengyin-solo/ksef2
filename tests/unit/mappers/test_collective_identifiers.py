from ksef2._infra.mappers.collective_identifiers import from_spec
from ksef2._infra.schema.api import spec


def test_invoice_response_preserves_collective_identifier_number() -> None:
    response = spec.CollectiveIdentifierInvoicesQueryResponse(
        invoices=[
            spec.CollectiveIdentifierInvoicesQueryResponseItem(
                ksefNumber="1234567890-20250625-ABC123-DEF456-07",
                collectiveIdentifierNumber="1111111111-IZ202607-65ED02180000-E7",
                detailsHidden=False,
            )
        ]
    )

    assert from_spec(response).invoices[0].model_dump() == {
        "ksef_number": "1234567890-20250625-ABC123-DEF456-07",
        "collective_identifier_number": "1111111111-IZ202607-65ED02180000-E7",
        "payment": None,
        "description": None,
        "details_hidden": False,
    }
