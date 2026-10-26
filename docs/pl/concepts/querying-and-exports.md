---
title: Wyszukiwanie i eksport paczek
description: Metadane faktur, pobieranie pojedynczych dokumentów, paczki eksportu i synchronizacja przyrostowa.
---

Pobieranie faktur w KSeF to trzy różne zadania:

- metadane odpowiadają na pytanie, jakie faktury pasują do filtra;
- pobranie pojedynczej faktury zwraca przetworzony XML dla podanego numeru KSeF;
- eksport przygotowuje paczkę do pobrania dla większego zestawu faktur.

KSeF najlepiej traktować jako system wymiany i miejsce oficjalnego zapisu faktur, a nie jako bazę pod każdym ekranem aplikacji. W większości integracji stabilny układ jest taki: odpytaj KSeF albo wyeksportuj dane, zapisz wynik lokalnie i zasilaj widoki z własnego magazynu.

## Metadane znajdują faktury

`auth.invoices.search()` zwraca `InvoiceSearchPager` po wierszach `InvoiceMetadata`. Iteruj go albo użyj `pages()`, `first_page()`, `page(cursor)` i `wait()`. Te operacje zachowują kontrakt ogólnego `Pager`. `page(cursor)` pobiera jedną stronę i zwraca `next_cursor`, który pozwala wznowić to samo wyszukiwanie później, nawet w innym procesie. Tylko `next_cursor` równe `None` kończy wyszukiwanie: strona może być pusta i nadal wskazywać następną. Użyj `responses()` dla pełnych, typowanych stron albo `first_response()` dla jednej `QueryInvoicesMetadataResponse` z flagami stronicowania i `permanent_storage_hwm_date`.

Metadane przydają się do list, uzgodnień, sprawdzania statusu po wysyłce i decyzji, co pobrać później. Wiersz metadanych może zawierać identyfikatory, daty, dane stron, kwoty, pola schematu, skróty, flagi załączników i tryb fakturowania.

Filtr opisuje widok, który KSeF ma przeszukać:

- `role`, na przykład `seller` albo `buyer`;
- `date_type`, `date_from` i `date_to`;
- opcjonalne `amount_min` i `amount_max` oraz `amount_type`, gdy używasz zakresu kwot;
- identyfikatory takie jak `seller_nip`, `buyer_nip`, `invoice_number` albo `ksef_number`;
- opcjonalne dane faktury, takie jak `invoice_types`, `invoice_schema`, `has_attachment` i `invoicing_mode`.

:::tip[Typ kwoty należy do zakresu kwot]
Ustaw `amount_type` tylko wtedy, gdy używasz `amount_min` albo `amount_max`. SDK sprawdza, że filtr zakresu wskazuje pole kwoty KSeF, którego dotyczy.
:::

## Bezpośrednie pobieranie zwraca jeden XML

`auth.invoices.download()` pobiera jeden przetworzony dokument XML po `ksef_number`.

Ta ścieżka jest celowo wąska. Użyj jej, gdy masz już numer KSeF z wyniku sesji, zapytania o metadane, przepływu UPO albo własnej bazy. Jeśli KSeF nadał już numer, ale jeszcze nie udostępnił XML-a, `auth.invoices.download(ksef_number, timeout=...)` sprawdza gotowość dokumentu aż do lokalnego limitu czasu.

## Eksport tworzy zaszyfrowaną paczkę

Eksport jest asynchroniczny. `auth.invoices.export()` przyjmuje ten sam `InvoicesFilter`, którego używają zapytania o metadane, i zwraca `ExportJob`. Jego `wait()` sprawdza KSeF, aż paczka będzie gotowa, pobiera i odszyfrowuje części, łączy je i zwraca obiekt `ExportedInvoices`.

```text
InvoicesFilter
  -> auth.invoices.export()
    -> ExportJob
      -> job.wait()
        -> ExportedInvoices: invoices(), metadata, archive, save()
```

:::caution[Obiekt eksportu trzymaj jak dane wrażliwe]
`ExportJob` trzyma lokalny klucz AES potrzebny do odszyfrowania paczki. Aby przetrwać restart, zapisz `job.resume_state().to_json()` jak sekret i przekaż go do `auth.invoices.export(state=...)`. Nigdy go nie loguj.
:::

## Każdy asynchroniczny obiekt zapisuje swój stan

Eksport nie jest jedyną operacją, która żyje dłużej niż wywołanie, które ją zaczęło. Obiekty wygenerowanego tokena, wniosku o certyfikat, operacji na uprawnieniach i wysłanej faktury zapisują i wznawiają pracę tak samo: `resume_state()` zwraca stan, `to_json()` go zapisuje, a jedna metoda klienta czyta go z powrotem.

| Obiekt | Zapisz przez | Wznów przez |
| --- | --- | --- |
| `ExportJob` | `job.resume_state()` | `auth.invoices.export(state=...)` |
| `GeneratedToken` | `token.resume_state()` | `auth.tokens.generation(state)` |
| `CertificateEnrollment` | `enrollment.resume_state()` | `auth.certificates.enrollment(state)` |
| `PermissionOperation` | `operation.resume_state()` | `auth.permissions.operation(state)` |
| `InvoiceSubmission` | `submission.resume_state()` | `session.submission(state=...)` |

Tylko `ExportResumeState` zawiera sekrety. Pozostałe cztery stany trzymają numer referencyjny KSeF, a stan wysłania faktury dodatkowo wskazuje sesję, do której faktura trafiła. Dlatego ich `to_dict()` i `to_json()` to zwykłe dane, a nie sekret. W szczególności `GeneratedTokenResumeState` nigdy nie zawiera jednorazowej wartości tokena. Ten sekret zapisuj osobno, tak jak przy generowaniu tokena.

Wznowiony obiekt sprawdza ten sam numer referencyjny co oryginalny. Nie wymyśla danych, których nie zapisano, więc wznowiony token nie ma `token`, a wznowiony wniosek o certyfikat nie ma `timestamp`.

## HWM wyznacza synchronizację

Przy automatycznej synchronizacji kluczowy jest znacznik HWM (High Water Mark). Gdy KSeF zwraca `permanent_storage_hwm_date`, informuje, że dane faktur w trwałym zapisie są kompletne do tej daty.

Niezawodna synchronizacja wygląda tak:

```text
ostatni zapisany permanent_storage_date
  -> query/export z restrict_to_permanent_storage_hwm_date=True
    -> lokalny zapis metadanych i treści faktur
      -> zapis permanent_storage_hwm_date jako początku następnego okna
```

Użyj `date_type="permanent_storage"`, gdy celem jest synchronizacja przyrostowa. Użyj `restrict_to_permanent_storage_hwm_date=True`, żeby KSeF ograniczył wynik do bezpiecznej, domkniętej daty.

Przykład zakłada uwierzytelnionego klienta `auth`, zapisany `last_synced_at` oraz Twoje funkcje zapisu `persist_metadata(invoice)` i `save_checkpoint(datetime)`. Zapisuj metadane trwale i usuwaj duplikaty po `ksef_number`. Zapisz granicę dopiero po pomyślnym odczytaniu i zapisaniu wszystkich stron.

```python
from datetime import timedelta

from ksef2.models import InvoiceMetadataParams, InvoicesFilter

filters = InvoicesFilter.for_buyer(
    date_type="permanent_storage",
    date_from=last_synced_at,
    date_to=last_synced_at + timedelta(days=100),
    restrict_to_permanent_storage_hwm_date=True,
)

next_checkpoint = None
for page in auth.invoices.search(
    filters, InvoiceMetadataParams(sort_order="asc")
).responses():
    for invoice in page.invoices:
        persist_metadata(invoice)
    if not page.has_more and not page.is_truncated:
        next_checkpoint = page.permanent_storage_hwm_date

if next_checkpoint is not None:
    save_checkpoint(next_checkpoint)
```

Pusta, zakończona odpowiedź również może zawierać datę synchronizacji. Jeśli KSeF nie zwróci znacznika HWM albo ostatnia odpowiedź jest ucięta, zostaw poprzednią datę. W kodzie asynchronicznym użyj `async for page in pager.responses()`, `page = await pager.first_response()` oraz `page = await pager.page(cursor)`, aby odczytać jedną stronę razem z kursorem.

`responses()` samo przechodzi przez granice stron i ucięte wyniki metadanych. Dla uciętej paczki eksportu kontynuuj od jej `last_permanent_storage_date`, zamiast zakładać, że pokryto całe żądane okno. Przy nakładających się oknach usuwaj duplikaty po `ksef_number`.

Paczka eksportu może też zawierać `_metadata.json`. Pomaga to uzgodnić pobrany XML z wierszami metadanych trzymanymi lokalnie.

## Powiązane strony

- [Wyszukiwanie faktur](../how-to-guides/query-invoices.md): filtry metadanych, strony wyników i oczekiwanie, aż nowe faktury będą widoczne.
- [Pobieranie faktur](../how-to-guides/download-invoices.md): jeden dokument XML albo większa paczka eksportu.
- [Faktura w KSeF](invoice-lifecycle.md): jak łączą się wysyłka, przetwarzanie, zapis i pobieranie.
- [Szyfrowanie](encryption.md): jak publiczne certyfikaty KSeF chronią klucze sesji i eksportów.
