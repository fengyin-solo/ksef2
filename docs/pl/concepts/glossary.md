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

Obiekt SDK z numerem referencyjnym eksportu i lokalnym materiałem potrzebnym do pobrania oraz odszyfrowania paczki.

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

Identyfikator nadany przez KSeF po przyjęciu i przetworzeniu faktury. Zapisuj go, gdy pobierasz fakturę, uzgadniasz dokumenty, obsługujesz zgłoszenia albo pobierasz UPO.

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
