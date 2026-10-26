---
title: Konfiguracja klienta
description: Utwórz klienta synchronicznego albo asynchronicznego, skonfiguruj transport i wybierz moduły uwierzytelnione.
---

Klient główny `Client` przechowuje konfigurację transportu HTTP i udostępnia publiczne moduły, które nie wymagają uwierzytelnienia. Uwierzytelnij się raz dla kontekstu logowania, a potem przekaż klienta uwierzytelnionego do kodu przepływu.

## Wybierz wersję synchroniczną albo asynchroniczną

`Client` to synchroniczny klient główny, a `AsyncClient` to jego odpowiednik asynchroniczny. Oba mają to samo API. Z `AsyncClient` używasz `async with` i `await` przy wywołaniach.

### Wersja synchroniczna

```python
from ksef2 import Client, Environment

with Client(Environment.TEST) as client:
    auth = client.authentication.with_test_certificate(nip="5261040828")
```

### Wersja asynchroniczna

Uruchom przykład przez `asyncio.run(main())`. Wzorce zamykania zasobów znajdziesz w [konfiguracji klienta](../how-to-guides/client-setup.md).

```python
import asyncio

from ksef2 import AsyncClient, Environment

async def main() -> None:
    async with AsyncClient(Environment.TEST) as client:
        auth = await client.authentication.with_test_certificate(nip="5261040828")

asyncio.run(main())
```

Poza lokalnymi przepływami w środowisku testowym używaj `Environment.DEMO` albo `Environment.PRODUCTION`.

## Pamięć certyfikatów

Klienci główni domyślnie używają pamięci certyfikatów w procesie. Magazyn odświeża publiczne certyfikaty szyfrowania po 24 godzinach, a przepływy uwierzytelniania, sesji i eksportu pobierają certyfikaty dopiero wtedy, gdy są potrzebne.

Ustaw własny odstęp odświeżania, gdy aplikacja ma ostrzejszą zasadę startu albo wymiany certyfikatów:

```python
from datetime import timedelta

from ksef2 import CertificateStore, Client, Environment

store = CertificateStore(refresh_after=timedelta(hours=6))
client = Client(Environment.PRODUCTION, certificate_store=store)
```

Przekaż dowolny obiekt implementujący `CertificateStoreProtocol`, gdy certyfikaty mają być wspólne dla magazynu aplikacji, na przykład bazy danych albo pamięci podręcznej.

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

## Opis API

- [Uwierzytelnianie](authentication.md)
- [Certyfikaty szyfrowania](encryption-certificates.md)
- [Dostawcy PEPPOL](peppol.md)
- [Dane TEST](test-data.md)
- [API cyklu życia klienta](../reference/api/client-lifecycle.md)
