"""Public FA(3) authorized-subject domain model mapped to ``Faktura/PodmiotUpowazniony``."""

import re
from typing import Literal

from pydantic import Field, field_validator

from ksef2._domain.models.base import KSeFBaseModel
from ksef2._domain.models.fa3.party import ContactInfo, InvoiceAddress

AuthorizedSubjectRole = Literal[
    "enforcement_authority",
    "bailiff",
    "tax_representative",
]


class InvoiceAuthorizedSubject(KSeFBaseModel):
    """Authorized subject stored in the optional ``Faktura/PodmiotUpowazniony`` block."""

    tax_id: str = Field(
        description="dane_identyfikacyjne/NIP: Polish NIP of the authorized subject."
    )
    """Polish NIP of the authorized subject."""
    name: str = Field(
        min_length=1,
        max_length=512,
        description="dane_identyfikacyjne/Nazwa: Name of the authorized subject.",
    )
    """Full name of the authorized subject."""
    address: InvoiceAddress = Field(
        description="adres: Registered address of the authorized subject."
    )
    """Address of the authorized subject."""
    correspondence_address: InvoiceAddress | None = Field(
        default=None,
        description="adres_koresp: Optional mailing address for the authorized subject.",
    )
    """Correspondence address, if different from ``address``."""
    contact: list[ContactInfo] | ContactInfo | None = Field(
        default=None,
        description="dane_kontaktowe: Up to three contact entries (EmailPU/TelefonPU).",
    )
    """One or more contact entries (up to three)."""
    role: AuthorizedSubjectRole = Field(
        description="rola_pu: Enumerated role of the authorized subject on the invoice."
    )
    """Role of the authorized subject on the invoice."""
    eori_number: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="nr_eori: EORI number of the authorized subject.",
    )
    """EORI number of the authorized subject."""

    @field_validator("tax_id")
    @classmethod
    def _validate_tax_id(cls, value: str) -> str:
        if re.fullmatch(r"\d{10}", value) is None:
            raise ValueError("tax_id must be exactly 10 digits")
        return value

    @field_validator("contact")
    @classmethod
    def _validate_contact_count(
        cls, value: list[ContactInfo] | ContactInfo | None
    ) -> list[ContactInfo] | ContactInfo | None:
        if isinstance(value, list) and len(value) > 3:
            raise ValueError("contact accepts at most 3 entries")
        return value
