---
title: Tworzenie i zamykanie klientów
description: Argumenty konstruktorów, własność modułów, zamykanie zasobów i błędy cyklu życia w klientach ksef2.
---

Ta strona opisuje kontrakt klientów głównych i uwierzytelnionych. Pełną sekwencję konfiguracji znajdziesz w poradniku praktycznym.

## Konstruktory klienta głównego

```text
Client(
    environment=Environment.TEST,
    *,
    transport_config=None,
    http_client=None,
)

AsyncClient(
    environment=Environment.TEST,
    *,
    transport_config=None,
    http_client=None,
)
```

| Argument | Typ sync | Typ async | Domyślnie | Znaczenie |
| --- | --- | --- | --- | --- |
| `environment` | `Environment | str` | `Environment | str` | Wymagane | Środowisko KSeF i bazowy adres URL klienta. Nazwy tekstowe nie rozróżniają wielkości liter, na przykład `"test"`. |
| `transport_config` | `TransportConfig | None` | `TransportConfig | None` | | Limity czasu HTTP, pula połączeń, TLS, proxy, HTTP/2 i ponowienia dla klienta HTTP tworzonego przez SDK. |
| `http_client` | `httpx.Client | None` | `httpx.AsyncClient | None` | | Klient HTTP przekazany przez aplikację. Gdy jest podany, aplikacja ma jego ustawienia HTTP i sama go zamyka. |

Gdy `http_client` nie jest podany, SDK tworzy klienta `httpx` z `transport_config` i zamyka go razem z klientem głównym. Przekazany `http_client` musi mieć `base_url` zgodny z wybranym `Environment`. SDK używa tego klienta do żądań i nie podmienia jego `base_url`.

Gdy przekazujesz `http_client`, jego `base_url` musi pasować do `environment`. Pusty `base_url` zostanie ustawiony na adres wybranego środowiska. Inny adres spowoduje `KSeFArgumentError` przy tworzeniu klienta. Dzięki temu kierowanie ruchu i ograniczenia funkcji środowiska testowego zostają zgodne.

## Elementy klienta głównego

| Element | Dostępny na | Zwraca | Uwagi |
| --- | --- | --- | --- |
| `authentication` | `Client`, `AsyncClient` | `AuthClient` / `AsyncAuthClient` | Wejście do tokenu, XAdES, certyfikatu testowego i profili. |
| `encryption` | `Client`, `AsyncClient` | `EncryptionClient` / `AsyncEncryptionClient` | Publiczny odczyt certyfikatów szyfrowania KSeF. |
| `peppol` | `Client`, `AsyncClient` | `PeppolClient` / `AsyncPeppolClient` | Publiczne wyszukiwanie dostawców PEPPOL. |
| `testdata` | `Client`, `AsyncClient` | `TestDataClient` / `AsyncTestDataClient` | Moduł danych testowych tylko dla `Environment.TEST`. Poza tym środowiskiem zgłasza błąd. |
| `raw` | `Client`, `AsyncClient` | `RawClient` / `AsyncRawClient` | Niskopoziomowe, nieuwierzytelnione grupy operacji API. |
| `authenticated(auth_tokens)` | `Client`, `AsyncClient` | `AuthenticatedClient` / `AsyncAuthenticatedClient` | Przestarzała metoda zgodności. Użyj `authentication.resume(AuthenticationResumeState.from_tokens(auth_tokens))`. |
| `close()` | `Client` | `None` | Idempotentnie zamyka synchronicznego klienta HTTP należącego do SDK i unieważnia zapamiętane moduły. |
| `aclose()` | `AsyncClient` | `None` | Idempotentnie zamyka zasoby asynchroniczne i unieważnia zapamiętane moduły. |

`AsyncClient.close()`, `AsyncOnlineSessionClient.close()` i `AsyncBatchSessionClient.close()` od razu zgłaszają `KSeFArgumentError` i zostawiają zasoby otwarte. Użyj `await client.aclose()`, `await session.aclose()` albo `async with`. Metody `close()` są synchroniczne i nie można ich używać z `await`.

Właściwości modułów są zapamiętywane, dopóki klient główny jest otwarty. Po zamknięciu klienta dostęp do modułów i operacje chronione przez warstwę cyklu życia zgłaszają `KSeFClientClosedError`.

## Menedżery kontekstu

| Klient | Zapis | Zamknięcie |
| --- | --- | --- |
| `Client` | `with Client(...) as client:` | `client.close()` przy wyjściu. |
| `AsyncClient` | `async with AsyncClient(...) as client:` | `await client.aclose()` przy wyjściu. |

Menedżer kontekstu zamyka tylko klienta głównego. Sesja interaktywna i sesja wsadowa mają osobny cykl życia. Zamykaj je własnym menedżerem kontekstu albo metodą usługi.

## Elementy klienta uwierzytelnionego

Uwierzytelnienie zwraca klienta uwierzytelnionego związanego z jednym kontekstem logowania i jedną parą tokenów.

| Element | Zwraca | Uwagi |
| --- | --- | --- |
| `auth_tokens` | `AuthTokens` | Modele tokena dostępu i tokena odświeżającego używane przez tego klienta. |
| `access_token` | `str` | Napis tokena dostępu w nagłówku bearer. Traktuj go jak sekret. |
| `refresh_token` | `str` | Napis tokena odświeżającego. Traktuj go jak sekret. |
| `resume_state()` | `AuthenticationResumeState` | Stan uwierzytelnienia do zapisu, z tokenem dostępu i tokenem odświeżającym. |
| `online_session(form_code=... \| state=...)` | Klient sesji interaktywnej | Otwiera jedną sesję interaktywną faktur albo wznawia ją z zapisanego stanu (obiekt albo JSON). Wersja asynchroniczna zwraca menedżer kontekstu, którego trzeba użyć z `await`. |
| `resume_online_session(state)` | Klient sesji interaktywnej | Wycofane. Użyj `online_session(state=...)`. |
| `batch_session(prepared_batch= \| batch_file= \| state=)` | Klient sesji wsadowej | Otwiera sesję wsadową z przygotowanej paczki albo z opisu pliku paczki, albo wznawia ją z zapisanego stanu. `state=` razem z oryginalnym `prepared_batch=` odzyskuje nieudane przesłanie. |
| `open_batch_session(...)` | Klient sesji wsadowej | Otwiera sesję wsadową, gdy wywołujący sam ma metadane szyfrowania. |
| `resume_batch_session(state)` | Klient sesji wsadowej | Wycofane. Użyj `batch_session(state=...)`. |
| `invoices` | `InvoicesService` | Metadane, pobrania bezpośrednie, eksporty, pobieranie paczek i funkcje oczekiwania. |
| `batch` | `BatchService` | Wysokopoziomowy przepływ przygotowania paczki, przesłania, zamknięcia, statusu i UPO. |
| `limits` | `LimitsClient` | Operacje limitów kontekstu logowania, podmiotu i API. |
| `tokens` | `TokensClient` | Generowanie, status, lista i unieważnianie tokenów. |
| `certificates` | `CertificatesClient` | Rejestracja, pobranie, zapytanie, limity i unieważnianie certyfikatów. |
| `sessions` | `SessionManagementClient` | Lista i zamykanie sesji uwierzytelnienia. |
| `invoice_sessions` | `InvoiceSessionsClient` | Historia sesji interaktywnych i wsadowych oraz pobieranie UPO po zapisanych numerach referencyjnych. |
| `permissions` | `PermissionsClient` | Nadawanie, zapytanie, cofanie i status operacji na uprawnieniach. |
| `raw` | `RawAuthenticatedClient` | Niskopoziomowe, uwierzytelnione grupy operacji API. |

`AuthenticationResumeState` jest właścicielem tokena dostępu i tokena odświeżającego w nagłówku bearer. `OnlineSessionResumeState` i `BatchSessionResumeState` nie zawierają danych uwierzytelnienia. Wznawiaj je przez klienta uwierzytelnionego.

Klienci uwierzytelnieni dzielą transport i pamięć certyfikatów klienta głównego. Nie mają osobnego klienta HTTP.

## Własność klienta HTTP

| Układ | Skąd bierze się konfiguracja HTTP | Kto zamyka zasoby HTTP |
| --- | --- | --- |
| `Client(Environment.TEST)` | SDK buduje `httpx.Client` z `TransportConfig`. | `Client.close()` albo wyjście z menedżera kontekstu. |
| `AsyncClient(Environment.TEST)` | SDK buduje `httpx.AsyncClient` z `TransportConfig`. | `await AsyncClient.aclose()` albo wyjście z asynchronicznego menedżera kontekstu. |
| `Client(..., http_client=http)` | Podany `httpx.Client`. | Aplikacja zamyka `http`. |
| `AsyncClient(..., http_client=http)` | Podany `httpx.AsyncClient`. | Aplikacja zamyka `http`. |

Gdy `http_client` jest podany, ustawienia HTTP, takie jak limit czasu, pula połączeń, TLS, proxy, `trust_env`, HTTP/2, własny transport i hooki zdarzeń, pochodzą z tego obiektu. Warstwa ponowień SDK nadal używa `transport_config.retry`.

## Wątki, zadania i serializacja

Używaj osobnego `Client` i jego klientów uwierzytelnionych w każdym wątku roboczym. Bazowy `httpx.Client` obsługuje współbieżne żądania, a `threading.Lock` w SDK szereguje odświeżanie tokenów w obrębie jednego klienta uwierzytelnionego. Ta blokada nie chroni pamięci podręcznej certyfikatów i limitów ani stanu cyklu życia klienta, więc SDK nie gwarantuje bezpieczeństwa całego klienta przy współdzieleniu między wątkami.

`AsyncClient` i jego klienci uwierzytelnieni mogą obsługiwać niezależne żądania wielu zadań w jednej pętli zdarzeń. Odświeżanie tokenów używa `asyncio.Lock`. Nie współdziel ich między wątkami ani pętlami zdarzeń. Przed zamknięciem klienta poczekaj na wszystkie zadania i uzgodnij zmiany pamięci podręcznej limitów albo magazynów certyfikatów.

Każdej sesji interaktywnej albo wsadowej przypisz jednego właściciela albo szereguj jej operacje blokadą aplikacji. Flagi zamknięcia sesji i stan wysyłki nie mają blokady współbieżności. Wysyłanie faktur albo części paczki nie może iść równolegle z zamykaniem sesji ani z ponownym wysyłaniem tej samej paczki.

Limity żądań KSeF obowiązują dla kontekstu logowania niezależnie od liczby klientów, wątków czy zadań, które go używają. Ograniczaj współbieżność łącznie dla tych procesów roboczych.

Klienci z założenia nie obsługują pickle ani głębokiego kopiowania. Stany wznowienia i modele faktur można serializować, więc przekazuj je i twórz klienta w procesie, który je odbiera. Zapisuj stany wznowienia przez `to_json()` i odtwarzaj je przez odpowiedni moduł klienta uwierzytelnionego.

## Błędy cyklu życia

| Błąd | Kiedy jest zgłaszany |
| --- | --- |
| `KSeFClientClosedError` | Klient główny albo moduł chroniony cyklem życia jest użyty po zamknięciu. |
| `KSeFUnsupportedEnvironmentError` | Moduł tylko dla środowiska testowego, obecnie `testdata`, jest użyty poza `Environment.TEST`. |

## Powiązane strony

- [Konfiguracja klienta](../how-to-guides/client-setup.md): Tworzenie klientów w skryptach, zadaniach w tle i zależnościach frameworka.
- [Metody uwierzytelniania](../concepts/authentication-methods.md): Jak klient główny staje się klientem uwierzytelnionym.
- [Operacje](operations.md): Transport, ponowienia, limity czasu i wznawianie.
- [API niskiego poziomu](low-level/overview.md): Operacje zgodne ze schematem, gdy klient przepływu nie wystarcza.
