---
title: Interfejs publiczny
description: Stabilne ścieżki importu i moduły wewnętrzne w ksef2 1.0.
---

W kodzie aplikacyjnym używaj ścieżek importu z tej strony. To one mają pozostać
stabilne w linii 1.x.

## Stabilne importy aplikacyjne

| Ścieżka importu | Do czego służy |
| --- | --- |
| `ksef2` | Klienci root, konfiguracja środowiska i transportu, `FormSchema`, `__version__` oraz publiczne wyjątki. |
| `ksef2.clients` | Konkretne klasy klientów synchronicznych i asynchronicznych, stabilne typy przepływów `InvoicesService` / `BatchService` oraz typy obiektów operacji, stronicowania i wyniku eksportu (`InvoiceSubmission`, `ExportJob`, `GeneratedToken`, `PermissionOperation`, `CertificateEnrollment`, `ExportedInvoices`, `Pager`, `OperationHandle`) wraz z odpowiednikami asynchronicznymi, do adnotacji typów. |
| `ksef2.models` | Modele żądań, odpowiedzi, filtrów, paginacji (w tym `Page`), tokenów, uprawnień, sesji, sesji wsadowej, eksportu i stanów wznowienia (`ExportResumeState`, `GeneratedTokenResumeState`, `CertificateEnrollmentResumeState`, `PermissionOperationResumeState`, `InvoiceSubmissionResumeState`) oraz obiekt pary certyfikat i klucz (`XAdESCredentials`) i rekordy certyfikatów podpisu (`SigningCertificate`, `SigningCertificateInfo`, `SigningCertificateRef`). |
| `ksef2.fa3` | `InvoiceBuilder` jest kanonicznym builderem FA(3). `FA3InvoiceBuilder` pozostaje wycofywanym aliasem przez 1.x; moduł eksportuje też drafty i typy modeli FA(3). |
| `ksef2.logging` | `configure_logging()` do jawnego włączenia logowania strukturalnego SDK. |
| `ksef2.xades` | Wczytywanie certyfikatów, generowanie certyfikatów testowych, lokalne podpisy XAdES, `LocalSigner` oraz obiekt `XAdESCredentials` przyjmowany przez `with_xades()`. |
| `ksef2.certificate_stores` | Protokoły magazynu certyfikatów podpisu (`SigningCertificateStoreProtocol`, `AsyncSigningCertificateStoreProtocol`), typy rekordów `SigningCertificate` oraz wbudowane adaptery w pamięci i w plikach szyfrowanych hasłem. To nie jest pamięć podręczna certyfikatów szyfrowania KSeF. |
| `ksef2.testdata` | Funkcje tylko dla środowiska testowego, które generują poprawne numery NIP i PESEL (`generate_nip`, `generate_pesel`). |
| `ksef2.profiles` | Funkcje konfiguracji profili zgodnych z `ksef2-cli`. |
| `ksef2.renderers` | Lokalne renderowanie XSLT; renderowanie PDF wymaga również dodatku `[pdf]`. Przy pierwszym użyciu bez niego `InvoicePDFExporter` zwraca czytelny błąd instalacji. |
| `ksef2.raw` | Klienci operacji API niskiego poziomu, modele `spec` i `supp` oraz narzędzia kryptograficzne. |
| `ksef2.raw.mappers` | Publiczne mappery między modelami raw i modelami SDK. |

Wybieraj najwyższy poziom importu, który pasuje do przepływu:

```python
from ksef2 import Client, Environment, FormSchema, KSeFApiError
from ksef2.fa3 import InvoiceBuilder, KsefInvoiceDraft, VatRate
from ksef2.models import InvoicesFilter, InvoiceMetadataParams
from ksef2.renderers import InvoicePDFExporter, InvoiceXSLTRenderer
from ksef2.xades import XAdESCredentials, load_certificate_from_pem
```

Tylko renderowanie PDF wymaga dodatku: zainstaluj `ksef2[pdf]`. Kontrole typów
podczas działania wymagają `ksef2[runtime-checks]`. Pozostałe wymienione wyżej
moduły działają z podstawową instalacją. `ksef2.pdf` nie jest osobnym modułem;
używaj `ksef2.renderers` dla obu rendererów.

SDK domyślnie nie emituje logów i przekazuje rekordy przez standardowy logger `ksef2`. Aplikacja może ustawić własną obsługę logów i poziomy standardowego logowania albo jawnie włączyć renderer konsolowy albo JSON z SDK:

```python
from ksef2.logging import configure_logging

configure_logging(level="INFO", renderer="console")
```

`configure_logging()` służy do konfiguracji aplikacji i SDK nigdy nie wywołuje go samodzielnie. Zdarzenia SDK używają poziomów standardowego logowania i pól strukturalnych. Tokeny, klucze kryptograficzne i podpisane adresy URL nie trafiają do zdarzeń logowania SDK.

## Eksporty pakietu głównego

Pakiet główny `ksef2` jest publicznym wejściem dla typowego kodu aplikacji:

- `Client`, `AsyncClient`;
- `Environment`, `TransportConfig`, `TimeoutConfig`, `RetryConfig`,
  `TlsConfig`, `ConnectionPoolConfig`;
- `FormSchema`;
- `ExceptionCode` i wszystkie publiczne klasy wyjątków `KSeF*`;
- `__version__`.

Dla tych nazw importuj z pakietu głównego, zamiast sięgać do modułów implementacji.

## Stabilność API niskiego poziomu

`ksef2.raw` jest publiczne, ale celowo niskopoziomowe. Ścieżka importu jest stabilna, natomiast postać modeli zgodnych ze schematem idzie za wersją OpenAPI KSeF.

```python
from ksef2.raw import spec
from ksef2.raw.mappers import auth as auth_mapper
```

Nie importuj wygenerowanych modeli OpenAPI z prywatnego pakietu schematów SDK. Używaj `ksef2.raw.spec` i `ksef2.raw.supp`, żeby kod aplikacji został na wspieranym zakresie.

## Ścieżki prywatne

Zasada jest prosta: **ścieżka modułu bez podkreślenia jest publiczna, a każda
ze znakiem podkreślenia jest prywatna.** `ksef2._core`, `ksef2._clients.base` i
`ksef2.raw._facade` są prywatne, podobnie jak każdy moduł poniżej nich.

Moduły prywatne mogą zmieniać się bez wydania głównego. Dawne ścieżki `core`, `domain`, `infra` i `services` zostają jako wycofywane aliasy przez całe 1.x. Zgłaszają ostrzeżenie raz dla danej rodziny pakietów, wskazują zamienniki i używają tych samych modułów oraz klas. Usunięcie jest możliwe nie wcześniej niż w 2.0.0.

Przykłady przed i po zmianie zawiera [poradnik migracji do 1.0](migration-1-0.md).

`scripts/*` to narzędzia repozytorium, nie API pakietu.

## Sekrety i serializacja

Modele, które niosą sekrety albo podpisane adresy URL (token dostępu i token odświeżający, klucze AES i IV, podpisane adresy pobierania i wysyłki, tokeny jednorazowe), ukrywają je w `model_dump()`, `model_dump_json()` i `repr()`. Te metody służą do logowania i wyświetlania. **Nie są formatem trwałego zapisu.** Wyniku z ukrytymi polami nie da się wczytać z powrotem, a jego sprawdzenie może się nie powieść. Na przykład `UpoPage.model_validate(page.model_dump())` zgłasza błąd, bo `download_url` jest wyłączony z wyniku `model_dump()`, ale model go wymaga.

Stan zapisuj i odtwarzaj jawnymi metodami:

- `to_dict()` i `to_json()` w modelach stanu wznowienia
  (`AuthenticationResumeState`, `OnlineSessionResumeState`,
  `BatchSessionResumeState`) eksportują pełne sekrety. Odtworzysz je przez `from_dict()` albo `from_json()`.
- `to_sensitive_dict()` w modelach odpowiedzi z sekretami, takich jak `UpoPage`,
  `GenerateTokenResponse` i `ExportHandle`, eksportuje pola sekretne do
  świadomego, chronionego użycia.
- `to_sensitive_dict()` i `to_sensitive_json()` w `PreparedBatch` eksportują pełne
  zaszyfrowane części i materiał AES do chronionego magazynu. Odtwórz paczkę przez
  `PreparedBatch.from_sensitive_dict()` lub `from_sensitive_json()` i przekaż ją razem
  z zapisanym stanem sesji, aby wznowić przesłanie po restarcie. Zwykły zrzut i `repr` ukrywają bajty paczki i klucze.

`XAdESCredentials` przechowuje załadowane obiekty certyfikatu i klucza prywatnego
cryptography, dostępne przez `certificate` i `private_key`. Nie zachowuje hasła ani
bajtów wejściowych, ukrywa oba obiekty w `repr()` i nie ma schematu Pydantic ani
API serializacji JSON.

`SigningCertificate` przechowuje obiekt `XAdESCredentials` obok metadanych odczytanych z
certyfikatu. Ukrywa go w `repr()`, odmawia `pickle`, `copy.copy()` i `copy.deepcopy()` i
nie ma `model_dump()` ani API JSON: zapisujesz go wyłącznie przez `save()` magazynu.
`SigningCertificateInfo` i `SigningCertificateRef` to metadane bez materiału klucza,
które można serializować i logować.

Wynik tych metod traktuj jak sekret. Przechowuj go zaszyfrowany, nigdy go nie loguj i nie zapisuj w repozytorium.

Zakończone eksporty faktur zapisuj jako zwykłe bajty `ExportedInvoices.archive`.
Odtwórz je przez `ExportedInvoices.from_archive(archive, compression="zip")` albo użyj `compression="tar_gz"` dla TarGz. Metadane są czytane z archiwum przy pierwszym dostępie. Status paczki i adresy pobierania nie są odtwarzane. Chroń odszyfrowane dane faktur w magazynie. Zobacz [Pobieranie faktur](../how-to-guides/download-invoices.md).

## Reguła kompatybilności

Usunięcie albo zmiana nazwy stabilnych importów SDK wymaga wydania głównego. Wycofywane API działa przez całe 1.x. Nowe API może wejść w wydaniu mniejszym. Wydania poprawkowe zachowują udokumentowane działanie, poza poprawkami błędów.

### Zmiany wymuszone przez KSeF

Gdy KSeF usuwa albo zmienia operację API w sposób, którego SDK nie może ukryć, wynikająca z tego zmiana może trafić do wydania mniejszego. Jest opisana w dzienniku zmian pod nagłówkiem „KSeF API changes”, żeby nie pomylić jej z decyzją SDK. Zmiany łamiące, które SDK wprowadza samo, nadal wymagają wydania głównego.

### Polityka wycofywania

Wycofywane API SDK używa PEP 702 `@deprecated` lub ostrzeżenia przy imporcie
aliasu modułu i wskazuje zamiennik. Usunięcie jest decyzją dla 2.0, a nie
zaplanowaną zmianą w 1.x. Komunikat "will be removed no earlier than ksef2
2.0.0" podaje najwcześniejszą wersję, nie obiecuje usunięcia w 2.0.

## Wycofywane API

Te API działają przez całe 1.x. Każde z nich zgłasza `DeprecationWarning` raz na wywołanie i jest oznaczone PEP 702 `@deprecated`, więc narzędzia typów i IDE wskazują miejsca użycia. Może zostać usunięte nie wcześniej niż w ksef2 2.0.0. Python ukrywa `DeprecationWarning` poza `__main__` i uruchamianiem testów, więc uruchom testy z `python -W error::DeprecationWarning`, żeby je znaleźć.

| Wycofane | Użyj zamiast | Usunięte w |
| --- | --- | --- |
| `Client.authenticated(tokens)` i `AsyncClient.authenticated(tokens)` | `client.authentication.resume(AuthenticationResumeState.from_tokens(tokens))` | 2.0.0 lub później |
| `get_state()` w klientach sesji interaktywnej i wsadowej | `resume_state()` | 2.0.0 lub później |
| `BatchSessionClient.access_token` | `AuthenticatedClient.access_token` klienta nadrzędnego | 2.0.0 lub później |
| `dump_state()` w stanie wznowienia sesji | `to_dict()` | 2.0.0 lub później |
| `model_dump_sensitive()` w stanie wznowienia sesji | `to_dict()` | 2.0.0 lub później |
| `model_dump_sensitive_json()` w stanie wznowienia sesji | `to_json()` | 2.0.0 lub później |
| `from_state()` w stanie wznowienia sesji | `from_dict()` | 2.0.0 lub później |
| `BaseSessionState`, `OnlineSessionState`, `BatchSessionState` | `BaseSessionResumeState`, `OnlineSessionResumeState`, `BatchSessionResumeState` | 2.0.0 lub później |
| argument `access_token=` w `from_encoded()` stanu wznowienia sesji (ignorowany) | Zapisuj `AuthenticationResumeState` osobno | 2.0.0 lub później |
| klucz `access_token` w zapisanym stanie wznowienia sesji (ignorowany; stare pliki nadal się wczytują) | Zapisuj `AuthenticationResumeState` osobno | 2.0.0 lub później |
| klucz `auth_timeout` w profilu zapisanym przez ksef2-cli 0.0.2 | `max_poll_attempts` (i opcjonalnie `poll_interval`) | 2.0.0 lub później |
| `send_invoice_and_wait()` i `wait_for_invoice_ready()` w sesji interaktywnej | `send_invoice(...).wait()` | 2.0.0 lub później |
| `get_invoice_upo_by_ksef_number()` i `get_invoice_upo_by_reference()` w sesji interaktywnej | `download_invoice_upo(ksef_number=...)` albo `download_invoice_upo(reference_number=...)` | 2.0.0 lub później |
| `BatchSessionClient.get_upo(upo_reference_number=...)` | `download_upo()` | 2.0.0 lub później |
| `auth.batch.prepare_batch()` i `prepare_batch_from_paths()` | `auth.batch.prepare()` | 2.0.0 lub później |
| `auth.batch.submit_batch()`, `submit_prepared_batch()` i `open_session()` | `auth.batch.submit()` albo `auth.batch_session(...)` | 2.0.0 lub później |
| `auth.batch.get_status()`, `list_invoices()`, `list_failed_invoices()`, `get_upo()` i `wait_for_completion()` (z `session=`) | Te same operacje na kliencie sesji, z `wait()` i `download_upo()` | 2.0.0 lub później |
| `auth.open_batch_session(aes_key=..., iv=..., ...)` | `auth.raw` | 2.0.0 lub później |
| `auth.resume_online_session(state)` i `auth.resume_batch_session(state)` | `auth.online_session(state=...)` i `auth.batch_session(state=...)` | 2.0.0 lub później |
| `auth.invoices.query_metadata()`, `query_metadata_pages()`, `all_metadata()` i `wait_for_invoices()` | `auth.invoices.search(...)` z `.responses()`, `.first_response()`, `.pages()`, `.first_page()` i `.wait()` | 2.0.0 lub później |
| `auth.invoices.download_invoice()` i `wait_for_invoice_download()` | `auth.invoices.download(...)` | 2.0.0 lub później |
| `auth.invoices.schedule_export()`, `get_export_status()`, `wait_for_export_package()`, `fetch_package()`, `fetch_package_bytes()` i `export_and_download()` | `auth.invoices.export(...)`, potem `ExportJob.wait()` | 2.0.0 lub później |
| `auth.tokens.wait_for_activation(reference_number=...)` | `auth.tokens.generate(...).wait()` | 2.0.0 lub później |
| `auth.tokens.status()` | `auth.tokens.get_status()` | 2.0.0 lub później |
| `auth.tokens.list_all()` | `auth.tokens.list(...)` z `.pages()` i `.first_page()` | 2.0.0 lub później |
| `auth.certificates.query()` i `all()` | `auth.certificates.list(...)` | 2.0.0 lub później |
| `client.peppol.query()` i `all()` | `client.peppol.list(...)` | 2.0.0 lub później |
| `auth.sessions.query()` i `all()` | `auth.sessions.list(...)` | 2.0.0 lub później |
| `auth.sessions.close(reference_number=...)` | `auth.sessions.terminate(reference_number)` | 2.0.0 lub później |
| `auth.invoice_sessions.query()` i `all()` | `auth.invoice_sessions.list(session_type, ...)` | 2.0.0 lub później |
| `auth.collective_identifiers.query()` i `query_all()` | `auth.collective_identifiers.list(filters)` | 2.0.0 lub później |
| `auth.collective_identifiers.query_by_ksef_number()` i `query_all_by_ksef_number()` | `auth.collective_identifiers.list_for_invoice(ksef_number)` | 2.0.0 lub później |
| `auth.collective_identifiers.list_all_invoices()` | `auth.collective_identifiers.list_invoices(numbers)` | 2.0.0 lub później |
| `auth.permissions.query_persons()`, `query_entities()`, `query_authorizations()`, `query_eu_entities()`, `query_personal()`, `query_subunits()` i `query_subordinate_entities()` | `auth.permissions.list_persons(query)`, `list_entities(query)`, `list_authorizations(query)`, `list_eu_entities(query)`, `list_personal(query)`, `list_subunits(query)` i `list_subordinate_entities(query)` | 2.0.0 lub później |
| `auth.permissions.get_entity_roles()` | `auth.permissions.list_entity_roles()` | 2.0.0 lub później |
| `auth.permissions.revoke_common()` | `auth.permissions.revoke()` | 2.0.0 lub później |
| `InvoicesClient` i `AsyncInvoicesClient` importowane z `ksef2.clients` | `auth.invoices` (`InvoicesService`) | 2.0.0 lub później |

`session.send_invoice()` zachowuje nazwę i przyjmuje XML pozycyjnie jako `bytes` albo `str`. Zwraca teraz obiekt `InvoiceSubmission`, który udostępnia każde pole dawnego `SendInvoiceResponse`, więc kod czytający `.reference_number` nadal działa.

To samo dotyczy pozostałych operacji, które KSeF kończy asynchronicznie:
`tokens.generate()` zwraca `GeneratedToken` (odczytaj `.token` od razu, `.wait()`
czeka na aktywację), `permissions.grant_*()` i `revoke*()` zwracają
`PermissionOperation`, a `certificates.enroll()` zwraca `CertificateEnrollment`.
Każdy udostępnia wszystkie pola odpowiedzi, którą zastępuje, a
`get_operation_status()` i `get_enrollment_status()` zostają metodami odczytu danych.

`auth.collective_identifiers.list_invoices()` zachowuje nazwę, ale zwraca teraz
`Pager` po fakturach zamiast jednej strony, więc jest jedyną nazwą z powyższej
tabeli, której typ zwracany się zmienia. Iteruj po nim albo wywołaj
`.first_page()`, by wykonać dawne pojedyncze żądanie; `list_all_invoices()` nadal
zwraca strony.

`auth.tokens.list_page()` pozostaje wspierane i nie jest już opisane jako
wycofane: to pojedyncze żądanie przyjmujące własny token kontynuacji KSeF, a
stronicowanie z kursorem go nie zastępuje. Każdy `Pager`, także ten z
`auth.invoices.search(...)`, odpowiada na `.page(cursor)` zwracając `Page` z
`items` oraz `next_cursor`, który zapisujesz, by kontynuować tę kolekcję później.

`InvoiceBuilder.dump_state()` i `from_state()` to osobne API szkiców buildera
i nie są wycofane.

## Powiązane strony

- [Tworzenie i zamykanie klientów](client-lifecycle.md): Klienci główni, klienci uwierzytelnieni i własność cyklu życia.
- [API niskiego poziomu](low-level/overview.md): Operacje zgodne ze schematem we wspieranym zakresie `raw`.
- [Synchronizacja kodu sync/async](../contributing/sync-generation.md): Jak klient synchroniczny powstaje z implementacji asynchronicznej.
