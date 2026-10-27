---
title: Działanie SDK
description: Główne obiekty SDK, podział przepływów KSeF i pojęcia używane w dokumentacji.
---

ksef2 opiera się na kilku obiektach, które żyją dłużej, oraz na krótkich przepływach KSeF. Klient główny, `Client` albo `AsyncClient`, wybiera środowisko i trzyma konfigurację transportu. Po uwierzytelnieniu powstaje klient uwierzytelniony dla jednego kontekstu logowania. Sesję otwierasz tylko wtedy, gdy KSeF wymaga pracy w ramach sesji.

Ta część dokumentacji jest po to, żeby zrozumieć przebieg pracy z KSeF, zanim napiszesz kod. Przewodniki praktyczne są po to, gdy znasz już zadanie i potrzebujesz konkretnych wywołań.

**Zobacz też:**

- [Podstawy](clients-and-lifecycle.md): klient główny, klient uwierzytelniony, środowiska i to, kto zamyka zasoby.
- [Uwierzytelnianie i bezpieczeństwo](authentication-methods.md): kontekst logowania, podmiot uwierzytelniający, certyfikaty, szyfrowanie i XAdES.
- [Przepływy faktur](invoice-lifecycle.md): sesje, przetwarzanie faktur, UPO (Urzędowe Poświadczenie Odbioru), zapytania o metadane, pobieranie i eksporty.
- [Administracja](permissions.md): tokeny, operacje na uprawnieniach, certyfikaty, limity i wyszukiwanie PEPPOL.

:::note[Najpierw pojęcia, potem kod]
Strony w tej części wyjaśniają nazwy, podział odpowiedzialności i decyzje. Przewodniki praktyczne pokazują wywołania, które można uruchomić: konfigurację, uwierzytelnianie, wysyłkę faktur, zapytania, pobieranie i administrację.
:::

## Jak SDK odwzorowuje oficjalne API

Oficjalna dokumentacja API KSeF grupuje pracę w obszary: dostęp, wysyłka interaktywna, wysyłka wsadowa, status i UPO, pobieranie faktur, tokeny, uprawnienia, certyfikaty, limity, publiczne certyfikaty szyfrowania i PEPPOL. SDK zachowuje ten podział i udostępnia go jako moduły klienta głównego albo klienta uwierzytelnionego.

| Obszar oficjalnego API | Widok w SDK |
| --- | --- |
| Dostęp | `client.authentication` tworzy klienta uwierzytelnionego dla jednego kontekstu logowania. |
| Wysyłka interaktywna i wsadowa | `auth.online_session()` i `auth.batch_session()` trzymają stan sesji wysyłki. |
| Status i UPO | Klienci sesji oraz `auth.invoice_sessions` sprawdzają przetwarzanie po stronie KSeF i pobierają poświadczenia. |
| Pobieranie faktur | `auth.invoices` odpowiada za zapytania o metadane, eksporty, bezpośrednie pobieranie i paczki. |
| Tokeny, uprawnienia, certyfikaty, limity | Moduły administracyjne klienta uwierzytelnionego. |
| Dane publiczne | Moduły klienta głównego: `client.encryption`, `client.peppol` i dane testowe. |

Moduł `raw` służy do własnej obsługi protokołu, diagnostyki i sprawdzania treści przesyłanych do KSeF. Jest publiczny, ale nie jest typowym miejscem, od którego zaczyna się kod aplikacji.

:::note[Zacznij od modułów wysokiego poziomu]
Większość kodu aplikacji powinna zaczynać od `client.authentication`, a potem korzystać z modułów uwierzytelnionych: `auth.invoices`, `auth.online_session()` albo `auth.batch_session()`. Modułu `raw` używaj tylko wtedy, gdy potrzebujesz kontroli na poziomie protokołu.
:::

## Dane i pliki wejściowe

W całym publicznym SDK wartości `bytes` i `str` oznaczają dane. Obiekt `pathlib.Path` oznacza plik do odczytania. SDK nie traktuje tekstu jako ścieżki do pliku. Aby odczytać plik, przekaż `Path("faktura.xml")`. Na przykład `auth.batch.prepare([xml_text])` dodaje treść XML, a `auth.batch.prepare([Path("faktura.xml")])` odczytuje plik. Jeśli tekst przekazany do przygotowania paczki wskazuje istniejący plik, metoda zgłasza błąd argumentu i podpowiada, co przekazać.

Metody pomocnicze PEM przyjmują treść PEM jako bajty lub tekst, a pliki jako obiekty `Path`. Metody PKCS#12 przyjmują bajty archiwum albo `Path`. Dla zgodności istniejąca ścieżka przekazana jako tekst do metody certyfikatów nadal działa w wersji 1.x i pokazuje ostrzeżenie o wycofaniu. Zamiast tekstu przekaż `Path(...)`. Obsługa ścieżek tekstowych może zostać usunięta nie wcześniej niż w wersji 2.0.0.

## Główne pojęcia

| Pojęcie | Znaczenie w SDK |
| --- | --- |
| Klient główny | Nieuwierzytelniony klient ze środowiskiem i transportem HTTP. |
| Klient uwierzytelniony | Obiekt powiązany z tokenem dostępu (`accessToken`) i tokenem odświeżającym (`refreshToken`) dla jednego kontekstu logowania. |
| Sesja interaktywna | Krótka sesja do wysyłki pojedynczych zaszyfrowanych faktur. W kodzie otwiera ją `online_session()`. |
| Sesja wsadowa | Krótka sesja do wysyłki przygotowanej, zaszyfrowanej paczki faktur. |
| Moduł faktur | Uwierzytelniony moduł do metadanych, eksportów, pobierania pojedynczych faktur i paczek eksportu. |
| Numer referencyjny | Identyfikator zwracany przez KSeF dla sesji, faktur, eksportów, tokenów, uprawnień i innych prac asynchronicznych. |
| Numer KSeF | Identyfikator nadawany po przyjęciu i przetworzeniu faktury przez KSeF. |
| UPO | Urzędowe Poświadczenie Odbioru, dostępne po osiągnięciu wymaganego stanu przetworzenia przez sesję albo fakturę. |

## Co wołać i skąd

Klienta głównego używaj do publicznych zapytań i konfiguracji:

- `client.authentication`, aby rozpocząć uwierzytelnianie.
- `client.encryption`, aby sprawdzić publiczne certyfikaty szyfrowania.
- `client.peppol`, aby wyszukać publiczne dane dostawców PEPPOL.
- `client.testdata` tylko w `Environment.TEST`.

Klienta uwierzytelnionego używaj do pracy zależnej od kontekstu logowania:

- `auth.online_session()` i `auth.batch_session()` do wysyłki.
- `auth.invoices` do metadanych, eksportów i pobierania.
- `auth.tokens`, `auth.permissions`, `auth.certificates` i `auth.limits` do administracji.
- `auth.sessions` i `auth.invoice_sessions` do zarządzania sesjami i historii.

## Powiązane strony

- [Środowiska](environments.md): środowisko testowe, przedprodukcyjne (Demo) albo produkcyjne i trzymanie stanu w tym środowisku.
- [Klient i cykl życia](clients-and-lifecycle.md): klient główny, klient uwierzytelniony, sesje i obiekt eksportu.
- [Metody uwierzytelniania](authentication-methods.md): token KSeF, XAdES, certyfikat testowy albo profil.
- [Sesje](sessions.md): sesje interaktywne, wsadowe, sesje uwierzytelniania i historia sesji faktur.
- [Faktura w KSeF](invoice-lifecycle.md): od wysyłki XML, przez przetwarzanie, do numeru KSeF, pobrania i UPO.
- [API klientów i usług](../reference/api/client-surface.md): wygenerowany opis API, gdy potrzebujesz pełnej listy obiektów i metod.
- [Oficjalny przewodnik API KSeF](https://github.com/CIRFMF/ksef-api): dokumentacja źródłowa pojęć API KSeF 2.0.
