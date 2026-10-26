---
title: Klient i cykl życia
description: Klient główny, klient uwierzytelniony, obiekty sesji i to, kto zamyka zasoby w ksef2.
---

SDK ma niewielką hierarchię obiektów. Każdy obiekt oznacza inny zakres zarządzania zasobami, a nie tylko inną przestrzeń nazw.

```text
Client albo AsyncClient
  -> publiczne moduły klienta bazowego
  -> authentication
    -> AuthenticatedClient dla jednego kontekstu KSeF
      -> sesje, faktury, tokeny, uprawnienia, certyfikaty, limity
        -> sesja online, sesja batch, uchwyt eksportu
```

Klient główny wybiera środowisko KSeF i trzyma zasoby transportu. Klient uwierzytelniony niesie dostęp do jednego kontekstu logowania. Klienci sesji i obiekt eksportu dotyczą jednego przepływu. Nie używaj ich jako ogólnego wejścia do SDK.

## Model obiektów

| Obiekt | Co ma | Kiedy użyć ponownie |
| --- | --- | --- |
| `Client` / `AsyncClient` | Środowisko, transport HTTP, ponowienia, TLS/proxy i pamięć publicznych certyfikatów. | Gdy operacje mają to samo środowisko i tę samą politykę transportu. |
| Klient uwierzytelniony | Token dostępu (`accessToken`) i token odświeżający (`refreshToken`) dla jednego kontekstu logowania. | Gdy operacje należą do tego samego kontekstu i tych samych danych uwierzytelniających. |
| Klient sesji interaktywnej | Jeden numer referencyjny sesji oraz materiał szyfrowania tej sesji. | Dla jednej wysyłki, a potem zamknij sesję. |
| Klient albo stan sesji wsadowej | Jedno przesłanie paczki oraz materiał szyfrowania paczki. | Do przesłania, zamknięcia, sprawdzania statusu i pobrania UPO. |
| Obiekt eksportu | Numer referencyjny eksportu oraz lokalny materiał AES potrzebny do odszyfrowania części paczki. | Tylko do czasu pobrania i zapisania paczki eksportu. |

Zasada jest prosta. Klienta głównego i uwierzytelnionego używaj ponownie, gdy zgadza się środowisko i kontekst logowania. Sesje i eksporty traktuj jako obiekty jednego przepływu.

## Klient główny

Klient główny jest granicą zasobów HTTP zarządzanych przez SDK. Udostępnia publiczne moduły bez uwierzytelnienia, na przykład odczyt certyfikatów szyfrowania i dostawców PEPPOL. Udostępnia też `authentication`, czyli wejście do uwierzytelnionego kontekstu logowania.

Twórz klienta głównego dla jednego środowiska: testowego, przedprodukcyjnego (Demo) albo produkcyjnego. Nie przełączaj jednego klienta między środowiskami. Jeśli aplikacja łączy się z więcej niż jednym środowiskiem, każde powinno mieć osobnego klienta głównego.

Zamknięcie klienta głównego zwalnia zasoby HTTP, gdy należą one do SDK. Jeśli przekazujesz własnego klienta `httpx`, aplikacja nadal odpowiada za jego zamknięcie.

## Klienci uwierzytelnieni

Uwierzytelnienie tworzy klienta uwierzytelnionego dla jednego kontekstu logowania. Kontekst to zwykle NIP podatnika oraz dane uwierzytelniające, które potwierdzają prawo działania w tym kontekście.

Klient uwierzytelniony udostępnia moduły chronione:

| Moduł | Rodzaj przepływu |
| --- | --- |
| `online_session` | Interaktywna wysyłka faktur. |
| `batch` | Przygotowanie paczki, przesłanie, status i UPO (Urzędowe Poświadczenie Odbioru). |
| `invoices` | Metadane, bezpośrednie pobrania, eksporty i pobieranie paczek eksportu. |
| `tokens` | Generowanie, lista, status i unieważnianie tokenów KSeF. |
| `permissions` | Nadawanie, zapytania, cofanie i status operacji na uprawnieniach. |
| `certificates` | Wniosek, pobieranie, limity i unieważnianie certyfikatów KSeF. |
| `limits` | Odczyt albo zmiana limitów kontekstu logowania, podmiotu i API. |
| `sessions` / `invoice_sessions` | Podgląd sesji uwierzytelnienia i sesji faktur. |

Klienta uwierzytelnionego można przekazywać między funkcjami tego samego przepływu, gdy należą do tego samego kontekstu logowania. Dzięki temu konfiguracja transportu i danych uwierzytelniających zostaje poza logiką operacji.

## Obiekty sesji

Klienci sesji interaktywnej i wsadowej nie są ogólnymi klientami uwierzytelnionymi. Wskazują jedną zdalną sesję KSeF i trzymają lokalny materiał szyfrowania używany przez tę sesję.

Sesję interaktywną zamknij, gdy nie będzie kolejnych faktur. Zamknięcie mówi KSeF, że etap wysyłki się skończył, i pozwala dojść do końcowego statusu oraz do UPO.

Sesja wsadowa też ma moment zamknięcia. KSeF zaczyna przetwarzanie dopiero po przesłaniu zaszyfrowanych części paczki i zamknięciu sesji.

:::caution[Numery referencyjne żyją dłużej niż obiekty Pythona]
Obiekt sesji w Pythonie może zniknąć, gdy KSeF nadal przetwarza dane. Zapisz numer referencyjny sesji, numery referencyjne faktur, numery KSeF i numery referencyjne UPO, jeśli później chcesz sprawdzić status.
:::

## Sync i async

`Client` i `AsyncClient` udostępniają ten sam układ modułów. Klient asynchroniczny zmienia styl wywołań: operacje sieciowe używają `await`, a zamykanie zasobów używa asynchronicznego menedżera kontekstu (`with`). Model pracy z KSeF się nie zmienia.

Wybierz klienta synchronicznego do skryptów, narzędzi CLI, synchronicznych procesów roboczych i aplikacji bez własnej pętli zdarzeń. Wybierz klienta asynchronicznego, gdy aplikacja już jest asynchroniczna, na przykład usługa HTTP albo proces roboczy oparty na `asyncio`.

## Co zapisywać

Nie zapisuj klientów głównych, klientów uwierzytelnionych ani obiektów sesji. Zapisuj identyfikatory i pliki:

- środowisko i nazwę profilu;
- identyfikator kontekstu logowania;
- numer referencyjny sesji;
- numer referencyjny faktury;
- numer KSeF;
- numer referencyjny eksportu i chroniony materiał obiektu eksportu, dopóki eksport jest pobierany;
- bajty XML UPO albo miejsce ich zapisu;
- ostatni zaobserwowany status, na potrzeby wsparcia i audytu.

Obiekty klientów są zasobami procesu. Numery referencyjne i pliki są stanem aplikacji.

## Powiązane strony

- [Konfiguracja klienta](../how-to-guides/client-setup.md): klient synchroniczny i asynchroniczny oraz zamykanie zasobów.
- [Metody uwierzytelniania](authentication-methods.md): token KSeF, XAdES, certyfikat testowy albo profil.
- [Sesje](sessions.md): sesje interaktywne i wsadowe, stan sesji i historia.
- [Tworzenie i zamykanie klientów](../reference/client-lifecycle.md): kto jest właścicielem klienta i kto zamyka zasoby.
