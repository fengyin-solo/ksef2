---
title: Pobierz faktury
description: Pobieraj przetworzony XML faktur bezpośrednio albo przez szyfrowane paczki eksportu ksef2.
---

Użyj `auth.invoices`, gdy potrzebujesz treści faktury po przetworzeniu jej przez
KSeF. Przykłady poniżej zakładają, że masz już uwierzytelnionego klienta
`auth`.

## Pobierz jedną fakturę

Jeśli masz numer KSeF, bezpośrednie pobranie to najkrótsza droga.

```python
from pathlib import Path

ksef_number = "1234567890-20260625-..."

xml_bytes = auth.invoices.download(ksef_number)
Path("invoice.xml").write_bytes(xml_bytes)
```

Jeśli faktura została dopiero wysłana, KSeF może potrzebować czasu, zanim
przetworzony XML będzie dostępny. Podaj `timeout`, a `download()` będzie
odpytywać KSeF, aż dokument będzie dostępny.

```python
xml_bytes = auth.invoices.download(ksef_number, timeout=120.0, poll_interval=2.0)
Path("invoice.xml").write_bytes(xml_bytes)
```

## Zbuduj filtr eksportu

Eksportów używaj do większych pobrań. Eksporty korzystają z `InvoicesFilter`,
czyli tego samego kształtu filtra co zapytania o metadane.

```python
from datetime import datetime, timedelta, timezone

from ksef2.models import InvoicesFilter

now = datetime.now(tz=timezone.utc)

filters = InvoicesFilter.for_buyer(
    date_type="permanent_storage",
    date_from=now - timedelta(days=1),
    date_to=now,
    restrict_to_permanent_storage_hwm_date=True,
)
```

:::tip[Do synchronizacji w tle użyj HWM]
`restrict_to_permanent_storage_hwm_date=True` utrzymuje automatyczne eksporty
w granicy, którą KSeF raportuje jako kompletną. Zapisz
`permanent_storage_hwm_date` dla następnego okna synchronizacji.
:::

## Wyeksportuj wiele faktur

`export()` planuje eksport i zwraca `ExportJob`. Jego `wait()` odpytuje KSeF,
aż paczka będzie gotowa, pobiera i odszyfrowuje części, łączy je i zwraca obiekt
`ExportedInvoices`.

```python
job = auth.invoices.export(filters)
package = job.wait(timeout=300.0)

for ksef_number, xml in package.invoices():
    print(ksef_number, len(xml))

# Sparsowany _metadata.json (lista InvoiceMetadata) albo None, gdy go brak.
metadata = package.metadata

# Szczegóły paczki do synchronizacji przyrostowej.
print(package.package.is_truncated, package.package.permanent_storage_hwm_date)
```

### Zapis do plików

```python
from pathlib import Path

written = package.save(Path("downloads"))
```

`save()` rozpakowuje archiwum i odrzuca każdy wpis, którego ścieżka wychodziłaby
poza katalog docelowy. Surowe bajty ZIP są dostępne jako `package.archive`.

### Wznowienie po restarcie

`job.resume_state()` zwraca `ExportResumeState` z numerem referencyjnym i kluczem
odszyfrowującym paczkę. Zapisz jego JSON, a `export(state=...)` zwróci z powrotem
`ExportJob`, więc `wait()` nadal działa.

```python
job = auth.invoices.export(filters)
saved = job.resume_state().to_json()   # przechowuj jak poświadczenie, nie loguj

# po restarcie
job = auth.invoices.export(state=saved)
package = job.wait(timeout=300.0)
```

Podaj dokładnie jedno z `filters` albo `state`. `to_dict()`, `from_json()` i
`from_dict()` działają jak w stanach sesji; `model_dump()` i `repr()` ukrywają
klucz.

### Zserializuj zakończony eksport

`ExportResumeState` służy do eksportu, który jeszcze się nie skończył. Gdy `wait()`
zwróci wynik, `to_model()` daje snapshot `ExportedInvoicesData` zakończonego
eksportu, który można przekazać innemu procesowi albo innemu wiązaniu językowym, a
`from_model()` zamienia go z powrotem w ten sam obiekt wyniku.

```python
from pathlib import Path

from ksef2.clients import ExportedInvoices
from ksef2.models import ExportedInvoicesData

saved = package.to_model().to_sensitive_json()  # przechowuj jak poświadczenie, nie loguj

# w innym procesie
data = ExportedInvoicesData.model_validate_json(saved)
restored = ExportedInvoices.from_model(data)
for ksef_number, xml in restored.invoices():
    print(ksef_number, len(xml))

written = restored.save(Path("downloads"))
```

`to_sensitive_json()` to jedyny pełny format. Archiwum jest w Base64, a paczka i
metadane zachowują każde pole. Adres części paczki jest podpisany i stanowi
uprawnienie, więc `model_dump()`, `model_dump_json()` i `repr()` go ukrywają: gdy
paczka ma części, to wyjście nadaje się do logów, a nie do przechowywania.
`to_sensitive_dict()` daje tę samą zawartość jako słownik i wymaga takiej samej
ochrony.

`to_model()` czyta archiwum, żeby wypełnić `metadata`, więc rzuca te same błędy co
`metadata`. `from_model()` bierze snapshot taki, jaki jest: `metadata=None` znaczy,
że snapshot nie zawiera metadanych, a pusta lista, że nie ma w nich faktur. Nic nie
jest pobierane ponownie i żaden klucz nie jest potrzebny, bo archiwum jest już
odszyfrowane. `await job.wait()` zwraca tę samą klasę `ExportedInvoices`, więc oba
warianty zapisują i odtwarzają wynik tak samo.

:::note[SDK odszyfrowuje części paczki]
KSeF zwraca zaszyfrowane adresy części paczki. `export()` ładuje poprawny
certyfikat szyfrowania KSeF i planuje eksport z lokalnym materiałem AES, a
`wait()` pobiera części i odszyfrowuje je przed zwróceniem wyniku.
:::

:::caution[Części paczki są tymczasowe]
Adresy paczki wygasają. Zapisz wypakowane XML-e faktur we własnym magazynie i
zachowaj `_metadata.json`, jeśli paczka go zawiera. Gdy KSeF zakończy eksport
błędem albo eksport wygaśnie, `wait()` rzuca `KSeFExportFailedError`.
:::

## Po wysyłce faktur

Trzymaj wysyłkę, przetwarzanie i pobieranie jako osobne fazy.

1. Wyślij XML faktury przez sesję online albo wsadową.

2. Polluj status sesji albo faktury do końcowego zaakceptowanego wyniku.

3. Zapisz zwrócone wartości `ksef_number`.

4. Pobierz jeden przetworzony dokument XML po `ksef_number` albo zbuduj filtr
   eksportu dla większego okna czasu.

## Pobieranie partii przy limitach zapytań

Nie potrzebujesz stałego `sleep` między wywołaniami `download()` ani ponownego
logowania po `401`. SDK stosuje dokładnie nagłówek `Retry-After` do wartości
`RetryConfig.max_retry_after` (domyślnie 120 sekund), ponawia błędy przemijające
i odświeża access token raz po `401`.

Jeden przypadek SDK oddaje z powrotem aplikacji: gdy KSeF każe czekać dłużej niż
sufit. Wtedy `download()` rzuca `KSeFRateLimitError` natychmiast, bez spania, a
`error.retry_after` niesie prawdziwą wartość z nagłówka.

Pojedyncze `download()` nadal blokuje, gdy nagłówek jest na tyle krótki, że SDK
go stosuje. Jeśli KSeF powtarza ten sam `Retry-After`, takie wywołanie
czeka maksymalnie `(max_attempts - 1) * max_retry_after` przed rzuceniem błędu,
czyli domyślnie 240 sekund. Uwzględnij to w długiej partii.

```python
from pathlib import Path

from ksef2 import KSeFRateLimitError

downloads = Path("downloads")
try:
    for ksef_number in ksef_numbers:
        xml_bytes = auth.invoices.download(ksef_number)
        downloads.joinpath(f"{ksef_number}.xml").write_bytes(xml_bytes)
except KSeFRateLimitError as error:
    # KSeF kazał czekać dłużej niż RetryConfig.max_retry_after sekund.
    # SDK nie spał. Zaplanuj pozostałe numery za error.retry_after sekund,
    # zamiast ponawiać w pętli.
    print(f"zwolnij, wróć za {error.retry_after} sekund")
```

Pełne zachowanie dla `429` i `401` oraz listę rzeczy należących do aplikacji
opisuje [Operacje](../reference/operations.md).

## Następne przepływy

- [Wyszukaj faktury](query-invoices.md): Znajdź numery KSeF i metadane przed pobraniem treści faktury.
- [Wyślij faktury](send-invoices.md): Wyślij XML faktury przez sesję online albo wsadową.
- [Zapytania i eksporty](../concepts/querying-and-exports.md): Zrozum metadane, bezpośrednie pobieranie, paczki eksportu i synchronizację HWM.
- [Sprawdź certyfikaty szyfrowania](inspect-encryption-certificates.md): Sprawdź publiczne certyfikaty KSeF używane przez szyfrowane przepływy.


## Eksportuj PDF z weryfikacyjnym kodem QR

Zainstaluj opcjonalne zależności przez `pip install 'ksef2[pdf]'` oraz biblioteki
systemowe wymagane przez [WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).

```python
from ksef2 import Environment
from ksef2.renderers import InvoicePDFExporter, PDFPageSize

exporter = InvoicePDFExporter(
    page_size=PDFPageSize.A4,
    verification_environment=Environment.TEST,
)
output = exporter.export_to_file(
    "invoice.xml",
    "invoice.pdf",
    ksef_number="9999999999-20260215-ABCDEF123456-AB",
)
```

Podaj rzeczywisty numer KSeF nadany tej fakturze. `ksef_number` dodaje lokalnie
wygenerowany kod QR w formacie SVG oraz numer pod kodem. Pominięcie tego argumentu
zachowuje dotychczasowy PDF bez QR. Ten sam argument obsługują `export_from_path()`
i `export_from_string()`. Domyślnym środowiskiem jest `Environment.PRODUCTION`;
dla faktur testowych lub demo wybierz odpowiednio `TEST` lub `DEMO`.
Kod zawiera NIP sprzedawcy, datę wystawienia oraz SHA-256 **oryginalnych bajtów XML**,
zakodowany jako Base64URL bez dopełnienia, zgodnie z
[specyfikacją kodów QR Ministerstwa Finansów](https://github.com/CIRFMF/ksef-docs/blob/main/kody-qr.md).
Do `export_from_string()` przekazuj bajty; tekst jest kodowany jako UTF-8.
Ponowna serializacja faktury zmienia skrót. Eksport nie sprawdza przyjęcia faktury
ani tego, czy podany numer KSeF należy do niej.

Opcja obsługuje faktury z nadanym numerem KSeF. Nie generuje kodu QR certyfikatu
dla trybu offline, nie podpisuje adresów URL ani nie zastępuje własnych układów PDF.

`PDFPageSize` obsługuje `A4`, `A4_LANDSCAPE`, `A3`, `A3_LANDSCAPE`, `LETTER` oraz
`LETTER_LANDSCAPE`. Bez `page_size` obowiązuje dotychczasowe ustawienie arkusza,
zwykle A4 poziomo. Jawny rozmiar strony ma pierwszeństwo przed CSS w `html_overrides`;
pozostałe reguły CSS nadal działają. Szerokie tabele mogą wymagać orientacji poziomej
lub własnego CSS, aby zmieściły się na pionowej stronie.
