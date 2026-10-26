---
title: Konfiguracja klienta
description: Utwórz klienta synchronicznego albo asynchronicznego, skonfiguruj transport i wybierz moduły po uwierzytelnieniu.
---

Klient główny `Client` przechowuje konfigurację transportu HTTP i udostępnia publiczne moduły bez uwierzytelnienia. Uwierzytelnij się raz dla kontekstu logowania, a potem przekaż klienta uwierzytelnionego do kodu przepływu.

## Wybierz wersję synchroniczną albo asynchroniczną

`Client` to synchroniczny klient główny, a `AsyncClient` to jego odpowiednik asynchroniczny. Oba mają to samo API. Z `AsyncClient` używasz `async with` i `await` przy wywołaniach.

### Wersja synchroniczna

```python
from ksef2 import Client, Environment

with Client(Environment.TEST) as client:
    auth = client.authentication.with_test_certificate(nip="5261040828")
```

### Wersja asynchroniczna

```python
import asyncio

from ksef2 import AsyncClient, Environment

async def main() -> None:
    async with AsyncClient(Environment.TEST) as client:
        auth = await client.authentication.with_test_certificate(nip="5261040828")

asyncio.run(main())
```

Poza lokalnymi przepływami w środowisku testowym używaj `Environment.DEMO` albo `Environment.PRODUCTION`.

## Zarządzanie zasobami

Klient główny przechowuje zasoby HTTP zarządzane przez SDK. W skryptach i zadaniach lepiej użyć menedżera kontekstu (`with`):

```python
from ksef2 import Client, Environment

with Client(Environment.TEST) as client:
    auth = client.authentication.with_test_certificate(nip="5261040828")
```

Jeżeli framework oczekuje zależności opartej o `yield`, umieść `yield` w funkcji zależności i zamknij klienta w `finally`:

```python
from collections.abc import Iterator

from ksef2 import Client, Environment

def get_client() -> Iterator[Client]:
    client = Client(Environment.TEST)
    try:
        yield client
    finally:
        client.close()
```

Aplikacje asynchroniczne używają tej samej granicy przez `async with` wewnątrz funkcji asynchronicznej:

```python
import asyncio

from ksef2 import AsyncClient, Environment

async def main() -> None:
    async with AsyncClient(Environment.TEST) as client:
        auth = await client.authentication.with_test_certificate(nip="5261040828")

asyncio.run(main())
```

Sesje interaktywne i wsadowe też zamykają zasoby. Używaj menedżera kontekstu sesji, żeby SDK zamknęło zdalną sesję po wyjściu z bloku:

```python
from ksef2 import FormSchema

with auth.online_session(form_code=FormSchema.FA3) as session:
    status = session.send_invoice(invoice_xml).wait()
```

Gdy dane uwierzytelniające są zapisane w profilu zgodnym z CLI, utwórz klienta głównego dla środowiska profilu i uwierzytelnij się przez `with_profile()`:

```python
from ksef2 import Client, Environment

client = Client(Environment.PRODUCTION)
auth = client.authentication.with_profile("prod-token")
```

## Publiczne moduły klienta głównego

Klient główny przydaje się przed uwierzytelnieniem:

```python
certificates = client.encryption.get_certificates()
providers = client.peppol.list().first_page()
```

Moduł tylko dla środowiska testowego też jest na kliencie głównym:

```python
client.testdata.create_subject(
    nip="5261040828",
    subject_type="vat_group",
    description="Sandbox company",
)
```

## Moduły uwierzytelnione

Po uwierzytelnieniu użyj modułu pasującego do zadania:

```python
invoices = auth.invoices
batch = auth.batch
tokens = auth.tokens
permissions = auth.permissions
certificates = auth.certificates
limits = auth.limits
sessions = auth.sessions
invoice_sessions = auth.invoice_sessions
```

:::note[Oddziel klienta głównego od uwierzytelnionego]
Klient główny wybiera środowisko i transport. Klient uwierzytelniony trzyma token dostępu (`accessToken`) i moduły zależne od kontekstu logowania. Przekazanie klienta uwierzytelnionego do kodu przepływów zostawia stan uwierzytelnienia poza kodem konfiguracji.
:::

## Zalecany przebieg

1. Odczytaj środowisko i ustawienia transportu na brzegu aplikacji.

2. Utwórz jednego klienta głównego dla wybranego środowiska KSeF.

3. Modułów klienta głównego używaj tylko do publicznych odczytów albo przygotowania danych testowych.

4. Uwierzytelnij się raz dla kontekstu logowania, który wykonuje operację.

5. Przekaż klienta uwierzytelnionego do przepływów faktur, tokenów, uprawnień, certyfikatów, limitów i sesji.

## Powiązane strony

- [Uwierzytelnianie](authenticate.md): token KSeF, XAdES, certyfikat testowy albo profil.
- [Operacje](../reference/operations.md): typowe przepływy i wejścia SDK wysokiego poziomu.
- [Konfiguracja magazynu certyfikatów](configure-certificate-store.md): odświeżanie pamięci certyfikatów albo własny magazyn.
- [Podgląd certyfikatów szyfrowania](inspect-encryption-certificates.md): publiczne certyfikaty szyfrowania KSeF przed zaszyfrowanymi przepływami.
- [Wyszukiwanie dostawców PEPPOL](query-peppol-providers.md): publiczne dane dostawców PEPPOL z klienta głównego.
- [Dane testowe](use-test-data.md): podmioty i uprawnienia w środowisku testowym.
- [Tworzenie i zamykanie klientów](../reference/client-lifecycle.md): tworzenie, zamykanie i własność zasobów klienta głównego i uwierzytelnionego.
