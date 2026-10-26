---
title: Wysyłanie faktur
description: Wyślij XML FA(3) przez sesję interaktywną albo sesję wsadową ksef2.
---

Użyj `auth.online_session(...)` do wysyłki interaktywnej i `auth.batch` dla większych zestawów plików. Przykłady poniżej zakładają, że masz już uwierzytelnionego klienta `auth`.

## Zacznij od bajtów XML

API wysyłki przyjmuje bajty XML faktury. Te bajty mogą pochodzić z systemu ERP, z pliku albo z buildera FA(3) w SDK.

### Z pliku

```python
from pathlib import Path

invoice_xml = Path("invoice.xml").read_bytes()
```

### Z buildera

```python
from datetime import date
from decimal import Decimal

from ksef2.fa3 import InvoiceBuilder, VatRate

invoice_xml = (
    InvoiceBuilder()
    .header(system_info="ksef2 send guide")
    .seller(
        name="Demo Seller Sp. z o.o.",
        tax_id="5261040828",
        country_code="PL",
        address_line_1="Prosta 1",
        address_line_2="00-001 Warszawa",
    )
    .buyer(
        name="Demo Buyer Sp. z o.o.",
        country_code="PL",
        address_line_1="Kwiatowa 2",
        address_line_2="00-002 Warszawa",
    )
    .standard()
    .issue_date(date.today())
    .issue_place("Warszawa")
    .invoice_number("FV/42/2026")
    .rows()
    .add_line(
        name="Usługa konsultingowa",
        quantity=Decimal("1"),
        unit_price_net=Decimal("100.00"),
        vat_rate=VatRate.VAT_23,
    )
    .done()
    .done()
    .to_xml()
    .encode("utf-8")
)
```

## Wyślij w sesji interaktywnej

Sesji interaktywnej użyj, gdy wysyłasz jedną fakturę albo mały zestaw na bieżąco. Menedżer kontekstu (`with`) zamyka zdalną sesję po wyjściu z bloku.

```python
from ksef2 import FormSchema

with auth.online_session(form_code=FormSchema.FA3) as session:
    submission = session.send_invoice(invoice_xml)

    # InvoiceSubmission handle
    # submission.reference_number == "20260625-SO-0123456789-ABCDEF0123-45"

    status = submission.wait(timeout=120.0, poll_interval=2.0)

    # SessionInvoiceStatusResponse
    # {
    #   "reference_number": "20260625-SO-0123456789-ABCDEF0123-45",
    #   "ksef_number": "5261040828-20260625-ABCDEF012345-67",
    #   "invoice_number": "FV/42/2026",
    #   "status": {
    #     "code": 200,
    #     "description": "Processed"
    #   }
    # }
```

`send_invoice()` oznacza tylko, że KSeF przyjął zaszyfrowane dane do sesji. SDK sprawdza rozmiar XML faktury przed szyfrowaniem. Stosuje udokumentowany limit domyślny 1 MB, gdy limity sesji nie są znane. Wywołaj `auth.limits.get_context_limits()` przed otwarciem sesji, żeby w tym sprawdzeniu użyć obowiązującego limitu sesji, w tym limitu dla faktur z załącznikiem. `submission.wait()` czeka na wynik konkretnej faktury i zwraca numer KSeF po udanym przetworzeniu. Działa też po zamknięciu sesji, a `session.wait()` zwraca końcowy status zamkniętej sesji.

:::tip[W prostym skrypcie połącz wywołania]
`session.send_invoice(invoice_xml).wait()` wysyła fakturę i sprawdza status, gdy nie potrzebujesz osobnego obiektu wysyłki.
:::

## Zachowaj stan sesji i numery referencyjne

Zapisz stan, zanim długo będziesz sprawdzać status albo przekażesz pracę innemu procesowi.

```python
with auth.online_session(form_code=FormSchema.FA3) as session:
    session_state_json = session.resume_state().to_json()
    submission = session.send_invoice(invoice_xml)
    invoice_reference_number = submission.reference_number

# Zapisz session_state_json i invoice_reference_number w bezpiecznym magazynie.
# Nie loguj session_state_json, bo zawiera dane szyfrowania sesji.

# Później, w tym samym lub innym procesie:
with auth.online_session(state=session_state_json) as session:
    submission = session.submission(invoice_reference_number)
    status = submission.wait(timeout=120.0)
    upo_xml = submission.download_upo()
```

`online_session(state=...)` przyjmuje obiekt stanu albo jego JSON. `session.submission(reference_number)` zwraca obiekt `InvoiceSubmission` wcześniej wysłanej faktury. Wyjście z bloku zamyka sesję. Zamknięcie sesji, która już jest zamknięta, nic nie robi.

`submission.resume_state()` trzyma oba numery referencyjne w jednym dokumencie: faktury i sesji, do której trafiła. Ten stan przekaż do `session.submission(state=...)` zamiast samego numeru referencyjnego. Sesja musi być tą, do której wysłano fakturę. Inna sesja zgłasza wyjątek `KSeFArgumentError`. Podanie obu argumentów albo żadnego też go zgłasza.

```python
with auth.online_session(form_code=FormSchema.FA3) as session:
    submission_state_json = session.send_invoice(invoice_xml).resume_state().to_json()

# Później: odtwórz sesję z jej stanu, a potem fakturę z jej stanu.
with auth.online_session(state=session_state_json) as session:
    submission = session.submission(state=submission_state_json)
    status = submission.wait(timeout=120.0)
```

## Wyślij paczkę

Paczki użyj, gdy chcesz wysłać wiele plików XML jako jeden przepływ KSeF. Moduł wysokiego poziomu przygotowuje paczkę ZIP, szyfruje części, otwiera sesję wsadową, wysyła części, zamyka sesję i zwraca zamkniętego klienta `BatchSessionClient`. Potem wywołaj jego `wait()`, `list_failed_invoices()` i `download_upo()`. `auth.batch.prepare()` i `submit()` przyjmują elementy `bytes`, `str`, `Path` lub `BatchInvoice`. Rozmiar faktury jest sprawdzany względem udokumentowanego limitu domyślnego 1 MB, chyba że wcześniej pobrano `auth.limits.get_context_limits()`. Wtedy używany jest obowiązujący limit sesji wsadowej, w tym limit dla faktur z załącznikiem. `send_invoice()`, `auth.batch.prepare()` i `submit()` odrzucają krótkie napisy wyglądające jak ścieżki i zgłaszają wyjątek `KSeFArgumentError`. Przekaż treść XML albo odczytaj plik przez `Path(...).read_bytes()`. Wejścia wsadowe przyjmują też `Path`.

### Z plików

```python
from pathlib import Path

from ksef2 import FormSchema

prepared = auth.batch.prepare(
    [Path("invoice-1.xml"), Path("invoice-2.xml")],
    form_code=FormSchema.FA3,
)

session = auth.batch.submit(prepared)

# session.reference_number == "20260625-BATCH-..."
```

### Z bajtów

```python
from pathlib import Path

from ksef2 import FormSchema
from ksef2.models import BatchInvoice

session = auth.batch.submit(
    [
        BatchInvoice(
            file_name="invoice-1.xml",
            content=Path("invoice-1.xml").read_bytes(),
        ),
        BatchInvoice(
            file_name="invoice-2.xml",
            content=Path("invoice-2.xml").read_bytes(),
        ),
    ],
    form_code=FormSchema.FA3,
)

# session.reference_number == "20260625-BATCH-..."
```

## Poczekaj na zakończenie sesji wsadowej

Po wysłaniu paczki sprawdzaj status sesji wsadowej i obejrzyj faktury przyjęte oraz odrzucone.

```python
final_status = session.wait(timeout=300.0, poll_interval=2.0)

# SessionStatusResponse
# {
#   "status": {
#     "code": 200,
#     "description": "Processed"
#   },
#   "invoice_count": 2,
#   "successful_invoice_count": 2,
#   "failed_invoice_count": 0,
#   "upo": {
#     "pages": [
#       {
#         "reference_number": "upo-page-reference"
#       }
#     ]
#   }
# }

accepted = session.list_invoices(page_size=100)
failed = session.list_failed_invoices(page_size=100)
```

:::caution[Zakończenie sesji nadal wymaga sprawdzenia faktur]
Status sesji wsadowej podsumowuje sesję. Sprawdź strony faktur przyjętych i odrzuconych, zanim uznasz, że każda faktura z paczki osiągnęła oczekiwany wynik.
:::

## Zalecany przebieg

1. Uwierzytelnij się w kontekście logowania sprzedawcy.

2. Wczytaj XML faktury z własnego systemu albo zbuduj go przez `InvoiceBuilder`.

3. Użyj sesji interaktywnej dla małej wysyłki na bieżąco albo `auth.batch` dla większych zestawów.

4. Zapisz zwrócone numery referencyjne sesji i faktur, zanim zaczniesz sprawdzać status.

5. Sprawdzaj status, zapisz wyniki przyjęte i odrzucone z kolejnych stron, a potem pobierz UPO (Urzędowe Poświadczenie Odbioru) albo XML faktury.

## Następne strony

- [Pobieranie statusu i UPO](get-status-and-upo.md): sesje interaktywne i wsadowe, wyniki i XML UPO.
- [Budowanie faktur FA(3)](build-fa3-invoices.md): poprawny XML FA(3), gdy aplikacja jeszcze go nie ma.
- [Wyszukiwanie faktur](query-invoices.md): przetworzone faktury, filtry metadanych i stronicowanie.
- [Pobieranie faktur](download-invoices.md): przetworzony XML faktury po nadaniu numeru KSeF.
