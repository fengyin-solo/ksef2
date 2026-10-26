---
title: Obsługa błędów
description: Hierarchia wyjątków SDK, atrybuty, kody błędów KSeF, wskazówki i klasy przekroczenia czasu oczekiwania.
---

ksef2 zgłasza wyjątki SDK dla każdego błędu, który klasyfikuje, także dla błędów żądań HTTP. Żadna metoda publiczna nie przepuszcza błędu żądania `httpx` do wywołującego. Łap `KSeFException`, żeby obsłużyć każdy błąd SDK, albo węższy `KSeFTransportError`, gdy żądanie nie dało odpowiedzi, której SDK mógłby użyć. Błędy, których SDK nie zgłasza, na przykład `TypeError` z Twoich własnych argumentów, zostają zwykłymi wyjątkami Pythona. Transfery przez podpisany adres URL do zewnętrznego magazynu używają opisanych niżej osobnych wyjątków, a nie klasyfikacji błędów API albo uwierzytelnienia KSeF.

## Lokalna walidacja danych wejściowych

Publiczne modele z `ksef2.models` zgłaszają `KSeFValidationError` dla
niepoprawnych danych wejściowych. Klienci i serwisy poza builderami używają tego
samego wyjątku podczas konwersji argumentów na modele żądań i odtwarzania stanu
z niepoprawnego JSON. Komunikat wskazuje publiczny parametr, a `__cause__`
zachowuje oryginalny błąd Pydantic. Metoda `errors()` udostępnia jego szczegóły.

Nadawanie uprawnień sprawdza długość i sumę kontrolną PESEL oraz wzorzec NIP
z OpenAPI zgodnie z wybranym typem identyfikatora. Nie sprawdza sumy kontrolnej
NIP. `with_test_certificate()` zachowuje dotychczasową kontrolę sumy NIP. Puste listy uprawnień, identyfikatory cofania
i tokeny KSeF zgłaszają `KSeFArgumentError` z podpowiedzią `hint` przed wysłaniem
żądania. Ten wyjątek dziedziczy też po `KSeFValidationError` i `KSeFException`.

`InvoicesFilter(ksef_number=...)` sprawdza format numeru podczas tworzenia
obiektu. Akceptuje 35-znakowe numery KSeF 2.0 oraz 36-znakowe numery KSeF 1.0.

## Rozróżniaj po klasie albo po `ksef_code`

Obsługuj błędy po klasie wyjątku, a dla błędów API KSeF po `ksef_code`. Nigdy nie rozróżniaj po treści komunikatu. Komunikaty są pisane dla ludzi, zawierają aktualne sformułowania KSeF i mogą zmienić się między wydaniami. To samo dotyczy `hint`: pokaż go albo zaloguj, ale nie parsuj.

## Klasy bazowe

| Klasa | Baza | `code` | Główne atrybuty |
| --- | --- | --- | --- |
| `KSeFException` | `Exception` | `SDK_ERROR` | `context`, `hint` |
| `KSeFPollingTimeoutError` | `KSeFException` | `POLLING_TIMEOUT` | `timeout` |
| `KSeFResponseValidationError` | `KSeFValidationError` | `RESPONSE_VALIDATION_ERROR` | `context`, `hint` |
| `KSeFProfileConfigError` | `KSeFValidationError` | `PROFILE_CONFIG_ERROR` | `context`, `hint` |
| `KSeFSessionFailedError` | `KSeFSessionError`, `KSeFOperationFailedError` | `SESSION_FAILED` | `reference_number`, `session_status_code`, `description`, `details`, `status` |
| `KSeFTokenActivationFailedError` | `KSeFApiError`, `KSeFOperationFailedError` | `TOKEN_ACTIVATION_FAILED` | `reference_number`, `token_status` |
| `KSeFOperationFailedError` | `KSeFException` | `OPERATION_FAILED` | Wspólna baza błędów operacji zakończonych niepowodzeniem. |
| `KSeFNotFoundError` | `KSeFApiError` | `NOT_FOUND` | `status_code`, `ksef_code`, `details`, `response` |
| `KSeFServerError` | `KSeFApiError` | `SERVER_ERROR` | `status_code`, `ksef_code`, `details`, `response` |
| `KSeFTransportError` | `KSeFException` | `TRANSPORT_ERROR` | `method`, `path`, `outcome_ambiguous` |
| `KSeFApiError` | `KSeFException` | `API_ERROR` | `status_code`, `ksef_code`, `exception_code`, `trace_id`, `details`, `response` |
| `KSeFNotReadyError` | `KSeFApiError` | `NOT_READY` | Atrybuty błędu API |
| `KSeFAuthError` | `KSeFApiError` | `AUTH_ERROR` | Atrybuty błędu API |
| `KSeFPermissionDeniedError` | `KSeFApiError` | `PERMISSION_DENIED` | Atrybuty błędu API |
| `KSeFAuthenticationExpiredError` | `KSeFAuthError` | `AUTHENTICATION_EXPIRED` | Atrybuty błędu API |
| `KSeFRateLimitError` | `KSeFApiError` | `RATE_LIMIT_ERROR` | `retry_after` oraz atrybuty błędu API |
| `KSeFCertificateStoreError` | `KSeFException` | `CERTIFICATE_STORE_ERROR` | `operation`, `reference`, `outcome_ambiguous` |
| `KSeFExternalTransferError` | `KSeFTransportError` | `EXTERNAL_TRANSFER_ERROR` | `operation`, `host`, `reference_number`, `part_ordinal`, `status_code`, `outcome_ambiguous` |
| `KSeFBatchUploadError` | `KSeFExternalTransferError` | `BATCH_UPLOAD_ERROR` | Atrybuty transferu zewnętrznego oraz `recovery_state()` i `recovery_prepared_batch()` |
| `KSeFInvoiceRejectedError` | `KSeFSessionError` | `INVOICE_REJECTED` | `invoice_reference_number`, `invoice_status_code`, `description`, `details`, `extensions`, `status` |

Łap węższe podklasy przed `KSeFException`, gdy workflow ma konkretną akcję
odzyskiwania.

```python
from ksef2 import (
    KSeFApiError,
    KSeFException,
    KSeFNotReadyError,
    KSeFRateLimitError,
    KSeFTransportError,
)

try:
    result = auth.invoices.query_metadata(filters=filters)
except KSeFRateLimitError as exc:
    retry_after = exc.retry_after
except KSeFNotReadyError:
    ...  # KSeF jeszcze nie skończył; poczekaj i zapytaj ponownie
except KSeFApiError as exc:
    if exc.ksef_code == 21405:
        details = exc.details
    trace_id = exc.trace_id  # podaj go, kontaktując się z pomocą KSeF
except KSeFTransportError as exc:
    if exc.outcome_ambiguous:
        ...  # KSeF mógł przyjąć żądanie; sprawdź rezultat przed ponowną wysyłką
except KSeFException as exc:
    context = exc.context
```

## Klasy wyjątków SDK

| Klasa | `code` | Kiedy jest zgłaszana |
| --- | --- | --- |
| `KSeFPollingTimeoutError` | `POLLING_TIMEOUT` | Baza dziesięciu przekroczeń czasu oczekiwania na wynik przepływu. |
| `KSeFResponseValidationError` | `RESPONSE_VALIDATION_ERROR` | Nieprawidłowa odpowiedź API lub metadane eksportu. |
| `KSeFProfileConfigError` | `PROFILE_CONFIG_ERROR` | Nieprawidłowa konfiguracja profilu, brak sekretów lub błąd wczytywania poświadczeń. |
| `KSeFSessionFailedError` | `SESSION_FAILED` | Przetwarzanie sesji interaktywnej lub wsadowej zakończyło się błędem. |
| `KSeFTokenActivationFailedError` | `TOKEN_ACTIVATION_FAILED` | Aktywacja wygenerowanego tokenu nie powiodła się lub token został unieważniony. |
| `KSeFNotFoundError` | `NOT_FOUND` | Brak zasobu według kodu KSeF lub HTTP 404/410. |
| `KSeFServerError` | `SERVER_ERROR` | Sesja tymczasowo niedostępna lub HTTP 5xx. |
| `KSeFClientClosedError` | `CLIENT_CLOSED` | Klient główny albo klient sesji użyty po zamknięciu. |
| `KSeFUnsupportedEnvironmentError` | `UNSUPPORTED_ENVIRONMENT` | Moduł albo przepływ tylko dla środowiska testowego użyty poza `Environment.TEST`. |
| `KSeFValidationError` | `VALIDATION_ERROR` | Niepoprawne dane wejściowe SDK, błędna treść odpowiedzi, błędny profil albo błędne argumenty sesji interaktywnej albo wsadowej. |
| `KSeFArgumentError` | `ARGUMENT_ERROR` | Wywołanie łączy argumenty niedozwolone przez SDK, na przykład oba albo żaden z `form_code` i `state`. Podklasa `KSeFValidationError`, `TypeError` i (przez `KSeFValidationError`) `ValueError`. |
| `KSeFInvoiceRenderingError` | `INVOICE_RENDERING_ERROR` | Błędy opcjonalnego renderowania XSLT/PDF. |
| `KSeFEncryptionError` | `ENCRYPTION_ERROR` | Błąd szyfrowania tokenu, klucza symetrycznego, faktury albo deszyfrowania. |
| `KSeFSessionError` | `SESSION_ERROR` | Naruszenie stanu sesji, na przykład użycie zamkniętej sesji. Klasa bazowa `KSeFInvoiceRejectedError`. |
| `KSeFInvoiceRejectedError` | `INVOICE_REJECTED` | KSeF skończył przetwarzanie faktury z sesji interaktywnej i ją odrzucił (`InvoiceSubmission.wait()`). |
| `KSeFExportFailedError` | `EXPORT_FAILED` | KSeF zakończył eksport faktur bez paczki: eksport się nie powiódł, został anulowany przez system albo wygasł (`ExportJob.wait()`). Podklasa `KSeFOperationFailedError`. |
| `KSeFPermissionOperationFailedError` | `PERMISSION_OPERATION_FAILED` | KSeF zakończył nadanie albo cofnięcie uprawnienia bez jego zastosowania (`PermissionOperation.wait()`). Podklasa `KSeFOperationFailedError`. |
| `KSeFCertificateEnrollmentFailedError` | `CERTIFICATE_ENROLLMENT_FAILED` | KSeF odrzucił, anulował albo nie zrealizował rejestracji certyfikatu (`CertificateEnrollment.wait()`). Podklasa `KSeFOperationFailedError`. |
| `KSeFCertificateStoreError` | `CERTIFICATE_STORE_ERROR` | Błąd bazowy magazynu certyfikatów podpisu (`ksef2.certificate_stores`). Niesie `operation`, `reference` i `outcome_ambiguous`. |
| `KSeFCertificateStoreNotFoundError` | `CERTIFICATE_STORE_NOT_FOUND` | Pod wskazanym `reference` nie ma zapisanego certyfikatu podpisu. Podklasa `KSeFCertificateStoreError`. |
| `KSeFCertificateStoreConflictError` | `CERTIFICATE_STORE_CONFLICT` | Pod tym wskazaniem zapisany jest już inny rekord. Podklasa `KSeFCertificateStoreError`. |
| `KSeFCertificateStoreAccessError` | `CERTIFICATE_STORE_ACCESS` | Magazyn odrzucił poświadczenia albo uprawnienia wywołującego. Podklasa `KSeFCertificateStoreError`. |
| `KSeFCertificateStoreUnavailableError` | `CERTIFICATE_STORE_UNAVAILABLE` | Magazyn jest niedostępny albo nie przyjął rekordu. Podklasa `KSeFCertificateStoreError`. |
| `KSeFCertificateStoreMaterialError` | `CERTIFICATE_STORE_MATERIAL` | Zapisany certyfikat albo klucz jest uszkodzony, nieobsługiwany, nie da się go odszyfrować albo nie zgadza się ze wskazaniem. Podklasa `KSeFCertificateStoreError`. |
| `KSeFAuthTokenRedemptionError` | `AUTH_TOKEN_REDEMPTION_ERROR` | Jednorazowa wymiana tokenu uwierzytelnienia nie dostała użytecznej odpowiedzi i mogła się powieść. Podklasa `KSeFTransportError`. |
| `KSeFExternalTransferError` | `EXTERNAL_TRANSFER_ERROR` | Przesłanie albo pobranie przez podpisany adres URL zostało odrzucone albo nie dało użytecznej odpowiedzi. |
| `KSeFBatchUploadError` | `BATCH_UPLOAD_ERROR` | Przesłanie części sesji wsadowej nie powiodło się, ale chroniony stan odzyskiwania zostaje dostępny. |
| `NoCertificateAvailableError` | `NO_CERTIFICATE_AVAILABLE` | Brak poprawnego certyfikatu dla podpisu albo szyfrowania. |
| `KSeFMetadataPaginationError` | `METADATA_PAGINATION_ERROR` | Paginacja metadanych nie może bezpiecznie kontynuować. |

`KSeFAuthTokenRedemptionError.outcome_ambiguous` ma zawsze wartość `True`. Nie ponawiaj wymiany tokenu: KSeF mógł już zużyć tymczasowy token uwierzytelnienia, mimo że do wywołującego nie dotarła użyteczna odpowiedź.

`KSeFCertificateStoreError.outcome_ambiguous` ma wartość `True` tylko wtedy, gdy
magazyn nie potrafi powiedzieć, czy zapis został wykonany. Przed ponownym zapisem
wywołaj `load()` albo `list()`. `operation` to nazwa metody magazynu, która się nie
powiodła, a `reference` ma postać `"<environment>:<fingerprint_sha256>"`; oba pola
trafiają też do `context`.

`KSeFValidationError` dziedziczy również po `ValueError`, aby zachować zgodność
z kodem obsługującym wcześniejsze błędy walidacji. Gdy przyczyną jest walidacja
Pydantic, wyjątek udostępnia `.errors()` i zachowuje oryginalny wyjątek w
`__cause__`. `KSeFArgumentError` dziedziczy również po `TypeError`. HTTP 401
zgłasza `KSeFAuthError`, a HTTP 403 zgłasza `KSeFPermissionDeniedError`. Kod,
który wcześniej obsługiwał HTTP 403 przez `except KSeFAuthError`, powinien teraz
obsługiwać `KSeFPermissionDeniedError` albo `KSeFApiError`.

## Atrybuty błędu transportu

`KSeFTransportError` jest zgłaszany, gdy żądanie nie dało odpowiedzi, której SDK mógłby użyć: nie dotarło do KSeF, odpowiedzi nie dało się zdekodować albo łańcuch przekierowań został porzucony. Żądania, które da się ponowić, są ponawiane najpierw, więc ten błąd oznacza wyczerpane próby albo żądanie, którego SDK nie ponawia. Powtarzamy tylko błędy, których KSeF mógł nie zobaczyć, więc błąd dekodowania albo przekierowania jest zgłaszany po jednej próbie. Samo zgłoszenie tego błędu nie zmienia liczby prób.

| Atrybut | Typ | Znaczenie |
| --- | --- | --- |
| `method` | `str \| None` | Metoda HTTP błędnego żądania albo `None`, gdy SDK jej nie zna. |
| `path` | `str \| None` | Ścieżka URL żądania bez userinfo, hosta, zapytania i fragmentu. Podpisane adresy URL magazynu nigdy nie trafiają do tego pola. |
| `cause_type` | `str \| None` | Typ oryginalnego błędu transportu albo `None`. |
| `cause_message` | `str \| None` | Bezpieczne podsumowanie przyczyny; adresy URL i query są usuwane. |
| `outcome_ambiguous` | `bool` | `True`, gdy żądanie mogło dotrzeć do KSeF. Błędy połączenia przed wysłaniem mają wartość `False`; utrata odpowiedzi dla niebezpiecznego żądania ma wartość `True`. |

Gdy wynik wysyłki jest niejednoznaczny, sprawdź status przed ponowną próbą.
Dla faktury online `session.list_invoices()` może pokazać, czy KSeF ją zapisał.
Pole `hint` błędu podaje ten sposób odzyskiwania.

Oryginalny wyjątek `httpx` pozostaje dostępny jako `__cause__`. Komunikat i
`str(exc)` zawierają metodę żądania, oczyszczoną ścieżkę, typ przyczyny i jej
bezpieczne podsumowanie. `repr(exc)` i `context` nie zawierają przyczyny, treści
żądania, tokenu bearer ani podpisanego URL-a. `cause_message` może mieć wartość
`None`, gdy SDK utworzyło wyjątek bez pierwotnego błędu transportu.

```python
from ksef2 import KSeFException, KSeFTransportError

try:
    providers = client.peppol.list().first_page()
except KSeFTransportError as exc:
    print(f"{exc.method} {exc.path} nie dało użytecznej odpowiedzi")
    if exc.outcome_ambiguous:
        ...  # sprawdź, co zapisał KSeF, zanim wyślesz coś ponownie
except KSeFException as exc:
    print(exc)  # każdy pozostały błąd SDK
```

## Atrybuty transferu zewnętrznego i odzyskiwanie sesji wsadowej

Odpowiedzi z magazynu na podpisanym adresie URL nie są odpowiedziami API KSeF. Na przykład błąd `403` tego magazynu zgłasza `KSeFExternalTransferError`, a nie `KSeFAuthError`. Komunikat i `context` zawierają wyłącznie oczyszczony host, operację, numer referencyjny przepływu, numer części, status i flagę niejednoznaczności. Nie zawierają podpisanego adresu URL.

| Atrybut | Typ | Znaczenie |
| --- | --- | --- |
| `operation` | `Literal["upload", "download"]` | Zewnętrzny transfer, który się nie powiódł. |
| `host` | `str` | Host magazynu bez ścieżki, zapytania i podpisu. |
| `reference_number` | `str` | Numer referencyjny eksportu albo przepływu sesji wsadowej. |
| `part_ordinal` | `int` | Jednobazowy numer części paczki. |
| `status_code` | `int | None` | Status odpowiedzi storage albo `None`, gdy odpowiedź nie dotarła. |
| `outcome_ambiguous` | `bool` | `True`, gdy przesłanie mogło dotrzeć do magazynu mimo utraty odpowiedzi. |

`KSeFBatchUploadError.recovery_state()` celowo ujawnia wrażliwy `BatchSessionResumeState` potrzebny do odzyskania przepływu, a `recovery_prepared_batch()` ujawnia dokładną paczkę `PreparedBatch`, której użyło nieudane przesłanie, także tę przygotowaną wewnątrz `submit()`. Oba przekazujesz do `auth.batch_session(state=..., prepared_batch=...)`. Żaden z nich nie trafia do komunikatu ani do `context`, bo zawierają materiał szyfrujący, a stan także podpisane adresy URL. Zapisuj je wyłącznie w chronionym magazynie danych uwierzytelniających i nie ponawiaj przesłania automatycznie, gdy `outcome_ambiguous` ma wartość `True`.

Oryginalny błąd `httpx` pozostaje dostępny przez `__cause__`. Nie loguj go bez
kontroli, ponieważ surowa diagnostyka HTTP może zawierać podpisany URL.

## Atrybuty błędu API

`KSeFApiError` jest zgłaszany dla sparsowanych odpowiedzi KSeF 4xx i 5xx. Osobne podklasy są używane dla błędów uwierzytelnienia i uprawnień, limitu żądań oraz zasobów, których KSeF jeszcze nie udostępnił.

| Atrybut | Typ | Znaczenie |
| --- | --- | --- |
| `status_code` | `int` | Status HTTP zwrócony przez KSeF. |
| `ksef_code` | `int | None` | Surowy kod błędu KSeF, niezależnie od wartości. `None`, gdy odpowiedź nie zawierała kodu. Rozróżniaj błędy według tego pola. |
| `exception_code` | `ExceptionCode` | Ten sam kod jako enum, gdy SDK go zna; w przeciwnym razie `UNKNOWN_ERROR`. Zachowany dla zgodności. |
| `trace_id` | `str | None` | Identyfikator śledzenia żądania w KSeF, gdy KSeF go zwrócił. |
| `details` | `list[str]` | Komunikaty szczegółowe dołączone przez KSeF; pusta lista, gdy ich brak. |
| `hint` | `str | None` | Co zrobić dalej, gdy SDK zna przyczynę. |
| `response` | `BaseModel | None` | Sparsowana treść błędu KSeF, gdy parsowanie się udało. |

Te same wartości są dostępne w `context`: `status_code`, `ksef_code`,
`trace_id`, `details` oraz `hint` (jeśli jest).

Używaj `response.model_dump()` albo `response.model_dump_json()` do
strukturalnych diagnostyk, gdy `response` nie jest `None`.

### Format komunikatu

Każdy błąd API KSeF ma ten sam format, niezależnie od postaci odpowiedzi (`application/problem+json`, starsza treść `exception`, inne JSON-y, tekst albo pusta odpowiedź). SDK wybiera parser po nagłówku `Content-Type` odpowiedzi:
`application/problem+json` jest czytany jako Problem Details, `application/json`
jako starsza treść (poza 401, który KSeF wysyła jako Problem Details oznaczony
`application/json`), a wszystko inne staje się krótkim fragmentem:

```text
KSeF rejected <METODA> <ścieżka> (HTTP <status>, KSeF code <kod>): <opis>
Details: <szczegół>; <szczegół>
Trace ID: <identyfikator śledzenia>
Hint: <wskazówka>
```

Fragment `KSeF code` jest pomijany, gdy odpowiedź nie ma kodu, a linie `Details`,
`Trace ID` i `Hint` pojawiają się tylko wtedy, gdy jest co pokazać. Domyślnie
SDK wysyła `X-Error-Format: problem-details` w każdym żądaniu do API KSeF
(zobacz [Format błędów](#format-błędów)), więc KSeF zwraca błędy 400 i 429 jako
`application/problem+json`, a `trace_id` jest ustawiony w każdym błędzie API
zwróconym w tym formacie. (401, 403 i 410 zawsze są Problem Details.) Nagłówek
nie jest wysyłany na podpisane adresy URL magazynu. Treść odpowiedzi nie wchodzi do
komunikatu; zostaje w `response`. Gdy treść nie jest rozpoznawalnym błędem,
opisem jest krótki, skrócony fragment tej treści.

### Format błędów

`TransportConfig.error_format` wybiera format, o który SDK prosi KSeF:

| Wartość | Wysyłany nagłówek | Błędy 400 i 429 |
| --- | --- | --- |
| `"problem-details"` (domyślnie) | `X-Error-Format: problem-details` | `application/problem+json`: `trace_id` jest ustawiony, a `response` to `BadRequestProblemDetails` / `TooManyRequestsProblemDetails` |
| `"legacy"` | brak | `application/json`: `trace_id` to identyfikator śledzenia zawarty w `serviceCode` (brak przy 429), a `response` to `ExceptionResponse` / `TooManyRequestsResponse` |

401, 403 i 410 zawsze są Problem Details. SDK czyta oba formaty tak samo, więc
`ksef_code`, `details`, klasa i wskazówka się nie zmieniają; zmienia się tylko
typ `response`, a `trace_id` pochodzi z `serviceCode` zamiast z `traceId`
(starszy błąd 429 nie ma żadnego z nich). Używaj `"legacy"` tylko wtedy, gdy
Twój kod czyta `response` i oczekuje starszych modeli:

```python
client = Client(Environment.PRODUCTION, transport_config=TransportConfig(error_format="legacy"))
```

Treść niezgodna ze swoim modelem w specyfikacji KSeF (brak wymaganego pola,
wartość poza limitami specyfikacji) albo Problem Details ze statusem, dla
którego specyfikacja nie ma modelu, na przykład 500, jest czytana bez modelu:
`response` to `None`, ale kod KSeF, opis, szczegóły i identyfikator śledzenia
nadal pochodzą z treści, więc klasa i wskazówka się nie zmieniają.

Przykład: pobranie UPO faktury, którego KSeF jeszcze nie wystawił:

```text
KSeF rejected GET /sessions/online/S1/invoices/I1/upo (HTTP 400, KSeF code 21178): Nie znaleziono UPO dla podanych kryteriów.
Details: UPO o numerze referencyjnym I1 nie zostało znalezione.
Trace ID: 0b1f6a7c-4d2e-4a53-9a6e-3f2b9d1c8e11
Hint: KSeF has no UPO for this yet. Call `wait()` on the invoice submission or the session first, then call `download_upo()` or `download_invoice_upo()` again. If `wait()` raises `KSeFInvoiceRejectedError`, KSeF rejected the invoice and will never issue a UPO for it.
```

Opis i szczegóły pochodzą z KSeF, a `Hint` z SDK, które pisze wskazówki po
angielsku. Linia `Trace ID` pojawia się, gdy KSeF zwrócił identyfikator
śledzenia (odpowiedzi `application/problem+json`).

## Wskazówki

`KSeFException.hint` mówi, co zrobić dalej. Jest pokazywany w osobnej linii
`Hint:` w `str(exc)` i zapisany w `exc.context["hint"]`. Wskazówka jest ustawiana
tylko wtedy, gdy SDK zna przyczynę, każda wymieniona w niej metoda jest aktualna,
a dla jednego wystąpienia można ją zastąpić, przekazując `hint=...` do wyjątku.

Wskazówki do błędów API zależą najpierw od kodu KSeF, potem od statusu HTTP. Kod z własną wskazówką zachowuje ją także przy 401 albo 403. HTTP 401 zgłasza `KSeFAuthError`, a HTTP 403 zgłasza `KSeFPermissionDeniedError`. SDK wstawia tekst wskazówki po angielsku. W tabeli jest jego polskie znaczenie. Nazwy klas, kody i metody zostają bez zmian.

| Status HTTP | Kod KSeF | Klasa | Wskazówka |
| --- | --- | --- | --- |
| inny | 21155 | `KSeFApiError` | Sesja osiągnęła limit faktur. Zamknij ją przez `close()` i wyślij pozostałe faktury w nowej sesji z `online_session()`. |
| inny | 21157 | `KSeFApiError` | Zbuduj zaszyfrowaną paczkę przez `auth.batch.prepare()`. Ta metoda dzieli części według limitów rozmiaru i liczby w KSeF. |
| inny | 21161 | `KSeFApiError` | Zbuduj zaszyfrowaną paczkę przez `auth.batch.prepare()`. Ta metoda dzieli części według limitów rozmiaru i liczby w KSeF. |
| inny | 21165 | `KSeFNotReadyError` | KSeF przetworzył fakturę, ale jeszcze jej nie udostępnił. Wywołaj `download()` z `timeout`, żeby SDK sprawdzało dostępność, aż faktura się pojawi. |
| inny | 21178 | `KSeFNotReadyError` | KSeF nie ma jeszcze UPO. Najpierw wywołaj `wait()` na wysyłce faktury albo na sesji, a potem ponownie `download_upo()` albo `download_invoice_upo()`. Jeśli `wait()` zgłosi `KSeFInvoiceRejectedError`, KSeF odrzucił fakturę i nie wystawi dla niej UPO. |
| inny | 21180 | `KSeFApiError` | Sesja jest już zamknięta albo jest w stanie, który nie pozwala na tę operację. Sprawdź stan przez `get_status()` albo otwórz nową sesję przez `online_session()` albo `batch_session()`. |
| inny | 21182 | `KSeFApiError` | KSeF ogranicza liczbę eksportów naraz. Poczekaj, aż trwający eksport skończy się przez `wait()`, a potem wywołaj `export()` ponownie. |
| inny | 21183 | `KSeFApiError` | Zakres dat wychodzi poza dane, które KSeF przechowuje. Zawęź zakres dat w filtrach przekazanych do `search()`. |
| inny | 21184 | `KSeFServerError` | KSeF nie może teraz przyjąć faktur w tej sesji. Spróbuj później albo wyślij fakturę w nowej sesji z `online_session()`. |
| inny | 21205 | `KSeFApiError` | Prześlij każdą zadeklarowaną część paczki przez `upload_parts()`, zanim zamkniesz sesję, albo wyślij paczkę przez `submit()`. |
| inny | 21208 | `KSeFApiError` | KSeF anulował sesję wsadową, bo części nie zostały przesłane albo sesja nie została zamknięta na czas. Wyślij paczkę ponownie w nowej sesji z `batch_session()`. |
| inny | 21418 | `KSeFApiError` | Tokeny kontynuacji pochodzą z KSeF i są ważne tylko w otrzymanej postaci. Iteruj po stronach, które zwraca SDK, albo użyj `pages()`, zamiast budować albo ponownie używać tokenu samodzielnie. |
| inny | 21470 | `KSeFApiError` | KSeF nie zna klucza publicznego, którym zaszyfrowano żądanie, albo ten klucz został wycofany. SDK trzyma certyfikaty KSeF przez 24 godziny. Utwórz nowego klienta, żeby wczytał aktualne. |
| inny | 25001 | `KSeFApiError` | Rejestracja certyfikatu wymaga uwierzytelnienia XAdES. Uwierzytelnij się przez `client.authentication.with_xades()`, a nie przez `client.authentication.with_token()`. |
| inny | 25002 | `KSeFApiError` | Rejestracja certyfikatu wymaga uwierzytelnienia XAdES. Uwierzytelnij się przez `client.authentication.with_xades()`, a nie przez `client.authentication.with_token()`. |
| inny | 25003 | `KSeFApiError` | Pobierz dane podmiotu, których oczekuje KSeF, przez `get_enrollment_data()` i zbuduj nowy CSR, zanim wywołasz `enroll()`. |
| inny | 25006 | `KSeFApiError` | KSeF pozwala na ograniczoną liczbę rejestracji certyfikatów. `get_limits()` pokazuje, ile jeszcze można złożyć. |
| inny | 25007 | `KSeFApiError` | Masz maksymalną liczbę certyfikatów KSeF. Unieważnij nieużywany przez `revoke()` i sprawdź limit w `get_limits()`. |
| inny | 26001 | `KSeFApiError` | Token może dostać tylko uprawnienia, które ma uwierzytelniony podmiot. Poproś o mniej uprawnień w `generate()`. |
| inny | 26002 | `KSeFApiError` | W tym typie kontekstu nie da się wygenerować tokenu KSeF. Uwierzytelnij się w obsługiwanym kontekście, zanim wywołasz `generate()`. |
| inny | 30001 | `KSeFApiError` | Podmiot albo osoba już istnieje w środowisku testowym KSeF. Użyj istniejącego albo usuń go najpierw przez `delete_subject()` albo `delete_person()`. |
| 401 | inny | `KSeFAuthError` | KSeF odrzucił dane uwierzytelniające albo token dostępu. Uwierzytelnij się ponownie przez `client.authentication.with_token()` albo `client.authentication.with_xades()` i sprawdź, czy token albo certyfikat jest ważny w tym kontekście. |
| 403 | inny | `KSeFPermissionDeniedError` | Uwierzytelniony podmiot nie może tego zrobić w bieżącym kontekście. Sprawdź powód w `details` i nadaj brakujące uprawnienie klientem uprawnień, na przykład `grant_person()`. |

`KSeFRateLimitError` buduje wskazówkę z `retry_after`. SDK wstawia ją po angielsku, na przykład `Wait 17 seconds before retrying.` (poczekaj 17 sekund przed ponowieniem).

Wskazówki do pozostałych błędów SDK:

| Klasa | Wskazówka |
| --- | --- |
| `KSeFArgumentError` | Przekaż dokładnie jeden z wykluczających się argumentów nazwanych w komunikacie. |
| `KSeFAuthPollingTimeoutError` | KSeF jeszcze nie skończył uwierzytelniania. Uwierzytelnij się ponownie z większym `timeout` w `client.authentication.with_xades()` albo `client.authentication.with_token()`. |
| `KSeFAuthenticationExpiredError` | Uwierzytelnij się ponownie przez `client.authentication.with_token()` albo `client.authentication.with_xades()`, albo przywróć nadal ważne tokeny przez `client.authentication.resume()`. |
| `KSeFBatchSessionTimeoutError` | KSeF może nadal przetwarzać sesję wsadową. Wywołaj `wait()` na sesji wsadowej ponownie z większym `timeout`. Po restarcie odbuduj sesję ze stanu zapisanego przez `resume_state()`, używając `batch_session(state=...)`. |
| `KSeFCertificateEnrollmentFailedError` | Przeczytaj powód w `description` i `details`, a potem złóż poprawione żądanie przez `enroll()`. `get_limits()` pokazuje, ile rejestracji i certyfikatów jeszcze można złożyć. |
| `KSeFCertificateEnrollmentTimeoutError` | KSeF może nadal wydać certyfikat. Wywołaj `wait()` na rejestracji ponownie z większym `timeout` albo sprawdź ją przez `get_enrollment_status()`. Po restarcie odzyskaj obiekt przez `auth.certificates.enrollment(state)`, używając stanu zapisanego z `resume_state()`. |
| `KSeFCertificateStoreAccessError` | Sprawdź dane dostępowe magazynu albo źródło hasła oraz jego uprawnienia. |
| `KSeFCertificateStoreConflictError` | Pod tym wskazaniem jest już inny rekord. Wczytaj go i obejrzyj albo najpierw wywołaj `delete()`, jeśli ma zostać zastąpiony. |
| `KSeFCertificateStoreMaterialError` | Zapisany rekord jest uszkodzony, używa nieobsługiwanego formatu, nie da się go odszyfrować albo nie zgadza się ze wskazaniem. Sprawdź źródło hasła albo przywróć nienaruszoną kopię rekordu. |
| `KSeFCertificateStoreNotFoundError` | Wywołaj `list()`, żeby zobaczyć zapisane wskazania, albo najpierw zapisz certyfikat przez `save()`. |
| `KSeFCertificateStoreUnavailableError` | Sprawdź, czy backend magazynu jest osiągalny i ma wolne miejsce, a potem ponów. Gdy `outcome_ambiguous` jest prawdziwe, najpierw wywołaj `load()` albo `list()`, żeby sprawdzić, czy operacja się wykonała. |
| `KSeFExportFailedError` | Przeczytaj powód w `description` i `details`, a potem zacznij nowy eksport przez `export()`. |
| `KSeFExportTimeoutError` | Eksport może jeszcze się skończyć. Wywołaj `wait()` na eksporcie ponownie z większym `timeout`. Po restarcie odzyskaj obiekt przez `export(state=...)`, używając stanu zapisanego z `resume_state()`. |
| `KSeFInvoiceDownloadTimeoutError` | KSeF jeszcze nie udostępnił faktury. Wywołaj `download()` ponownie z większym `timeout`. |
| `KSeFInvoiceProcessingTimeoutError` | KSeF może jeszcze przyjąć fakturę. Czekaj dalej przez `submission(reference_number).wait()` na sesji, z większym `timeout`. Po restarcie odbuduj sesję ze stanu zapisanego przez `resume_state()`, używając `online_session(state=...)`. `submission(state=...)` przyjmuje też stan zapisany na samej wysyłce, który trzyma razem numer referencyjny faktury i sesji. |
| `KSeFInvoiceQueryTimeoutError` | Żadna faktura nie pasowała przed upływem czasu. Wywołaj `wait()` ponownie z większym `timeout` albo sprawdź filtry przekazane do `search()`. |
| `KSeFInvoiceRejectedError` | Przeczytaj powód w `description` i `details`, popraw fakturę i wyślij ją ponownie przez `send_invoice()`. |
| `KSeFNotReadyError` | KSeF nie skończył jeszcze przygotowywać tego zasobu. Poczekaj i poproś o niego ponownie. |
| `KSeFOnlineSessionTimeoutError` | KSeF może nadal przetwarzać sesję. Wywołaj `wait()` na sesji ponownie z większym `timeout`. Po restarcie odbuduj sesję ze stanu zapisanego przez `resume_state()`, używając `online_session(state=...)`. |
| `KSeFPermissionOperationFailedError` | Przeczytaj powód w `description`, popraw żądanie i nadaj albo cofnij uprawnienie ponownie. `get_operation_status()` pokazuje końcowy stan operacji. |
| `KSeFPermissionOperationTimeoutError` | Operacja może jeszcze zostać zastosowana. Wywołaj `wait()` na operacji ponownie z większym `timeout` albo sprawdź ją przez `get_operation_status()`. Po restarcie odzyskaj obiekt przez `auth.permissions.operation(state)`, używając stanu zapisanego z `resume_state()`. |
| `KSeFSessionFailedError` | Zobacz, czemu faktury się nie udały, przez `list_failed_invoices()`. |
| `KSeFTokenActivationFailedError` | Wygeneruj nowy token przez `generate()` albo sprawdź status tokenu przez `get_status()`. |
| `KSeFTokenStatusTimeoutError` | KSeF może nadal aktywować token. Wywołaj `wait()` na tokenie ponownie z większym `timeout` albo sprawdź go przez `get_status()`. Po restarcie odzyskaj obiekt przez `auth.tokens.generation(state)`, używając stanu zapisanego z `resume_state()`. Ten stan nigdy nie zawiera jednorazowego tokenu. |

`KSeFSessionError` nie ma wskazówki na poziomie klasy. SDK ustawia ją tam, gdzie
zna przyczynę: oczekiwanie na sesję, która jest nadal otwarta (najpierw ją
zamknij), oraz sesja, którą KSeF zakończył błędem (sprawdź faktury z błędem).
Odrzucony duplikat (`440`) dostaje własną wskazówkę w `KSeFInvoiceRejectedError`.

## Kody błędów KSeF

`ksef_code` to liczba wysłana przez KSeF. SDK nigdy nie gubi nieznanego kodu.
Kody `21165` i `21178` zgłaszają `KSeFNotReadyError`. Kody `21301`, `21304`
i `21308` zgłaszają `KSeFAuthError` także przy HTTP 400. Kody `21164`, `21173`,
`21175`, `25005`, `25008` i `71001` zgłaszają `KSeFNotFoundError`, a `21184`
zgłasza `KSeFServerError`. HTTP 403 zawsze zgłasza
`KSeFPermissionDeniedError`. W pozostałych przypadkach pierwszeństwo mają
zmapowane kody KSeF, a następnie status HTTP: 401 oznacza błąd uwierzytelnienia,
429 limit żądań, 404/410 brak zasobu, a 5xx błąd serwera. Inne błędy zgłaszają
`KSeFApiError`. Poniżej są wszystkie kody, które wymienia dokumentacja API KSeF
(`openapi.json`), wszystkie w odpowiedziach HTTP 400, i każdy ma swój element
`ExceptionCode`. Test jednostkowy nie przejdzie, gdy aktualizacja specyfikacji
doda kod, którego tu nie ma.

`21178` nie zawsze znaczy „jeszcze nie wystawione”: KSeF zwraca go na stałe także
dla faktury, którą odrzucił (na przykład duplikatu, status 440). Najpierw wywołaj
`wait()`. Jeśli zgłosi `KSeFInvoiceRejectedError`, UPO nie będzie.

| Kod KSeF | `ExceptionCode` | Znaczenie |
| --- | --- | --- |
| `9101` | `INVALID_DOCUMENT` | Nieprawidłowy dokument. |
| `9102` | `MISSING_SIGNATURE` | Brak podpisu. |
| `9103` | `TOO_MANY_SIGNATURES` | Przekroczona liczba dozwolonych podpisów. |
| `9105` | `INVALID_SIGNATURE` | Nieprawidłowy podpis. |
| `21001` | `UNREADABLE_CONTENT` | Nieczytelna treść. |
| `21111` | `INVALID_AUTH_CHALLENGE` | Nieprawidłowe wyzwanie autoryzacyjne. |
| `21115` | `INVALID_CERTIFICATE` | Nieprawidłowy certyfikat. |
| `21117` | `INVALID_CONTEXT_IDENTIFIER` | Nieprawidłowy identyfikator podmiotu dla wskazanego typu kontekstu. |
| `21155` | `SESSION_INVOICE_LIMIT_EXCEEDED` | Przekroczono dozwoloną liczbę faktur w sesji. |
| `21157` | `INVALID_PACKAGE_PART_SIZE` | Nieprawidłowy rozmiar części pakietu. |
| `21161` | `PACKAGE_PART_LIMIT_EXCEEDED` | Przekroczono dozwoloną liczbę części pakietu. |
| `21164` | `INVOICE_NOT_FOUND` | Faktura o podanym identyfikatorze nie istnieje. |
| `21165` | `NOT_PROCESSED_YET` | Faktura o podanym numerze KSeF nie jest jeszcze dostępna. `KSeFNotReadyError`. |
| `21166` | `TECHNICAL_CORRECTION_UNAVAILABLE` | Korekta techniczna niedostępna. |
| `21167` | `TECHNICAL_CORRECTION_NOT_ALLOWED` | Status faktury nie pozwala na korektę techniczną. |
| `21173` | `SESSION_NOT_FOUND` | Brak sesji o wskazanym numerze referencyjnym. |
| `21175` | `QUERY_RESULT_NOT_FOUND` | Wynik zapytania o podanym identyfikatorze nie istnieje. |
| `21178` | `UPO_NOT_FOUND` | Nie znaleziono UPO dla podanych kryteriów. `KSeFNotReadyError`. |
| `21180` | `SESSION_STATUS_FORBIDS_OPERATION` | Status sesji nie pozwala na wykonanie operacji. |
| `21181` | `INVALID_EXPORT_REQUEST` | Nieprawidłowe żądanie eksportu faktur. |
| `21182` | `EXPORT_LIMIT_REACHED` | Osiągnięto limit trwających eksportów. |
| `21183` | `FILTER_RANGE_OUT_OF_BOUNDS` | Zakres filtrowania wykracza poza dostępny zakres danych. |
| `21184` | `SESSION_TEMPORARILY_UNAVAILABLE` | Sesja tymczasowo niedostępna. |
| `21205` | `EMPTY_PACKAGE` | Pakiet nie może być pusty. |
| `21208` | `UPLOAD_WINDOW_EXCEEDED` | Czas oczekiwania na requesty upload lub finish został przekroczony. |
| `21217` | `INVALID_CHARACTER_ENCODING` | Nieprawidłowe kodowanie znaków. |
| `21301` | `NO_AUTHORIZATION` | Brak autoryzacji. |
| `21304` | `NO_AUTHENTICATION` | Brak uwierzytelnienia. |
| `21308` | `DECEASED_PERSON_AUTHENTICATION` | Próba wykorzystania metod autoryzacyjnych osoby zmarłej. |
| `21401` | `SCHEMA_VALIDATION_FAILED` | Dokument nie jest zgodny ze schemą (XSD). |
| `21402` | `INVALID_FILE_SIZE` | Nieprawidłowy rozmiar pliku. |
| `21403` | `INVALID_FILE_HASH` | Nieprawidłowy skrót pliku. |
| `21405` | `VALIDATION_ERROR` | Błąd walidacji danych wejściowych. |
| `21406` | `SIGNATURE_AUTH_TYPE_CONFLICT` | Konflikt podpisu i typu uwierzytelnienia. |
| `21418` | `INVALID_CONTINUATION_TOKEN` | Przekazany token kontynuacji jest nieprawidłowy. |
| `21470` | `UNKNOWN_KEY_ID` | Identyfikator klucza jest nieznany lub wskazuje na wycofany klucz. |
| `25001` | `CSR_DATA_UNAVAILABLE` | Brak możliwości pobrania danych do CSR dla wykorzystanego sposobu uwierzytelnienia. |
| `25002` | `ENROLLMENT_NOT_ALLOWED` | Brak możliwości złożenia wniosku certyfikacyjnego dla wykorzystanego sposobu uwierzytelnienia. |
| `25003` | `CSR_DATA_MISMATCH` | Dane w CSR nie zgadzają się z danymi w użytym wektorze uwierzytelniającym. |
| `25004` | `INVALID_CSR` | Niepoprawny format CSR lub niepoprawny podpis CSR. |
| `25005` | `ENROLLMENT_NOT_FOUND` | Wniosek certyfikacyjny o podanym numerze referencyjnym nie istnieje. |
| `25006` | `ENROLLMENT_LIMIT_REACHED` | Osiągnięto limit możliwych do złożenia wniosków certyfikacyjnych. |
| `25007` | `CERTIFICATE_LIMIT_REACHED` | Osiągnięto limit dopuszczalnej liczby posiadanych certyfikatów. |
| `25008` | `CERTIFICATE_NOT_FOUND` | Certyfikat o podanym numerze seryjnym nie istnieje. |
| `25009` | `CERTIFICATE_NOT_REVOCABLE` | Nie można odwołać wskazanego certyfikatu, ponieważ jest już odwołany, zablokowany lub nieważny. |
| `25010` | `INVALID_KEY` | Nieprawidłowy typ lub długość klucza. |
| `25011` | `INVALID_CSR_SIGNATURE_ALGORITHM` | Nieprawidłowy algorytm podpisu CSR. |
| `26001` | `TOKEN_PERMISSIONS_NOT_HELD` | Nie można nadać tokenowi uprawnień, których nie posiadasz. |
| `26002` | `TOKEN_CONTEXT_NOT_ALLOWED` | Nie można wygenerować tokena dla obecnego typu kontekstu. |
| `30001` | `OBJECT_ALREADY_EXISTS` | Podmiot lub uprawnienie już istnieje. |
| `71001` | `COLLECTIVE_INVOICE_NOT_FOUND` | Faktura o podanym identyfikatorze nie istnieje. |
| `71002` | `COLLECTIVE_IDENTIFIER_LIMIT_REACHED` | Faktura jest już przypisana do maksymalnej liczby identyfikatorów zbiorczych. |
| `71004` | `DIFFERENT_SELLERS` | Faktury mają różnych sprzedawców. |
| `71005` | `DUPLICATE_KSEF_NUMBER` | Powtórzony numer KSeF w żądaniu. |

## Wartości ExceptionCode

`ExceptionCode` to `IntEnum`: wartością każdego elementu jest jego kod KSeF, a
nazwy są w tabeli powyżej. Jeden dodatkowy element nie jest kodem KSeF:

| Nazwa | Wartość |
| --- | --- |
| `UNKNOWN_ERROR` | `10000` |

Kody, których enum nie zna, mapują się do `ExceptionCode.UNKNOWN_ERROR`, ale
surowa liczba zostaje w `ksef_code`. W nowym kodzie preferuj `ksef_code`.

## Klasy przekroczenia czasu oczekiwania

Wszystkie dziesięć klas poniżej dziedziczy po `KSeFPollingTimeoutError`, który udostępnia `timeout`.

Te wyjątki oznaczają przekroczenie lokalnego limitu czasu czekania. Same w sobie nie dowodzą, że zdalny przepływ w KSeF się nie udał.

| Klasa | `code` | Atrybuty identyfikujące |
| --- | --- | --- |
| `KSeFAuthPollingTimeoutError` | `AUTH_POLLING_TIMEOUT` | `reference_number`, `timeout` |
| `KSeFTokenStatusTimeoutError` | `TOKEN_STATUS_TIMEOUT` | `reference_number`, `timeout` |
| `KSeFInvoiceQueryTimeoutError` | `INVOICE_QUERY_TIMEOUT` | `timeout` |
| `KSeFInvoiceDownloadTimeoutError` | `INVOICE_DOWNLOAD_TIMEOUT` | `ksef_number`, `timeout` |
| `KSeFInvoiceProcessingTimeoutError` | `INVOICE_PROCESSING_TIMEOUT` | `invoice_reference_number`, `timeout` |
| `KSeFExportTimeoutError` | `EXPORT_TIMEOUT` | `reference_number`, `timeout` |
| `KSeFPermissionOperationTimeoutError` | `PERMISSION_OPERATION_TIMEOUT` | `reference_number`, `timeout` |
| `KSeFCertificateEnrollmentTimeoutError` | `CERTIFICATE_ENROLLMENT_TIMEOUT` | `reference_number`, `timeout` |
| `KSeFBatchSessionTimeoutError` | `BATCH_SESSION_TIMEOUT` | `reference_number`, `timeout` |
| `KSeFOnlineSessionTimeoutError` | `ONLINE_SESSION_TIMEOUT` | `reference_number`, `timeout` |

Zapisz właściwy numer referencyjny albo stan zwracany przez `resume_state()`, zanim zaczniesz cyklicznie sprawdzać status, żeby inny proces mógł je wznowić. Każdy błąd przekroczenia czasu niesie `hint`, który mówi, jak czekać dalej albo wznowić pracę.

`download_upo()` na obiekcie faktury, sesji interaktywnej i sesji wsadowej nigdy nie czeka i nie ma `timeout`. Najpierw wywołaj `wait()` na tym obiekcie albo na sesji. Wywołane za wcześnie zgłasza `KSeFNotReadyError` ze wskazówką wskazującą `wait()`. Sesja, która jest nadal otwarta, zgłasza `KSeFSessionError`.

## Atrybuty limitu żądań

| Atrybut | Typ | Znaczenie |
| --- | --- | --- |
| `retry_after` | `int | None` | Całkowite sekundy z `Retry-After` KSeF, podane jako sekundy albo data HTTP; `None`, gdy nagłówka brak lub nie da się go odczytać. |
| `status_code` | `int` | Zawsze `429`. |
| `response` | `BaseModel | None` | Sparsowana treść błędu KSeF, gdy jest dostępna. |
| `hint` | `str` | Tekst wstawiany przez SDK po angielsku: `Wait <retry_after> seconds before retrying.` (poczekaj podaną liczbę sekund przed ponowieniem). |

## Atrybuty odrzucenia faktury

`KSeFInvoiceRejectedError` dziedziczy po `KSeFSessionError`, więc istniejąca obsługa tego błędu nadal go łapie. Łap `KSeFInvoiceRejectedError` przed `KSeFSessionError`, gdy tylko naruszenie stanu sesji wymaga otwarcia sesji od nowa albo ponownego uwierzytelnienia.

| Atrybut | Typ | Znaczenie |
| --- | --- | --- |
| `invoice_reference_number` | `str` | Numer referencyjny odrzuconej faktury. |
| `invoice_status_code` | `int` | Kod statusu faktury KSeF, na przykład `440` albo `450`. To nie jest status HTTP. |
| `description` | `str` | Opis statusu KSeF. |
| `details` | `list[str]` | Szczegóły statusu KSeF; pusta lista, gdy ich brak. |
| `extensions` | `dict[str, str | None]` | Rozszerzenia statusu KSeF; pusty słownik, gdy ich brak. |
| `status` | `SessionInvoiceStatusResponse` | Pełna odpowiedź statusu. |

W przeciwieństwie do `KSeFApiError.status_code`, które zawsze jest statusem HTTP,
`invoice_status_code` pochodzi ze statusu faktury KSeF.

Dla duplikatu (`440`) `extensions` zawiera `originalKsefNumber` i
`originalSessionReferenceNumber`. Wywołujący, który odzyskuje wysyłkę z utraconą
odpowiedzią, może przekazać `originalKsefNumber` do `download()` i
porównać pobraną fakturę z wysłaną. Jeśli to ta sama faktura, może uznać ją za
już przyjętą.

## Powiązane strony

- [Operacje](operations.md): Ponowienia, limit żądań, limity czasu przepływów i stan, który da się wznowić.
- [Tworzenie i zamykanie klientów](client-lifecycle.md): Błędy cyklu życia i zamykanie klientów.
- [Status i UPO](../concepts/status-and-upo.md): Statusy, dokumenty UPO i lokalne limity czasu.
