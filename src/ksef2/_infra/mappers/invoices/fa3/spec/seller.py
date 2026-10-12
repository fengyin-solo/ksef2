"""Mappings from FA(3) seller schema models to domain objects."""

from functools import singledispatch
from typing import overload

from ksef2._domain.models.fa3 import ContactInfo, InvoiceEntity
from ksef2._domain.models.fa3.party import TaxpayerStatus
from ksef2._infra.mappers.invoices.fa3.spec.subject import (
    from_spec as subject_from_spec,
)
from ksef2._infra.schema.fa3.models.schemat import (
    FakturaPodmiot1,
    TstatusInfoPodatnika,
)

_TAXPAYER_STATUS: dict[TstatusInfoPodatnika, TaxpayerStatus] = {
    TstatusInfoPodatnika.VALUE_1: "in_liquidation",
    TstatusInfoPodatnika.VALUE_2: "in_restructuring",
    TstatusInfoPodatnika.VALUE_3: "in_bankruptcy",
    TstatusInfoPodatnika.VALUE_4: "successor_enterprise",
}


@overload
def from_spec(schema: FakturaPodmiot1) -> InvoiceEntity: ...


@overload
def from_spec(schema: object) -> object: ...


def from_spec(schema: object) -> object:
    """Convert an FA(3) seller schema model into the domain model."""
    return _from_spec(schema)


@singledispatch
def _from_spec(schema: object) -> object:
    raise NotImplementedError(
        f"No mapper registered for {type(schema).__name__}. "
        f"Register one with @_from_spec.register"
    )


@_from_spec.register
def _(schema: FakturaPodmiot1) -> InvoiceEntity:
    identity = schema.dane_identyfikacyjne
    contact = None
    if schema.dane_kontaktowe:
        first = schema.dane_kontaktowe[0]
        if first.email is not None or first.telefon is not None:
            contact = ContactInfo(email=first.email, phone=first.telefon)

    return InvoiceEntity(
        tax_id=identity.nip,
        vat_prefix=schema.prefiks_podatnika.value if schema.prefiks_podatnika else None,
        name=identity.nazwa,
        address=subject_from_spec(schema.adres) if schema.adres else None,
        correspondence_address=subject_from_spec(schema.adres_koresp)
        if schema.adres_koresp
        else None,
        contact=contact,
        taxpayer_status=_TAXPAYER_STATUS.get(schema.status_info_podatnika)
        if schema.status_info_podatnika
        else None,
        eori_number=schema.nr_eori,
    )
