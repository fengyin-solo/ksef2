---
title: Pobieranie statusu i UPO
description: Sprawdzaj status sesji interaktywnej i wsadowej, listuj faktury sesji i pobieraj dokumenty UPO.
---

Użyj tej strony po wysłaniu XML faktury. Przykłady zakładają, że masz już uwierzytelnionego klienta `auth`.

Wywołania statusu zwracają modele SDK. Wywołania UPO (Urzędowego Poświadczenia Odbioru) zwracają bajty XML.

## Status faktury w sesji interaktywnej

Przy wysyłce interaktywnej `send_invoice()` zwraca numer referencyjny faktury w sesji. Użyj go do sprawdzania wyniku faktury i pobrania jej UPO.

```python
from pathlib import Path

from ksef2 import FormSchema

with auth.online_session(form_code=FormSchema.FA3) as session:
    submission = session.send_invoice(invoice_xml)

    invoice_status = submission.wait(timeout=120.0, poll_interval=2.0)

    # SessionInvoiceStatusResponse
    # {
    #   "ordinal_number": 1,
    #   "reference_number": "20260625-SO-0123456789-ABCDEF0123-45",
    #   "invoice_number": "FV/42/2026",
    #   "ksef_number": "5261040828-20260625-ABCDEF012345-67",
    #   "status": {
    #     "code": 200,
    #     "description": "Processed"
    #   }
    # }

    upo_xml = submission.download_upo()
    Path("upo.xml").write_bytes(upo_xml)
```

`download_upo()` to jedno zapytanie i nigdy nie czeka, więc najpierw wywołaj `submission.wait()`, jak powyżej. Wywołane za wcześnie zgłasza wyjątek `KSeFNotReadyError` ze wskazówką, żeby wywołać `wait()`.

W tym samym bloku sesji, jeśli masz już numer KSeF, możesz pobrać UPO faktury po numerze KSeF:

```python
ksef_number = invoice_status.ksef_number
if ksef_number is None:
    raise RuntimeError("KSeF did not assign an invoice number.")

upo_xml = session.download_invoice_upo(ksef_number=ksef_number)
```

:::caution[Zachowaj numer referencyjny faktury]
Numer referencyjny faktury pozwala później sprawdzić jedną fakturę w sesji. Zapisz go, zanim zaczniesz czekać, żeby inny proces roboczy mógł sprawdzić wynik, jeśli pierwotny proces się zatrzyma.
:::

## Pobierz UPO po restarcie

Mając nowego uwierzytelnionego klienta `auth`, użyj zapisanych numerów referencyjnych, aby pobrać UPO z sesji interaktywnej lub wsadowej. Nie potrzebujesz otwartego obiektu sesji ani `OnlineSessionResumeState` z kluczami szyfrowania.

```python
# Wczytaj te referencje z danych zapisanych przez aplikację.
upo_xml = auth.invoice_sessions.download_upo(
    session_reference_number,
    invoice_reference_number=invoice_reference_number,
)
_ = Path("upo.xml").write_bytes(upo_xml)

# Alternatywnie wybierz fakturę po numerze KSeF.
upo_xml = auth.invoice_sessions.download_upo(
    session_reference_number,
    ksef_number=ksef_number,
)

# Albo pobierz jedną stronę UPO sesji po zapisanej referencji UPO.
upo_page_xml = auth.invoice_sessions.download_upo(
    session_reference_number,
    upo_reference_number=upo_reference_number,
)
```

Przekaż dokładnie jeden z parametrów: `invoice_reference_number`, `ksef_number` albo `upo_reference_number`. Każde wywołanie wykonuje jedno uwierzytelnione żądanie i zwraca bajty XML. Dla klienta asynchronicznego użyj `await` przy tym samym wywołaniu.

Podobnie jak `submission.download_upo()`, ta metoda nie czeka i nie sprawdza statusu w pętli. Gdy KSeF zwróci kod 21165 albo 21178, zgłasza wyjątek `KSeFNotReadyError`. Sprawdź status przetwarzania przed ponowną próbą. Odrzucona faktura może nigdy nie dostać UPO. Strona UPO sesji jest dostępna po zamknięciu i przetworzeniu sesji.

## Strony sesji interaktywnej

Stron sesji użyj, gdy chcesz sprawdzić wszystko, co wysłano w sesji interaktywnej, a nie jedną fakturę.

### Przyjęte

```python
page = session.list_invoices(page_size=100)

for invoice in page.invoices:
    print(invoice.reference_number, invoice.ksef_number)
```

### Odrzucone

```python
page = session.list_failed_invoices(page_size=100)

for invoice in page.invoices:
    print(invoice.reference_number, invoice.status.code, invoice.status.details)
```

## Status sesji wsadowej i UPO

Przy wysyłce wsadowej zachowaj zwrócony `BatchSessionResumeState`. Moduł sesji wsadowej może sprawdzać status po stanie albo po samym numerze referencyjnym sesji.

```python
from pathlib import Path

final_status = session.wait(timeout=300.0, poll_interval=2.0)

# SessionStatusResponse
# {
#   "status": {
#     "code": 200,
#     "description": "Processed"
#   },
#   "invoice_count": 10,
#   "successful_invoice_count": 9,
#   "failed_invoice_count": 1,
#   "upo": {
#     "pages": [
#       {
#         "reference_number": "upo-page-reference",
#         "download_url_expiration_date": "2026-06-26T10:00:00Z"
#       }
#     ]
#   }
# }

session.wait(timeout=120.0)  # sesja jest zamknięta; poczekaj, aż KSeF skończy

for number, upo_xml in enumerate(session.download_upo(), start=1):
    Path(f"batch-upo-{number}.xml").write_bytes(upo_xml)
```

:::note[UPO jest materiałem do audytu]
Zapisuj XML UPO trwale. To oficjalne poświadczenie, a nie tylko chwilowa odpowiedź ze statusem.
:::

## Lista faktur przyjętych i odrzuconych w sesji wsadowej

Faktury przyjęte i odrzucone są na osobnych stronach. Przy uzgadnianiu paczki przeczytaj oba zestawy.

### Przyjęte

```python
page = session.list_invoices(page_size=100)

for invoice in page.invoices:
    print(invoice.invoice_file_name, invoice.ksef_number, invoice.status.description)
```

### Odrzucone

```python
page = session.list_failed_invoices(page_size=100)

for invoice in page.invoices:
    print(invoice.invoice_file_name, invoice.status.code, invoice.status.details)
```

Gdy strona ma `continuation_token`, przekaż go do następnego wywołania:

```python
page = session.list_invoices(page_size=100)

while page.continuation_token is not None:
    page = session.list_invoices(
        page_size=100,
        continuation_token=page.continuation_token,
    )
```

## Znajdź sesje po restarcie

Użyj `auth.invoice_sessions`, gdy musisz znaleźć sesje interaktywne albo wsadowe po zakończeniu pierwotnego procesu wysyłki.

`list()` zwraca `Pager`. Iteruj po nim, żeby dostać każdą sesję, wywołaj `.pages()` dla list wielkości strony albo `.first_page()`, żeby wykonać jedno żądanie.

### Jedna strona

```python
sessions = auth.invoice_sessions.list(
    "online",
    statuses=["in_progress", "succeeded"],
).first_page()

for item in sessions:
    print(item.reference_number, item.status.code, item.total_invoice_count)
```

### Wszystkie sesje

```python
for item in auth.invoice_sessions.list("batch"):
    print(item.reference_number, item.status.description)
```

## Zalecany przebieg

1. Zapisz numery referencyjne sesji i faktur podczas wysyłki.

2. Sprawdzaj konkretną fakturę, sesję interaktywną albo sesję wsadową, zależnie od pytania.

3. Zapisz szczegóły faktur przyjętych i odrzuconych.

4. Pobierz XML UPO i zapisz go razem z danymi do audytu.

5. Użyj `auth.invoice_sessions`, żeby odzyskać numery referencyjne sesji po restarcie procesu.

## Następne strony

- [Wysyłanie faktur](send-invoices.md): XML faktury przez sesję interaktywną albo wsadową, zanim sprawdzisz status.
- [Status i UPO](../concepts/status-and-upo.md): statusy, dokumenty UPO, sprawdzanie wyniku i lokalne limity czasu.
- [Pobieranie faktur](download-invoices.md): przetworzony XML faktury po nadaniu numeru KSeF.
- [Wyszukiwanie faktur](query-invoices.md): przetworzone faktury, filtry metadanych i stronicowanie.
