---
title: Spis poradników
description: Wybierz poradnik do konkretnego zadania na publicznym API SDK.
---

Ta część jest dla sytuacji, w których znasz już ogólny układ SDK i chcesz wykonać konkretne zadanie w KSeF. Szybki start pokazuje jedną ścieżkę od początku do końca. Poniższe poradniki rozbijają typowe decyzje produkcyjne.

## Konfiguracja

- [Konfiguracja klienta](client-setup.md): wersja synchroniczna albo asynchroniczna, publiczne moduły klienta głównego i moduły po uwierzytelnieniu.
- [Uwierzytelnianie](authenticate.md): certyfikat testowy, token KSeF, certyfikat XAdES, zmienne środowiskowe albo profile zgodne z CLI.
- [Profile](profiles.md): wspólna lokalna konfiguracja ksef2-cli dla uwierzytelniania SDK i `ProfileStore`.

## Faktury

- [Budowanie faktur FA(3)](build-fa3-invoices.md): prosty publiczny model faktury i XML FA(3) budowany łańcuchem metod.
- [Wysyłanie faktur](send-invoices.md): XML FA(3) przez sesję interaktywną albo wsadową i wynik przetwarzania.
- [Pobieranie statusu i UPO](get-status-and-upo.md): status sesji interaktywnej albo wsadowej, lista faktur sesji i dokumenty UPO.
- [Wyszukiwanie faktur](query-invoices.md): filtry metadanych, strony wyników i oczekiwanie, aż nowe faktury będą widoczne.
- [Pobieranie faktur](download-invoices.md): jedna faktura po numerze KSeF albo zaplanowana, zaszyfrowana paczka eksportu.

## Administracja

- [Zarządzanie tokenami](manage-tokens.md): generowanie, lista, sprawdzenie i unieważnienie tokenów KSeF dla automatyzacji.
- [Konfiguracja uprawnień](configure-permissions.md): nadawanie, wyszukiwanie, odbieranie i śledzenie uprawnień KSeF.
- [Zarządzanie certyfikatami](manage-certificates.md): limity, rejestracja, pobranie wydanego certyfikatu i unieważnienie.
- [Zarządzanie limitami](manage-limits.md): odczyt i nadpisanie limitów kontekstu logowania, podmiotu oraz liczby żądań API.

## Narzędzia pomocnicze

- [Podgląd certyfikatów szyfrowania](inspect-encryption-certificates.md): publiczne certyfikaty KSeF używane przy szyfrowaniu faktur i eksportów.
- [Wyszukiwanie dostawców PEPPOL](query-peppol-providers.md): publiczne dane dostawców PEPPOL z klienta głównego.
- [Dane testowe](use-test-data.md): podmioty, uprawnienia i flagi załączników w środowisku testowym oraz dane, które same się sprzątają.
- [Podpisy XAdES](use-xades-helpers.md): wczytanie certyfikatu, certyfikaty testowe i podpis XML.
- [Przechowywanie certyfikatów podpisu](store-signing-certificates.md): pary do podpisu w pamięci albo w plikach szyfrowanych hasłem, wskazywane przez `SigningCertificateRef`.
- [Własny magazyn certyfikatów podpisu](write-signing-certificate-store.md): własny certyfikat podpisu i klucz w pęku kluczy, bazie danych albo menedżerze sekretów.
- [API niskiego poziomu](../reference/low-level/overview.md): bezpośrednie wywołania operacji API przy własnym podpisie, własnym szyfrowaniu albo diagnostyce treści żądań.

:::tip[Wersja synchroniczna i asynchroniczna mają ten sam przepływ]
Klient asynchroniczny ma te same moduły i nazwy metod. Użyj `AsyncClient`, operacje sieciowe poprzedź `await`, a zasoby klienta i sesji zamykaj przez `async with`.
:::

## Typowa kolejność

1. Skonfiguruj środowisko i dane uwierzytelniające.

   Sekrety trzymaj w zmiennych środowiskowych, a ustawienia bez sekretów w lokalnej konfiguracji.

2. Uwierzytelnij się dla wybranego kontekstu logowania.

   Klient uwierzytelniony udostępnia `online_session`, `batch`, `invoices`, `tokens`, `permissions`, `certificates` i inne moduły.

3. Uruchom moduł, który odpowiada za zadanie.

   Publicznych modułów klienta głównego używaj do certyfikatów szyfrowania, wyszukiwania PEPPOL i danych testowych. Modułów uwierzytelnionych używaj do faktur, sesji, tokenów, uprawnień, certyfikatów i limitów.

4. Poczekaj na przetwarzanie w KSeF albo na status operacji.

   Metody wysokiego poziomu potrafią sprawdzać status faktury, zakończenie sesji wsadowej, operacje na uprawnieniach, rejestrację certyfikatu, widoczność w metadanych i gotowość paczki eksportu.

5. Zapisz wynik biznesowy.

   Zapisuj numery KSeF, numery referencyjne sesji i operacji, obiekt eksportu, pobrany XML, numery referencyjne tokenów, numery seryjne certyfikatów i UPO (Urzędowe Poświadczenie Odbioru) zgodnie z zasadami przechowywania w aplikacji.

## Dalszy opis

- [Szybki start](../getting-started/quickstart.md): pierwszy przebieg od wygenerowania faktury, przez wysyłkę i poświadczenie, do pobrania.
- [Operacje](../reference/operations.md): zadania, moduły SDK, sprawdzanie statusu i granice ponawiania.
- [Interfejs publiczny](../reference/public-api.md): stabilne importy i publiczne moduły SDK.
- [API niskiego poziomu](../reference/low-level/overview.md): bezpośrednie wywołania operacji API, gdy przepływ wysokiego poziomu nie wystarcza.
