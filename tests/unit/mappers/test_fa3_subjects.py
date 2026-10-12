from ksef2._domain.models.fa3 import ContactInfo, InvoiceAddress, InvoiceEntity
from ksef2._infra.mappers.invoices.fa3.domain.buyer import to_spec as buyer_to_spec
from ksef2._infra.mappers.invoices.fa3.domain.seller import to_spec as seller_to_spec
from ksef2._infra.mappers.invoices.fa3.domain.subject import to_spec as subject_to_spec
from ksef2._infra.mappers.invoices.fa3.spec.buyer import from_spec as buyer_from_spec
from ksef2._infra.mappers.invoices.fa3.spec.seller import from_spec as seller_from_spec
from ksef2._infra.schema.fa3.models.elementarne_typy_danych_v10_0_e import Twybor1
from ksef2._infra.schema.fa3.models.kody_krajow_v10_0_e import TkodKraju
from ksef2._infra.schema.fa3.models.schemat import (
    FakturaPodmiot1,
    FakturaPodmiot1AdresKoresp,
    FakturaPodmiot2,
    FakturaPodmiot2Gv,
    FakturaPodmiot2Jst,
    Tadres,
    TkodyKrajowUe,
    Tpodmiot1,
    Tpodmiot2,
    TstatusInfoPodatnika,
)


def make_polish_address() -> InvoiceAddress:
    return InvoiceAddress(
        country_code="PL",
        address_line_1="Marszalkowska 10/5",
        address_line_2="00-001 Warszawa",
    )


def make_spec_address(line_1: str) -> Tadres:
    return Tadres(kod_kraju=TkodKraju.PL, adres_l1=line_1)


def test_subject_to_spec_maps_simple_address() -> None:
    output = subject_to_spec(make_polish_address())

    assert output.kod_kraju == TkodKraju.PL
    assert output.adres_l1 == "Marszalkowska 10/5"
    assert output.adres_l2 == "00-001 Warszawa"


def test_subject_to_spec_maps_foreign_address() -> None:
    output = subject_to_spec(
        InvoiceAddress(
            country_code="de",
            address_line_1="Unter den Linden 1",
            address_line_2="10115 Berlin",
        )
    )

    assert output.kod_kraju == TkodKraju.DE
    assert output.adres_l1 == "Unter den Linden 1"
    assert output.adres_l2 == "10115 Berlin"


def test_seller_to_spec_maps_invoice_entity() -> None:
    output = seller_to_spec(
        InvoiceEntity(
            tax_id="1234567890",
            eori_number="PL123456789000000",
            name="Seller Sp. z o.o.",
            address=make_polish_address(),
            contact=ContactInfo(
                email="seller@example.com",
                phone="+48123456789",
            ),
        )
    )

    assert isinstance(output, FakturaPodmiot1)
    assert output.nr_eori == "PL123456789000000"
    assert output.dane_identyfikacyjne.nip == "1234567890"
    assert output.dane_identyfikacyjne.nazwa == "Seller Sp. z o.o."
    assert output.adres.adres_l1 == "Marszalkowska 10/5"
    assert output.dane_kontaktowe[0].email == "seller@example.com"
    assert output.dane_kontaktowe[0].telefon == "+48123456789"


def test_parsing_keeps_party_correspondence_addresses_and_seller_status() -> None:
    seller = seller_from_spec(
        FakturaPodmiot1(
            dane_identyfikacyjne=Tpodmiot1(nip="1234567890", nazwa="Seller"),
            adres=make_spec_address("Marszalkowska 10/5"),
            adres_koresp=FakturaPodmiot1AdresKoresp(
                kod_kraju=TkodKraju.PL, adres_l1="Skrzynka pocztowa 1"
            ),
            status_info_podatnika=TstatusInfoPodatnika.VALUE_1,
        )
    )
    buyer = buyer_from_spec(
        FakturaPodmiot2(
            dane_identyfikacyjne=Tpodmiot2(nip="1234567890", nazwa="Buyer"),
            adres=make_spec_address("Piekna 1"),
            adres_koresp=make_spec_address("Skrzynka pocztowa 2"),
            jst=FakturaPodmiot2Jst.VALUE_2,
            gv=FakturaPodmiot2Gv.VALUE_2,
        )
    )

    assert seller.correspondence_address is not None
    assert seller.correspondence_address.address_line_1 == "Skrzynka pocztowa 1"
    assert seller.taxpayer_status == "in_liquidation"
    assert buyer.correspondence_address is not None
    assert buyer.correspondence_address.address_line_1 == "Skrzynka pocztowa 2"

    rebuilt_seller = seller_to_spec(seller)
    assert isinstance(rebuilt_seller, FakturaPodmiot1)
    assert rebuilt_seller.adres_koresp is not None
    assert rebuilt_seller.adres_koresp.adres_l1 == "Skrzynka pocztowa 1"
    assert rebuilt_seller.status_info_podatnika == TstatusInfoPodatnika.VALUE_1

    rebuilt_buyer = buyer_to_spec(buyer)
    assert isinstance(rebuilt_buyer, FakturaPodmiot2)
    assert rebuilt_buyer.adres_koresp is not None
    assert rebuilt_buyer.adres_koresp.adres_l1 == "Skrzynka pocztowa 2"


def test_buyer_to_spec_maps_polish_buyer_with_nip() -> None:
    output = buyer_to_spec(
        InvoiceEntity(
            tax_id="1234567890",
            customer_number="CUST-001",
            name="Buyer Sp. z o.o.",
            address=make_polish_address(),
            contact=ContactInfo(
                email="buyer@example.com",
                phone="+48987654321",
            ),
        )
    )

    assert isinstance(output, FakturaPodmiot2)
    assert output.dane_identyfikacyjne.nip == "1234567890"
    assert output.dane_identyfikacyjne.brak_id is None
    assert output.nr_klienta == "CUST-001"
    assert output.dane_kontaktowe[0].email == "buyer@example.com"
    assert output.dane_kontaktowe[0].telefon == "+48987654321"
    assert output.jst == FakturaPodmiot2Jst.VALUE_2
    assert output.gv == FakturaPodmiot2Gv.VALUE_2


def test_buyer_to_spec_maps_buyer_without_tax_id_to_brak_id() -> None:
    output = buyer_to_spec(
        InvoiceEntity(
            name="Buyer GmbH",
            address=InvoiceAddress(
                country_code="DE",
                address_line_1="Unter den Linden 1",
            ),
        )
    )

    assert output.dane_identyfikacyjne.nip is None
    assert output.dane_identyfikacyjne.brak_id == Twybor1.VALUE_1
    assert output.dane_identyfikacyjne.nazwa == "Buyer GmbH"


def test_buyer_to_spec_maps_eu_vat_identifier() -> None:
    output = buyer_to_spec(
        InvoiceEntity(
            eu_vat_id="DE123456789",
            name="Buyer GmbH",
            address=InvoiceAddress(
                country_code="DE",
                address_line_1="Unter den Linden 1",
            ),
        )
    )

    assert output.dane_identyfikacyjne.nip is None
    assert output.dane_identyfikacyjne.kod_ue == TkodyKrajowUe.DE
    assert output.dane_identyfikacyjne.nr_vat_ue == "123456789"
    assert output.dane_identyfikacyjne.brak_id is None


def test_buyer_to_spec_maps_other_identifier_without_brak_id() -> None:
    output = buyer_to_spec(
        InvoiceEntity(
            other_id="US-TAX-9988",
            name="Buyer Inc.",
            address=InvoiceAddress(
                country_code="US",
                address_line_1="1 Infinite Loop",
            ),
        )
    )

    assert output.dane_identyfikacyjne.kod_kraju == TkodKraju.US
    assert output.dane_identyfikacyjne.nr_id == "US-TAX-9988"
    assert output.dane_identyfikacyjne.brak_id is None


def test_buyer_to_spec_maps_eori_and_jst_gv_flags() -> None:
    output = buyer_to_spec(
        InvoiceEntity(
            tax_id="1234567890",
            eori_number="PL123456789000000",
            jst_subordinate_unit=True,
            vat_group_member=True,
            name="Buyer Sp. z o.o.",
            address=make_polish_address(),
        )
    )

    assert output.nr_eori == "PL123456789000000"
    assert output.jst == FakturaPodmiot2Jst.VALUE_1
    assert output.gv == FakturaPodmiot2Gv.VALUE_1
