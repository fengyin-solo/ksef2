---
title: Wyszukiwanie faktur
description: Wyszukuj metadane faktur przez filtry, stronicowanie i sprawdzanie statusu w ksef2.
---

Użyj `auth.invoices`, gdy potrzebujesz metadanych faktur poza sesją wysyłki. Przykłady poniżej zakładają, że masz już uwierzytelnionego klienta `auth`.

`InvoiceMetadataParams.page_size` przyjmuje wartości od 10 do 250. Zakres dat metadanych może obejmować najwyżej 100 dni. Dłuższe wyszukiwania podziel na kolejne zakresy.

## Zbuduj wąski filtr

Zacznij od pytania biznesowego: jaka rola, jakie pole daty i jaki przedział czasu mają zostać przeszukane przez KSeF?

```python
from datetime import datetime, timedelta, timezone

from ksef2.models import InvoicesFilter

now = datetime.now(tz=timezone.utc)

filters = InvoicesFilter.for_seller(
    date_from=now - timedelta(days=7),
    date_to=now,
    invoice_types=["vat"],
    invoicing_mode="online",
)
```

`InvoicesFilter` normalizuje każdą przyjętą datę do UTC przed porównaniem i mapowaniem żądania. Wartości z jawnym offsetem zachowują swój moment. Wartości bez strefy są interpretowane jako czas lokalny Europe/Warsaw. Niejednoznaczne albo nieistniejące godziny zmiany czasu muszą zawierać jawny offset.

KSeF przyjmuje zakresy zapytań o długości najwyżej 100 dni. Dłuższe zapytania historyczne podziel na krótsze przedziały. `InvoiceMetadataParams.page_size` musi wynosić od 10 do 250. Domyślna wartość to 10.

:::tip[Do synchronizacji użyj dat trwałego zapisu]
`issue_date` zwykle pasuje do okresów księgowych. Do automatycznej synchronizacji przyrostowej użyj `date_type="permanent_storage"` oraz `restrict_to_permanent_storage_hwm_date=True`.
:::

## Pobierz jedną stronę

`auth.invoices.search()` zwraca leniwy obiekt `Pager`. Nic nie jest pobierane, dopóki go nie użyjesz. Wywołaj `first_page()`, gdy potrzebujesz jednej strony dla ekranu, uzgodnienia albo diagnostyki.

```python
from ksef2.models import InvoiceMetadataParams

pager = auth.invoices.search(
    filters,
    InvoiceMetadataParams(page_size=25, sort_order="asc"),
)

for invoice in pager.first_page():
    print(invoice.ksef_number, invoice.invoice_number)
```

## Przejdź po wynikach

Iteruj po obiekcie stronicowania, żeby dostać wiersze faktur, albo wywołaj `pages()`, gdy ważna jest każda strona. Obiekt sam obsługuje granice stron i obcięcia w KSeF.

### Strony

```python
params = InvoiceMetadataParams(page_size=100, sort_order="asc")

for page in auth.invoices.search(filters, params).pages():
    print(f"page={len(page)}")

    for invoice in page:
        print(invoice.ksef_number, invoice.permanent_storage_date)
```

### Faktury

```python
params = InvoiceMetadataParams(page_size=100, sort_order="asc")

for invoice in auth.invoices.search(filters, params):
    print(invoice.ksef_number, invoice.invoice_number)
```

## Wznów od kursora

`page()` pobiera jedną stronę i zwraca obiekt `Page`: jego `items` oraz `next_cursor`, czyli napis wskazujący następną stronę. Zapisz ten napis i przekaż go później do `page()`, w tym samym albo w nowym procesie. Wyszukiwanie będzie kontynuowane w miejscu przerwania, bez ponownego pobierania stron już odczytanych.

```python
params = InvoiceMetadataParams(page_size=100, sort_order="asc")

first = auth.invoices.search(filters, params).page()
cursor = first.next_cursor

for invoice in first.items:
    print(invoice.ksef_number, invoice.invoice_number)

# Later, after a restart, with the cursor you kept.
if cursor is not None:
    second = auth.invoices.search(filters, params).page(cursor)

    for invoice in second.items:
        print(invoice.ksef_number, invoice.invoice_number)
```

Kursor wyszukiwania faktur zawiera całe następne żądanie: filtr, rozmiar strony, kolejność sortowania oraz granicę obcięcia, na której zatrzymał się KSeF. Wznowione wyszukiwanie zachowuje więc pozycję nawet wtedy, gdy KSeF zawęził zakres dat. Wznów je na wyszukiwaniu zbudowanym z tym samym filtrem, rozmiarem strony i kolejnością sortowania. Jawnie podane `date_to` musi odpowiadać pierwotnej dacie końcowej. Jeśli je pominiesz, wznowione wyszukiwanie użyje daty zapisanej w kursorze. Kursor z innego wyszukiwania zgłasza wyjątek `KSeFArgumentError` przed wysłaniem jakiegokolwiek żądania. Kursor pokazuje te filtry, w tym numery NIP i numery faktur, w czytelnej postaci, więc nie zapisuj go w logach ani w adresach URL. `next_cursor` ma wartość `None` dopiero po przeczytaniu ostatniej strony. Strona może być pusta i nadal przekazywać kursor następnej. W kodzie asynchronicznym to samo odczytanie to `second = await auth.invoices.search(filters, params).page(cursor)`.

`pages()` oraz zwykła iteracja korzystają z tego samego łańcucha kursorów. Kursorami zajmujesz się tylko wtedy, gdy chcesz przerwać pracę i kontynuować później.

:::note[Kursory są nieprzezroczyste]
Kursor to stan SDK, a nie numer strony, który obliczasz. Kursor z innej kolekcji albo taki, którego SDK nie potrafi odczytać, zgłasza wyjątek `KSeFArgumentError` przed wysłaniem jakiegokolwiek żądania, a komunikat nie powtarza wtedy tego kursora.
:::

## Znajdź konkretną fakturę

Jeśli znasz własny numer faktury, dodaj go do filtra. Jeśli masz już numer KSeF, lepiej filtruj po `ksef_number` albo pobierz fakturę bezpośrednio.

```python
filters = InvoicesFilter.for_seller(
    date_from=now - timedelta(days=30),
    date_to=now,
    invoice_number="FV/42/2026",
)

page = auth.invoices.search(filters).first_page()
```

```python
filters = InvoicesFilter.for_seller(
    date_type="permanent_storage",
    date_from=now - timedelta(days=30),
    date_to=now,
    ksef_number="5261040828-20260625-ABCDEF012345-67",
)

page = auth.invoices.search(filters).first_page()
```

## Poczekaj po wysyłce

Przetwarzanie w KSeF jest asynchroniczne. Jeśli przepływ wysyła fakturę i od razu potrzebuje jej widoczności w API pobierania, sprawdzaj status wąskim filtrem.

```python
filters = InvoicesFilter.for_seller(
    date_from=now - timedelta(days=1),
    date_to=now,
    invoice_number="FV/42/2026",
)

pager = auth.invoices.search(filters).wait(timeout=120.0, poll_interval=2.0)

for invoice in pager:
    print(invoice.ksef_number, invoice.invoice_number)
```

:::caution[Oczekiwanie kończy się przy pierwszym dopasowaniu]
`wait()` zwraca wynik, gdy co najmniej jeden wiersz pasuje do filtra. Utrzymaj filtr na tyle konkretny, żeby pierwsze dopasowanie było fakturą, na którą czekasz. Jeśli nic nie pojawi się na czas, metoda zgłasza wyjątek `KSeFInvoiceQueryTimeoutError`.
:::

## Zalecany przebieg

1. Wybierz rolę podmiotu, w której wyszukujesz.

2. Wybierz pole daty pasujące do zadania: widok księgowy, widok przetwarzania albo synchronizacja przyrostowa.

3. Zbuduj wąski `InvoicesFilter`.

4. Pobierz jedną stronę do pracy na bieżąco albo użyj iteratorów do zadań w tle.

5. Zapisz wartości `ksef_number` do późniejszego bezpośredniego pobierania albo uzgodnienia eksportów.

## Następne strony

- [Pobieranie faktur](download-invoices.md): XML faktury bezpośrednio albo z zaszyfrowanej paczki eksportu.
- [Wysyłanie faktur](send-invoices.md): XML faktury przez sesję interaktywną albo wsadową, zanim wyszukasz wynik.
- [Wyszukiwanie i eksport paczek](../concepts/querying-and-exports.md): metadane, bezpośrednie pobieranie, paczki eksportu i synchronizacja według znacznika HWM.
