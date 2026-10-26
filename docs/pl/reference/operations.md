---
title: Operacje
description: Konfiguracja transportu, ponowienia, limity czasu przepływów, pola logowania i stany, które da się wznowić.
---

Ta strona opisuje zachowania operacyjne ważne w integracji produkcyjnej. To nie jest przewodnik wysyłki ani uwierzytelniania.

## Pola logowania

SDK wysyła zdarzenia strukturalne przez standardowy logger `ksef2`. Domyślnie milczy, więc aplikacja może użyć własnej obsługi i formatowania logów. Aby włączyć renderer konsolowy albo JSON z SDK, wywołaj `ksef2.logging.configure_logging()` przy starcie aplikacji. Zdarzenia korzystają ze standardowych poziomów `DEBUG`, `INFO`, `WARNING` i `ERROR`. SDK nie loguje tokenów, kluczy kryptograficznych ani podpisanych adresów URL.

## TransportConfig

`TransportConfig` działa tylko wtedy, gdy SDK samo tworzy klienta `httpx`. Jeśli przekażesz `http_client`, ten klient ma własne limity czasu HTTP, pulę połączeń, TLS, proxy, `trust_env`, HTTP/2, własny transport i hooki zdarzeń. Jego `base_url` musi pasować do `environment` klienta głównego. Pusty adres bazowy zostanie ustawiony według tego środowiska. Inny adres spowoduje `KSeFArgumentError` przy tworzeniu klienta. Na przykład `Client("test", http_client=httpx.Client())` kieruje do API środowiska testowego, a klient ustawiony na inne środowisko zostanie odrzucony.

```python
from ksef2 import (
    ConnectionPoolConfig,
    RetryConfig,
    TimeoutConfig,
    TlsConfig,
    TransportConfig,
)

TransportConfig(
    timeouts=TimeoutConfig(),
    pool=ConnectionPoolConfig(),
    retry=RetryConfig(),
    tls=TlsConfig(),
    proxy_url=None,
    trust_env=True,
    http2=True,
    auto_refresh_tokens=True,
    error_format="problem-details",
)
```

| Pole | Typ | Domyślnie | Przekazywane do |
| --- | --- | --- | --- |
| `timeouts` | `TimeoutConfig` | `TimeoutConfig()` | `httpx.Timeout` |
| `pool` | `ConnectionPoolConfig` | `ConnectionPoolConfig()` | `httpx.Limits` |
| `retry` | `RetryConfig` | `RetryConfig()` | Warstwa ponowień SDK |
| `tls` | `TlsConfig` | `TlsConfig()` | Weryfikacja TLS w `httpx` |
| `proxy_url` | `str | None` | `None` | Proxy `httpx` |
| `trust_env` | `bool` | `True` | Obsługa zmiennych środowiskowych przez `httpx` |
| `http2` | `bool` | `True` | Flaga HTTP/2 w `httpx` |
| `auto_refresh_tokens` | `bool` | `True` | Odświeżanie tokena dostępu przez klientów uwierzytelnionych, zobacz [Odświeżanie tokena dostępu](#odświeżanie-tokena-dostępu) |
| `error_format` | `Literal["problem-details", "legacy"]` | `"problem-details"` | Nagłówek `X-Error-Format` w żądaniach do API KSeF, zobacz [Format błędów](errors.md#format-błędów) |

`auto_refresh_tokens` i `error_format` nie konfigurują `httpx`, więc działają także wtedy, gdy przekażesz własny `http_client`.

## TimeoutConfig

`TimeoutConfig` dotyczy jednego żądania HTTP. Nie określa, jak długo SDK cyklicznie sprawdza stan przepływu w KSeF.

| Pole | Domyślnie | Znaczenie |
| --- | --- | --- |
| `connect` | `5.0` | Czas na zestawienie połączenia. |
| `read` | `30.0` | Czas oczekiwania na bajty odpowiedzi. |
| `write` | `30.0` | Czas wysyłania bajtów żądania. |
| `pool` | `5.0` | Czas oczekiwania na połączenie z puli. |

## ConnectionPoolConfig

| Pole | Domyślnie | Znaczenie |
| --- | --- | --- |
| `max_connections` | `100` | Maksymalna liczba otwartych połączeń. |
| `max_keepalive_connections` | `20` | Maksymalna liczba bezczynnych połączeń keep-alive. |
| `keepalive_expiry` | `30.0` | Wygaśnięcie bezczynnego keep-alive w sekundach. |

## TlsConfig

| Pole | Domyślnie | Znaczenie |
| --- | --- | --- |
| `verify` | `True` | Przekazywane do `httpx`, chyba że ustawiono `ca_bundle_path`. |
| `ca_bundle_path` | `None` | Ścieżka zestawu certyfikatów CA używana jako wartość `verify` w `httpx`. |

## RetryConfig

`RetryConfig` steruje warstwą ponowień SDK. Obejmuje błędy transportu i odpowiedzi HTTP, które da się ponowić, dla żądań, które wolno powtórzyć.

| Pole | Domyślnie |
| --- | --- |
| `max_attempts` | `3` |
| `initial_delay` | `0.5` |
| `max_delay` | `4.0` |
| `max_retry_after` | `120.0` |
| `backoff_multiplier` | `2.0` |
| `retryable_status_codes` | `(429, 502, 503, 504)` |
| `jitter` | `True` |

Limit opóźnienia wykładniczego wynosi:

```text
min(initial_delay * backoff_multiplier ** (attempt - 1), max_delay)
```

`jitter=True` włącza pełne losowanie: każde ponowienie losuje opóźnienie jednostajnie od zera do limitu z powyższego wzoru. Ustaw `jitter=False`, aby używać tego limitu jako dokładnego opóźnienia. To samo dotyczy ponowień HTTP w funkcjach cyklicznego sprawdzania statusu. Zwykły `poll_interval` zostaje stały. `Retry-After` nie podlega losowaniu.

`max_delay` ogranicza tylko wykładnicze wydłużanie odstępu. Nagłówek `Retry-After` (sekundy albo data HTTP) jest stosowany dokładnie, gdy mieści się w `max_retry_after`. Gdy go przekracza, SDK nie czeka i nie ponawia: od razu się poddaje i zgłasza `KSeFRateLimitError` z prawdziwą wartością z nagłówka, żeby aplikacja mogła przełożyć pracę. Sufit chroni proces przed wielogodzinnym czekaniem na `Retry-After`.

Sufit ogranicza jedno oczekiwanie, nie całe żądanie. Jeśli KSeF powtórzy ten sam `Retry-After` przy każdej próbie, jedno żądanie czeka maksymalnie `(max_attempts - 1) * max_retry_after`, zanim się podda. Przy wartościach domyślnych to 240 sekund, bo SDK czeka 120 sekund dwa razy. Zmniejsz `max_attempts` albo `max_retry_after`, gdy obsługa żądania nie może tyle czekać. `max_attempts` dotyczy jednego żądania HTTP. `wait()` wysyła kolejne żądanie po ponawialnym błędzie serwera, limicie albo błędzie transportu i wlicza opóźnienia oraz czas żądań do swojego `timeout`.

## Żądania, które można ponowić

SDK ponawia tylko takie żądania, które da się bezpiecznie powtórzyć na poziomie transportu.

| Typ żądania | Ponowienie |
| --- | --- |
| `GET` | Można ponowić. |
| `DELETE` | Można ponowić. |
| Większość `POST` | Nie jest ponawiana automatycznie. |
| Wybrane `POST` | Są ponawiane automatycznie, gdy są na liście niżej. |

Grupy `POST`, które można ponowić:

| Obszar | Operacje |
| --- | --- |
| Uwierzytelnianie | challenge; token odświeżający tylko po `429` |
| Faktury | zapytanie o metadane |
| Certyfikaty | zapytanie, pobranie |
| Uprawnienia | zapytania personal, authorization, EU entity, person, subordinate entity i subunit |

Wysyłka faktury jest ponawiana tylko po odpowiedzi `429`, która potwierdza, że KSeF jej nie przetworzył. SDK stosuje `Retry-After`, jeśli mieści się w `max_retry_after`. Nie ponawia wysyłki po `5xx` ani po utracie odpowiedzi. Przy niejednoznacznym wyniku sprawdź `session.list_invoices()` przed ponowną wysyłką. Nadawanie uprawnień, rejestracja certyfikatu, generowanie tokenu, otwieranie sesji interaktywnej i otwieranie sesji wsadowej nie są ponawiane przez warstwę ponowień SDK. Zapisz zwrócone numery referencyjne i wznawiaj przez status, zamiast tworzyć te operacje ponownie w ciemno.

Wymiana jednorazowego tokenu uwierzytelnienia (redeem) też nigdy nie jest ponawiana, bo KSeF zwraca parę tokena dostępu i tokena odświeżającego tylko raz. Utrata odpowiedzi tej wymiany zgłasza `KSeFAuthTokenRedemptionError` z `outcome_ambiguous=True`. Nie powtarzaj tej operacji automatycznie.

Żądanie odświeżenia tokena jest ponawiane wyłącznie po jawnej odpowiedzi `429`. SDK nie ponawia go po błędzie transportu ani po `5xx`, bo token mógł już zostać zmieniony.

## Równoległość pobierania

SDK nie ogranicza liczby równoległych pobrań. Przy pobieraniu wielu faktur ogranicz równoległość w aplikacji, na przykład semaforem, i dobierz limit na podstawie aktualnych limitów KSeF z `auth.limits`. Dla `429` SDK ponawia żądanie skonfigurowaną liczbę razy. Zbyt wiele równoległych operacji może nadal wyczerpać te próby.

## Odświeżanie tokena dostępu

Klienci uwierzytelnieni sami odświeżają token dostępu (`accessToken`), używając tokena odświeżającego (`refreshToken`) z uwierzytelnienia albo z `AuthenticationResumeState`, z którego zostali wznowieni.

| Wyzwalacz | Zachowanie |
| --- | --- |
| Z wyprzedzeniem | Żądanie, które zastaje token dostępu na mniej niż 60 sekund przed `access_token_valid_until`, najpierw go odświeża, a potem idzie z nowym tokenem. |
| Po odpowiedzi | Odpowiedź `401` wywołuje jedno odświeżenie i jedną ponowną próbę tego samego żądania. Drugi `401` jest zgłaszany jako `KSeFAuthError`. |
| Współbieżność | Żądania dzielą jedno odświeżenie: lock w `Client`, `asyncio.Lock` w `AsyncClient`. |
| Inne statusy | `403` i pozostałe błędy nie powodują odświeżenia. |

Jedno odświeżenie to nie jest pełne ponowne uwierzytelnienie. SDK powtarza oryginalne żądanie raz, z odświeżonym tokenem. Jeżeli to powtórzone żądanie znów dostanie `401`, `KSeFAuthError` trafia do aplikacji i to ona decyduje, czy uwierzytelnić się ponownie, czy zgłosić błąd.

`auth.auth_tokens`, `auth.access_token` i `auth.resume_state()` zawsze zwracają bieżące tokeny, więc po dłuższej pracy zapisz `resume_state()` jeszcze raz.

Gdy token odświeżający wygasł albo KSeF go odrzucił, żądanie zgłasza `KSeFAuthenticationExpiredError`, podklasę `KSeFAuthError`. Jedynym wyjściem jest ponowne uwierzytelnienie. Jeśli token odświeżający już wygasł, ale token dostępu jest jeszcze ważny, żądania nadal używają tokena dostępu, dopóki KSeF go nie odrzuci. Błędy transportu i inne błędy wywołania odświeżenia przechodzą dalej bez zmian.

Odświeżanie nigdy nie dotyczy jednorazowej wymiany tokenu uwierzytelnienia ani transferów na podpisany adres URL do zewnętrznego magazynu (przesłanie części sesji wsadowej, pobieranie eksportów). Te ścieżki są osobne i nie niosą tokenu bearer.

Aby zarządzać tokenami samodzielnie, wyłącz to zachowanie. Wygasłe tokeny ujawnią się wtedy jako `KSeFAuthError`, a `client.authentication.refresh()` zostaje dostępne.

```python
from ksef2 import Client, Environment, TransportConfig

client = Client(Environment.PRODUCTION, transport_config=TransportConfig(auto_refresh_tokens=False))
```

## Limity czasu cyklicznego sprawdzania statusu

Funkcje, które czekają na wynik, przyjmują `timeout` i `poll_interval`. To limity czasu całego przepływu, nie limity jednego żądania HTTP. Gdy SDK zgłosi przekroczenie czasu oczekiwania, operacja po stronie KSeF może nadal skończyć się później.

| Przepływ | Wyjątek przekroczenia czasu | Identyfikator w wyjątku |
| --- | --- | --- |
| Cykliczne sprawdzanie uwierzytelniania | `KSeFAuthPollingTimeoutError` | `reference_number` |
| Cykliczne sprawdzanie aktywacji i statusu tokenu | `KSeFTokenStatusTimeoutError` | `reference_number` |
| Czekanie na widoczność metadanych | `KSeFInvoiceQueryTimeoutError` | tylko `timeout` |
| Gotowość pobrania faktury | `KSeFInvoiceDownloadTimeoutError` | `ksef_number` |
| Przetwarzanie faktury w sesji interaktywnej | `KSeFInvoiceProcessingTimeoutError` | `invoice_reference_number` |
| Gotowość paczki eksportu | `KSeFExportTimeoutError` | `reference_number` |
| Nadanie albo cofnięcie uprawnienia | `KSeFPermissionOperationTimeoutError` | `reference_number` |
| Wydanie certyfikatu | `KSeFCertificateEnrollmentTimeoutError` | `reference_number` |
| Zakończenie sesji wsadowej | `KSeFBatchSessionTimeoutError` | `reference_number` |
| Zakończenie sesji interaktywnej | `KSeFOnlineSessionTimeoutError` | `reference_number` |

Po przekroczeniu czasu wznów sprawdzanie zapisanymi identyfikatorami. Lokalny limit czasu nie dowodzi, że zdalna operacja się nie udała.

## Limit żądań

Odpowiedzi KSeF `429` są klasyfikowane jako `KSeFRateLimitError`. Wyjątek udostępnia:

| Atrybut | Znaczenie |
| --- | --- |
| `retry_after` | Liczba sekund z `Retry-After` (forma sekundowa albo data HTTP), jeśli KSeF zwrócił nagłówek. W przeciwnym razie `None`. |
| `status_code` | Zawsze `429`. |
| `response` | Sparsowana treść błędu KSeF, jeśli jest dostępna. |

Dla `429` warstwa ponowień stosuje dokładnie wartość `Retry-After`, gdy mieści się ona w `max_retry_after`, czeka i ponawia do `max_attempts` razy. Gdy nagłówek przekracza sufit, warstwa od razu się poddaje: bez czekania i bez ponawiania. Żądanie kończy się `KSeFRateLimitError` z prawdziwą wartością nagłówka w `retry_after`. Sufit ogranicza każde oczekiwanie z osobna, więc powtarzający się nagłówek może trzymać żądanie przez `(max_attempts - 1) * max_retry_after`, czyli domyślnie 240 sekund.

To nadal należy do aplikacji: `KSeFRateLimitError` oznacza, że SDK już się poddał, więc zaplanuj pracę na później, zamiast ponawiać na oślep. Używaj `retry_after` do planowania pracy w tle. W obsłudze żądania HTTP lepiej zwrócić pracę albo odłożyć ją do ponowienia, niż usypiać to żądanie.

## Sekrety i logowanie

Nie loguj:

- tokenów dostępu;
- tokenów odświeżających;
- wartości tokenów KSeF;
- kluczy prywatnych;
- haseł PEM albo PKCS#12;
- surowego XML faktury, chyba że polityka przechowywania na to pozwala;
- zserializowanego stanu sesji interaktywnej albo wsadowej.

Przydatne pola logów produkcyjnych:

| Pole | Znaczenie |
| --- | --- |
| `environment` | `test`, `demo` albo `production`. |
| `workflow` | Nazwa operacji na poziomie aplikacji. |
| `session_reference_number` | Numer referencyjny sesji interaktywnej albo wsadowej. |
| `invoice_reference_number` | Numer referencyjny faktury w sesji. |
| `ksef_number` | Końcowy numer KSeF po przyjęciu faktury. |
| `operation_reference_number` | Numer referencyjny operacji na tokenie, uprawnieniu, certyfikacie, uwierzytelnieniu albo eksporcie. |
| `sdk_error_code` | `KSeFException.context["code"]`, gdy istnieje. |
| `ksef_code` | Surowy kod błędu KSeF z `KSeFApiError.ksef_code`, gdy istnieje. |
| `trace_id` | Identyfikator śledzenia KSeF z `KSeFApiError.trace_id`. Podaj go, gdy kontaktujesz się z pomocą KSeF. |

## Stan przepływu, który da się wznowić

Większość przepływów KSeF zaczyna się numerem referencyjnym i kończy przez cykliczne sprawdzanie statusu albo późniejsze pobranie. Zapisz numer referencyjny, zanim zaczniesz czekać.

| Przepływ | Zapisz przed czekaniem |
| --- | --- |
| Uwierzytelnianie | numer referencyjny operacji uwierzytelnienia i czas życia tymczasowego tokenu uwierzytelnienia |
| Wysyłka faktury w sesji interaktywnej | numer referencyjny sesji i numer referencyjny faktury |
| Przesłanie sesji wsadowej | numer referencyjny sesji wsadowej, numery referencyjne przesłania, metadane paczki i stan sesji wsadowej, dopóki jest potrzebny |
| Eksport faktur | numer referencyjny eksportu i chroniony materiał obiektu eksportu |
| Generowanie tokenu | numer referencyjny tokenu i zwrócony sekret tokenu |
| Nadanie albo cofnięcie uprawnień | numer referencyjny operacji na uprawnieniach |
| Rejestracja albo unieważnienie certyfikatu | numer referencyjny operacji na certyfikacie albo numer seryjny certyfikatu |

## Powiązane strony

- [Tworzenie i zamykanie klientów](client-lifecycle.md): Konstruktory, własność modułów, zamykanie i błędy cyklu życia.
- [Obsługa błędów](errors.md): Klasy wyjątków SDK, błędy API KSeF i limity czasu.
- [Konfiguracja klienta](../how-to-guides/client-setup.md): Te ustawienia w przykładach klienta synchronicznego i asynchronicznego.
- [Status i UPO](../concepts/status-and-upo.md): Statusy, dokumenty UPO, cykliczne sprawdzanie statusu i lokalne limity czasu.
