---
title: Manifest API
description: Maszynowo czytelny opis publicznego API sync dla generatorów powiązań.
---

`ksef2.bridge.manifest()` opisuje publiczne synchroniczne API jako zwykłe dane
zgodne z JSON. Generator powiązań (bindingów) czyta ten opis zamiast wyprowadzać
API ponownie z `inspect`: nie musi decydować, które elementy są publiczne, które
wycofane ani jak model pydantic i alias `Literal` zamienić na typ w innym języku.

Ten sam dokument zwraca polecenie wiersza poleceń:

```bash
python -m ksef2.bridge manifest > ksef2-manifest.json
```

```python
from ksef2.bridge import FORMAT_VERSION, manifest

document = manifest()
assert document["format_version"] == FORMAT_VERSION
print(len(document["operations"]))
```

Budowanie manifestu jest deterministyczne: to samo publiczne API zawsze daje te
same bajty, więc wynik można zapisać w repozytorium i porównywać w review.

## Co zawiera dokument

| Sekcja | Zawartość |
| --- | --- |
| `format_version` | Wersja tego układu; przeczytaj ją przed parsowaniem czegokolwiek innego. |
| `ksef2_version` | Wersja SDK, które utworzyło dokument. |
| `json_schema_dialect` | Każdy schemat w dokumencie to JSON Schema 2020-12. |
| `conventions` | Jak dokument koduje `bytes`, wartości domyślne, stan i obiekty żywne. |
| `states` | Stan, na którym działa operacja: klient bez uwierzytelnienia, klient uwierzytelniony, sesja online, sesja batch, uchwyt, pager albo wynik. |
| `units` | Jeden wpis na publiczną klasę sync: jak ją osiągnąć, jaki stan ją niesie i które operacje ją tworzą. |
| `operations` | Jeden wpis na każdą niewycofaną publiczną metodę sync. |
| `attributes` | Właściwości klas publicznych: wartość ze schematem albo gałąź do innej jednostki. |
| `excluded` | Elementy publiczne, które nie są operacjami, każdy z powodem. |
| `$defs` | Jeden JSON Schema na nazwany typ, wskazywany lokalnym `$ref`. |

## Operacje

Operacja wskazuje jednostkę i stan, na którym działa, oraz jednoliniowe
podsumowanie z docstringu. Parametry zachowują kolejność z Pythona. Każdy
parametr ma schemat, informację, czy jest wymagany, wartość domyślną jako JSON
oraz opis z docstringu:

```python
from ksef2.bridge import manifest

tokens_list = next(
    operation
    for operation in manifest()["operations"]
    if operation["id"] == "tokens.list"
)
print(tokens_list["state"])
print(tokens_list["returns"]["item"])
```

Wynik operacji opisuje `returns.kind`:

| `kind` | Znaczenie |
| --- | --- |
| `value` | Zwykłe dane, opisane przez `returns.schema`. |
| `none` | Nic nie wraca; schemat to `{"type": "null"}`. |
| `paged` | Kolekcja czytana strona po stronie. `returns.item` to typ elementu, a `returns.schema` to `Page` z elementami i `next_cursor`, który wznawia kolekcję. |
| `handle`, `session`, `client` | Obiekt żywne tworzony przez SDK. `returns.unit` go nazywa, a `returns.schema` to model stanu wznowienia, który go niesie — można ten stan zapisać i odtworzyć obiekt później. |
| `data` | Obiekt opisany modelem danych, na przykład odszyfrowane archiwum stojące za `ExportedInvoices`. |

Uchwyty i sesje są stanowe w Pythonie i bezstanowe w manifeście. Jednostka z
`receiver_state` dodaje ten stan jako parametr `state` z
`origin: "unit_state"`, bo wygenerowane powiązanie nie ma klienta, który trzyma
numer referencyjny. Operacje, które ten stan tworzą, na przykład
`generated_token.resume_state`, go nie przyjmują.

## Typy

Każdy nazwany typ jest zapisany raz w `$defs` i wskazywany lokalnym `$ref`, więc
generator tworzy jeden typ na definicję. Dotyczy to modeli pydantic oraz aliasów
`Literal` z SDK, które stają się nazwanymi enumeracjami, a nie uniami w treści
schematu: `auth.with_token` przyjmuje `context_type`, a jego schemat wskazuje
`$defs.ContextIdentifierType` z dopuszczalnymi wartościami.

Dwa typy z Pythona potrzebują zasady, bo JSON nie ma dla nich odpowiednika:

- `bytes` podróżuje jako string zakodowany base64. Jego schemat ma
  `contentEncoding: "base64"`, a nigdy `format: "binary"`.
- `pathlib.Path` to string z `format: "path"`. Wskazuje plik na maszynie, na
  której działa SDK, więc powiązanie zdalne go nie użyje.

## Elementy wyłączone

Nic nie znika po cichu. Każdy element publiczny, który nie jest operacją, trafia
do `excluded` z maszynowo czytelnym `reason` i zdaniem mówiącym, czego użyć
zamiast niego:

| `reason` | Dlaczego element jest pominięty |
| --- | --- |
| `deprecated` | Oznacza go PEP 702; `detail` cytuje komunikat deprecacji wraz z zastępnikiem. |
| `python_only` | Przyjmuje albo zwraca typ bez JSON Schema, na przykład obiekty `cryptography` w `auth.with_xades` lub żywą sesję przekazywaną do `batch.upload_parts`. |
| `python_iterator` | Zwraca obiekty przez iterację Pythona, na przykład `pager.pages()`. Użyj `page(cursor)` i jego kursora. |
| `lifecycle` | Zarządza obiektem lokalnym, na przykład `client.close()`. |
| `local_filesystem` | Zapisuje pliki, na przykład `exported_invoices.save()`. Zapisz je z `archive`. |
| `sensitive` | To druga ścieżka do sekretu, na przykład `generated_token.to_sensitive_dict()`. |
| `abstract` | To zaczep klasy bazowej z nierozstrzygniętymi parametrami typów. |
| `branch_accessor` | Zwraca inną jednostkę, na przykład `testdata.temporal()`. |

## Czytanie manifestu w innym języku

Dokument to dane, więc odczyta go dowolny parser JSON. `python -m ksef2.bridge
manifest` zapisuje go na standardowe wyjście; `--indent 0` daje jedną zwartą
linię. Samo wywoływanie API nie jest częścią tego dokumentu: manifest opisuje
API, ale go nie wykonuje.

## Powiązane

- [Interfejs publiczny](public-api.md): Które ścieżki importu pozostają stabilne.
- [Cykl życia klienta](client-lifecycle.md): Klienci, sesje i uchwyty opisywane przez jednostki.
- [Operacje](operations.md): Zachowanie timeoutów, ponowień i odpytywania za operacjami.
