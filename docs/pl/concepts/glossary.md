---
title: Słownik
description: Krótkie definicje pojęć KSeF, SDK, faktur, podpisu i przepływów używanych w dokumentacji ksef2.
---

:::tip[Hasła używają nazw z SDK]
Definicje używają publicznych nazw SDK, takich jak `Environment.TEST`,
`FormSchema.FA3`, `permanent_storage_date` i `reference_number`, a nie
surowych nazw pól z OpenAPI.
:::

## Token dostępu (`accessToken`)

Token JWT uzyskany podczas uwierzytelniania. Klient uwierzytelniony wysyła go w wywołaniach API KSeF. Razem z nim SDK dostaje token odświeżający (`refreshToken`), którym przedłuża ważność tokena dostępu bez ponownego uwierzytelniania.

## Sesja wsadowa

Sesja KSeF do przesłania przygotowanych, zaszyfrowanych części paczki faktur. Przetwarzanie zaczyna się po zamknięciu sesji.

## HWM

Znacznik HWM (High Water Mark). Oznacza, że dane faktur są kompletne do wartości `permanent_storage_date`. Służy do niezawodnej synchronizacji przyrostowej.

## Środowisko przedprodukcyjne (Demo)

Środowisko KSeF o konfiguracji zbliżonej do produkcyjnej, do końcowych testów integracji. Wymaga własnych danych uwierzytelniających, innych niż w środowisku testowym i produkcyjnym. W kodzie: `Environment.DEMO`.

## Środowisko (`Environment`)

Wartość SDK, która wybiera adres bazowy API KSeF: `Environment.TEST`, `Environment.DEMO` albo `Environment.PRODUCTION`.

## Eksport

Asynchroniczne przygotowanie przez KSeF metadanych albo treści faktur zgodnych z filtrami. Wynikiem jest zaszyfrowana paczka do pobrania.

## Obiekt eksportu

Obiekt eksportu (`ExportHandle`) z numerem referencyjnym eksportu i lokalnym materiałem potrzebnym do pobrania oraz odszyfrowania paczki.

## FA(3)

Struktura logiczna faktury. W SDK odpowiada jej `FormSchema.FA3`, używane przy otwieraniu sesji interaktywnej albo wsadowej.

## Klient główny

Nieuwierzytelniony `Client` albo `AsyncClient`. Trzyma środowisko, transport HTTP, publiczne moduły do odczytu i wejście do uwierzytelniania.

## Klient uwierzytelniony

Część klienta zwracana przez uwierzytelnianie. Jest związana z jednym środowiskiem, jednym kontekstem logowania oraz parą tokenów: tokenem dostępu (`accessToken`) i tokenem odświeżającym (`refreshToken`).

## Kontekst logowania

Podmiot, w imieniu którego wykonywane są operacje w KSeF. Wskazuje go identyfikator kontekstu, zwykle NIP, identyfikator wewnętrzny, identyfikator złożony NIP i VAT UE albo identyfikator PEPPOL.

## Metadane

Informacje o fakturze zwracane przez zapytania do API. Metadane nie są dokumentem XML faktury.

## NIP

Polski numer identyfikacji podatkowej. Często służy jako identyfikator podatnika albo identyfikator kontekstu logowania.

## Numer KSeF

Identyfikator nadany przez KSeF po przyjęciu i przetworzeniu faktury. Zapisuj go, gdy pobierasz fakturę, uzgadniasz dokumenty, obsługujesz zgłoszenia albo pobierasz UPO. Nie myl go z numerem faktury, który nadaje sprzedawca.

## Numer referencyjny

Identyfikator nadany przez KSeF operacji, która trwa albo ma stan po stronie systemu: uwierzytelnianie, sesja, wysyłka faktury, eksport, token, operacja na uprawnieniach albo rejestracja certyfikatu.

## `permanent_storage_date`

Data w metadanych faktury. Oznacza moment trwałego zapisu w KSeF i jest podstawą synchronizacji według znacznika HWM.

## Podmiot uwierzytelniający

Osoba, jednostka, odcisk palca certyfikatu albo token, które potwierdzają tożsamość przy wejściu do kontekstu logowania.

## Sesja interaktywna

Sesja KSeF do wysyłania pojedynczych zaszyfrowanych faktur oraz sprawdzania ich statusu i UPO w tej samej sesji. W SDK otwierasz ją metodą `online_session()`.

## PEPPOL

Publiczne wyszukiwanie dostawców na kliencie głównym. Nie jest częścią uwierzytelnionego przetwarzania faktur w KSeF.

## Profil

Nazwana lokalna konfiguracja danych uwierzytelniających, zgodna z `ksef2-cli`. W SDK wybierasz ją przez `with_profile()`.

## Środowisko testowe

Środowisko KSeF do pracy lokalnej, CI, danych testowych i certyfikatów testowych generowanych przez SDK. W kodzie: `Environment.TEST`.

## UPO

Urzędowe Poświadczenie Odbioru. Jest dostępne, gdy sesja albo faktura osiągnie wymagany stan przetworzenia.

## XAdES

Format podpisu cyfrowego XML używany przy uwierzytelnianiu certyfikatem.

## Tryby offline

KSeF rozróżnia wystawianie faktur online, czyli bezpośrednio w systemie, i offline, czyli elektronicznie zgodnie ze wzorem FA(3), z przesłaniem do KSeF w ustawowym terminie. Opis Ministerstwa Finansów z 10.07.2025 jest w [trybach offline](https://github.com/CIRFMF/ksef-docs/blob/main/tryby-offline.md). Terminy prawne mogą się zmienić.

- **offline24**. Wybór podatnika, bez ograniczenia po stronie systemu. Fakturę przesyła się do następnego dnia roboczego po dacie wystawienia.
- **offline**. Ogłoszona niedostępność KSeF. Fakturę przesyła się do następnego dnia roboczego po zakończeniu niedostępności.
- **awaryjny**. Ogłoszona awaria KSeF. Fakturę przesyła się w ciągu 7 dni roboczych od zakończenia awarii. Kolejny komunikat o awarii liczy ten termin od nowa.
- **awaria całkowita**. Fakturę można wystawić papierowo albo elektronicznie poza wzorem FA(3). Po ustaniu awarii nie wysyła się jej do KSeF i nie opatruje kodami QR. Ogłoszenie awarii całkowitej znosi też obowiązek dosłania faktur z pozostałych trybów.

Przy wysyłce offline ustawia się `offlineMode` na `true` zarówno w sesji interaktywnej, jak i wsadowej. W SDK `offline_mode` (`bool`) jest parametrem `auth.batch.prepare()`, `auth.batch.submit()` i `auth.batch_session()`, a nie polem sesji. Odpowiada polu API `offlineMode` i nie rozróżnia tych czterech trybów. Metoda `send_invoice()` sesji interaktywnej nie przyjmuje tego pola i go nie ustawia.

Wizualizacja faktury offline używa dwóch kodów QR. Kod I służy do weryfikacji faktury w KSeF. Kod II potwierdza tożsamość wystawcy.

## Certyfikaty KSeF (typy)

Certyfikat KSeF ma dokładnie jeden typ: `Authentication` albo `Offline`. Nie ma certyfikatu, który łączy obie funkcje. W SDK są to `CertificateTypeEnum.AUTHENTICATION` (wartość `"authentication"`) i `CertificateTypeEnum.OFFLINE` (wartość `"offline"`).

Typ `Authentication` służy do uwierzytelniania w KSeF. Typ `Offline` służy tylko do wystawiania faktur w trybie offline. Potwierdza autentyczność wystawcy i integralność faktury przez kod QR II. Nie uwierzytelnia.

Certyfikat nie niesie uprawnień i nie jest przypisany do kontekstu logowania. Wniosek o certyfikat wymaga uwierzytelnienia podpisem XAdES. Token KSeF nie wystarczy, bo dane do CSR są czytane z certyfikatu użytego przy uwierzytelnieniu.
