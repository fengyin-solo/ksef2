"""Mappings from FA(3) authorized-subject schema models to domain objects."""

from functools import singledispatch
from typing import overload

from ksef2._domain.models.fa3.authorized_subject import (
    AuthorizedSubjectRole,
    InvoiceAuthorizedSubject,
)
from ksef2._domain.models.fa3.party import ContactInfo
from ksef2._infra.mappers.invoices.fa3.spec.subject import (
    from_spec as subject_from_spec,
)
from ksef2._infra.schema.fa3.models.schemat import (
    FakturaPodmiotUpowazniony,
    TrolaPodmiotuUpowaznionego,
)

_ROLE_MAP: dict[TrolaPodmiotuUpowaznionego, AuthorizedSubjectRole] = {
    TrolaPodmiotuUpowaznionego.VALUE_1: "enforcement_authority",
    TrolaPodmiotuUpowaznionego.VALUE_2: "bailiff",
    TrolaPodmiotuUpowaznionego.VALUE_3: "tax_representative",
}


@overload
def from_spec(schema: FakturaPodmiotUpowazniony) -> InvoiceAuthorizedSubject: ...


@overload
def from_spec(schema: object) -> object: ...


def from_spec(schema: object) -> object:
    """Convert an FA(3) authorized-subject schema model into the domain model."""
    return _from_spec(schema)


@singledispatch
def _from_spec(schema: object) -> object:
    raise NotImplementedError(
        f"No mapper registered for {type(schema).__name__}. "
        f"Register one with @_from_spec.register"
    )


@_from_spec.register
def _(schema: FakturaPodmiotUpowazniony) -> InvoiceAuthorizedSubject:
    identity = schema.dane_identyfikacyjne
    contact = None
    if schema.dane_kontaktowe:
        contacts = [
            ContactInfo(email=item.email_pu, phone=item.telefon_pu)
            for item in schema.dane_kontaktowe
            if item.email_pu is not None or item.telefon_pu is not None
        ]
        if contacts:
            contact = contacts[0] if len(contacts) == 1 else contacts

    return InvoiceAuthorizedSubject(
        tax_id=identity.nip,
        name=identity.nazwa,
        address=subject_from_spec(schema.adres),
        correspondence_address=(
            subject_from_spec(schema.adres_koresp) if schema.adres_koresp else None
        ),
        contact=contact,
        role=_ROLE_MAP[schema.rola_pu],
        eori_number=schema.nr_eori,
    )
