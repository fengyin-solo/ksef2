"""Mappings from FA(3) authorized-subject domain models to generated schema models."""

from functools import singledispatch
from typing import overload

from pydantic import BaseModel

from ksef2._domain.models.fa3.authorized_subject import (
    AuthorizedSubjectRole,
    InvoiceAuthorizedSubject,
)
from ksef2._domain.models.fa3.party import ContactInfo
from ksef2._infra.mappers.invoices.fa3.domain.subject import to_spec as subject_to_spec
from ksef2._infra.schema.fa3.models.schemat import (
    FakturaPodmiotUpowazniony,
    FakturaPodmiotUpowaznionyDaneKontaktowe,
    Tpodmiot1,
    TrolaPodmiotuUpowaznionego,
)


def _map_contact_details(
    contact: ContactInfo | list[ContactInfo] | None,
) -> list[FakturaPodmiotUpowaznionyDaneKontaktowe]:
    if contact is None:
        return []
    contacts = contact if isinstance(contact, list) else [contact]
    result: list[FakturaPodmiotUpowaznionyDaneKontaktowe] = []
    for item in contacts:
        if item.email is None and item.phone is None:
            continue
        result.append(
            FakturaPodmiotUpowaznionyDaneKontaktowe(
                email_pu=item.email,
                telefon_pu=item.phone,
            )
        )
    return result


def _map_role(value: AuthorizedSubjectRole) -> TrolaPodmiotuUpowaznionego:
    if value == "enforcement_authority":
        return TrolaPodmiotuUpowaznionego.VALUE_1
    if value == "bailiff":
        return TrolaPodmiotuUpowaznionego.VALUE_2
    return TrolaPodmiotuUpowaznionego.VALUE_3


@overload
def to_spec(request: InvoiceAuthorizedSubject) -> FakturaPodmiotUpowazniony: ...


@overload
def to_spec(request: BaseModel) -> object: ...


def to_spec(request: BaseModel) -> object:
    """Convert an authorized-subject domain model into the FA(3) schema model."""
    return _to_spec(request)


@singledispatch
def _to_spec(request: BaseModel) -> object:
    raise NotImplementedError(
        f"No mapper registered for {type(request).__name__}. "
        f"Register one with @_to_spec.register"
    )


@_to_spec.register
def _(request: InvoiceAuthorizedSubject) -> FakturaPodmiotUpowazniony:
    return FakturaPodmiotUpowazniony(
        nr_eori=request.eori_number,
        dane_identyfikacyjne=Tpodmiot1(
            nip=request.tax_id,
            nazwa=request.name,
        ),
        adres=subject_to_spec(request.address),
        adres_koresp=(
            subject_to_spec(request.correspondence_address)
            if request.correspondence_address
            else None
        ),
        dane_kontaktowe=_map_contact_details(request.contact),
        rola_pu=_map_role(request.role),
    )
