---
title: Migracja do ksef2 1.0
description: Zastąp wycofywane importy i operacje faktur, zachowując działanie dotychczasowego kodu przez całe 1.x.
---

Dawne importy z `ksef2.core`, `ksef2.domain`, `ksef2.infra` i `ksef2.services`
oraz wycofywane nazwy metod działają przez całe 1.x.
Emitują `DeprecationWarning` wskazujące zamiennik. Usunięcie jest możliwe nie
wcześniej niż w 2.0.0 i pozostaje decyzją dla tego wydania. Nowy kod powinien
używać publicznych importów i uchwytów operacji pokazanych poniżej.

## Importy

Przed zmianą, importy używane przez dotychczasowe aplikacje:

```python
from ksef2.core.exceptions import KSeFApiError
from ksef2.core.xades import load_certificate_from_pem
from ksef2.domain.models.invoices import InvoicesFilter
from ksef2.domain.models.pagination import InvoiceMetadataParams
from ksef2.domain.models.session import FormSchema
from ksef2.services.invoices import InvoicesFilter
from ksef2.services.builders import FA3InvoiceBuilder
from ksef2.services.renderers.xslt import InvoiceXSLTRenderer
```

Po zmianie, te same typy i funkcje pochodzą ze wspieranych modułów:

```python
from ksef2 import FormSchema, KSeFApiError
from ksef2.models import InvoicesFilter, InvoiceMetadataParams
from ksef2.xades import load_certificate_from_pem
from ksef2.fa3 import FA3InvoiceBuilder
from ksef2.renderers import InvoiceXSLTRenderer
```

| Dawna ścieżka | Migracja |
| --- | --- |
| `ksef2.domain.models` i jego podmoduły | `ksef2.models`, lub `ksef2.fa3` dla modeli domenowych FA(3) |
| `ksef2.infra.mappers` | `ksef2.raw.mappers` |
| `ksef2.infra.schema.api.spec` / `.supp` | `from ksef2.raw import spec, supp` |
| `ksef2.infra.schema.fa3` i wygenerowane podmoduły | Zachowaj wycofywany alias, jeśli potrzebujesz wygenerowanych klas XSD lub zasobów schemy. Nie każda wygenerowana klasa FA(3) ma publiczny zamiennik. Do budowania faktur używaj `ksef2.fa3.FA3InvoiceBuilder`. |
| `ksef2.services.builders` | `ksef2.fa3` |
| `ksef2.services.renderers.xslt` | `ksef2.renderers` |

Pierwszy import ze starego pakietu ładuje całe jego drzewo implementacji
i rejestruje aliasy do tych samych modułów i klas. Ostrzeżenie pojawia się raz
dla danej rodziny pakietów, także przy bezpośrednim imporcie podmodułu. Nowe
importy nie aktywują aliasów. Opcjonalne zależności PDF pozostają niezaładowane
aż do użycia renderowania.

Zagnieżdżone stare importy działają w czasie wykonania, ale IDE i narzędzia
sprawdzające typy mogą nie rozpoznawać dynamicznych aliasów. Do analizy
statycznej używaj publicznych importów pokazanych powyżej.

## Wysyłka, oczekiwanie i pobieranie UPO

Przykłady zakładają otwartą sesję online `session` i XML faktury w `invoice_xml`.
Przed zmianą, oczekiwanie i pobieranie UPO używają osobnych wywołań z referencją:

```python
response = session.send_invoice(invoice_xml=invoice_xml)
status = session.wait_for_invoice_ready(
    invoice_reference_number=response.reference_number,
    timeout=120.0,
)
upo = session.get_invoice_upo_by_reference(
    invoice_reference_number=response.reference_number,
)
# Alternatywnie: status = session.send_invoice_and_wait(invoice_xml=invoice_xml)
```

Po zmianie, zachowaj uchwyt wysyłki i użyj go do obu operacji:

```python
submission = session.send_invoice(invoice_xml)
status = submission.wait(timeout=120.0)
upo = submission.download_upo()
```

Jeśli masz tylko zapisaną referencję, pobierz UPO przez
`session.download_invoice_upo(reference_number=reference)`.
`wait_for_invoice_ready()` nadal obsługuje dotychczasowe oczekiwanie z referencją.

W kodzie async użyj await osobno dla każdej operacji:

```python
submission = await session.send_invoice(invoice_xml)
status = await submission.wait(timeout=120.0)
upo = await submission.download_upo()
```

## Wyszukiwanie, pobieranie i eksport

Zakładamy uwierzytelnionego klienta `auth`, filtr `filters` typu `InvoicesFilter`
i `params` typu `InvoiceMetadataParams`.
Przed zmianą:

```python
page = auth.invoices.query_metadata(filters=filters, params=params)
for invoice in auth.invoices.all_metadata(filters=filters, params=params):
    xml = auth.invoices.download_invoice(ksef_number=invoice.ksef_number)
for page_items in auth.invoices.query_metadata_pages(filters=filters, params=params):
    print(page_items)
parts = auth.invoices.export_and_download(filters=filters)
archive = b"".join(parts)
```

Po zmianie:

```python
pager = auth.invoices.search(filters, params=params)
page = pager.first_page()
for invoice in auth.invoices.search(filters, params=params):
    xml = auth.invoices.download(invoice.ksef_number)
for page_items in auth.invoices.search(filters, params=params).pages():
    print(page_items)
exported = auth.invoices.export(filters=filters).wait()
archive = exported.archive
```

`query_metadata()` zwraca `QueryInvoicesMetadataResponse`, a `first_page()` zwraca listę
faktur z tej strony. Użyj `pager.first_response()` dla pełnej, typowanej odpowiedzi
z flagami paginacji i `permanent_storage_hwm_date` albo `pager.responses()` dla
wszystkich odpowiedzi. Wyszukiwanie pobiera dane dopiero przy
odczycie wyników. W kodzie async użyj `async for`, await dla `first_page()`,
`first_response()` i `download()`, a dla eksportu `job = await auth.invoices.export(filters=filters)`
i następnie `exported = await job.wait()`.

## Wykrywanie wycofywanego API

Python zwykle ukrywa `DeprecationWarning` w importowanych modułach aplikacji.
Uruchom testy przez `python -W default::DeprecationWarning -m pytest`, aby zobaczyć
użycia, lub `python -W error::DeprecationWarning -m pytest`, aby wymagać migracji.
Aliasy metod mają także oznaczenia PEP 702 dla IDE i analizatorów typów.
Ostrzeżenie importu pojawia się raz dla danej rodziny starych pakietów,
a nie przy każdym imporcie podmodułu.
