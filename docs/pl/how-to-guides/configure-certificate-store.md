---
title: Konfiguracja magazynu certyfikatów
description: Skonfiguruj pamięć certyfikatów SDK używaną przez uwierzytelnianie tokenem, sesje i eksporty faktur.
---

SDK przechowuje publiczne certyfikaty szyfrowania KSeF na kliencie głównym. Uwierzytelnianie tokenem, sesje interaktywne i wsadowe oraz eksporty faktur używają tej pamięci, gdy muszą zaszyfrować klucz dla KSeF.

Domyślnej pamięci w procesie używaj w skryptach i procesach roboczych, które mogą odświeżać certyfikaty z KSeF. Przekaż własny magazyn, gdy certyfikaty mają być wspólne dla wielu procesów albo zapisane w magazynie aplikacji.

:::note[To pamięć publicznych certyfikatów szyfrowania]
Ta strona opisuje pamięć publicznych certyfikatów szyfrowania KSeF. Aby zapisać własny certyfikat podpisu i klucz prywatny, zobacz [Certyfikaty](../concepts/certificates.md).
:::

## Użyj domyślnego magazynu

`Client` i `AsyncClient` tworzą `CertificateStore` automatycznie. Domyślny magazyn odświeża ważne certyfikaty po 24 godzinach i odświeża je od razu, gdy brakuje wymaganego zastosowania certyfikatu.

Ustaw inny odstęp odświeżania przy tworzeniu klienta głównego:

```python
from datetime import timedelta

from ksef2 import CertificateStore, Client, Environment

store = CertificateStore(refresh_after=timedelta(hours=6))

with Client(Environment.PRODUCTION, certificate_store=store) as client:
    auth = client.authentication.with_profile("prod-token")
```

`AsyncClient` przyjmuje ten sam argument `certificate_store`. Użyj `async with AsyncClient(...)` i `await` przy wywołaniu uwierzytelniania. Nic więcej się nie zmienia.

Użyj `refresh_after=None` tylko dla krótkotrwałych klientów, w których jednorazowe pobranie jest zamierzone:

```python
from ksef2 import CertificateStore

store = CertificateStore(refresh_after=None)
```

:::note[Brak zastosowania nadal wymusza odświeżenie]
`refresh_after=None` nie blokuje odświeżenia, gdy w magazynie brakuje zastosowania wymaganego przez przepływ. SDK ponownie sprawdza KSeF, zanim zgłosi `NoCertificateAvailableError`.
:::

## Przekaż własny magazyn

Własne magazyny implementują `CertificateStoreProtocol`. SDK odpowiada za pobranie z KSeF. Magazyn odpowiada za trwałość, wybór ważnego certyfikatu i decyzję, czy dane są jeszcze świeże.

```python
from collections.abc import Iterable
from datetime import datetime

from ksef2 import CertificateStoreProtocol, Client, Environment
from ksef2.models import CertUsage, CertUsageEnum, PublicKeyCertificate

class DatabaseCertificateStore:
    def load(self, certs: Iterable[PublicKeyCertificate]) -> None:
        """Zastąp zapisane certyfikaty po pobraniu ich przez SDK."""
        ...

    def get_valid(
        self,
        usage: CertUsage | CertUsageEnum | str,
    ) -> PublicKeyCertificate:
        """Zwróć aktualnie ważny certyfikat dla wymaganego zastosowania."""
        ...

    def needs_refresh(
        self,
        usage: CertUsage | CertUsageEnum | str,
        *,
        at: datetime | None = None,
    ) -> bool:
        """Zwróć True, gdy SDK powinno pobrać certyfikaty z KSeF."""
        ...

store: CertificateStoreProtocol = DatabaseCertificateStore()
client = Client(Environment.PRODUCTION, certificate_store=store)
```

## Zalecany przebieg

1. Zacznij od domyślnego `CertificateStore`.

2. Ustaw `refresh_after`, gdy aplikacja ma ostrzejszą zasadę wymiany certyfikatów albo startu.

3. Implementuj `CertificateStoreProtocol` tylko wtedy, gdy certyfikaty mają przetrwać restart procesu albo być wspólne dla wielu procesów roboczych.

4. Pobieranie z KSeF zostaw klientowi SDK, a trwałość danych magazynowi.

## Powiązane strony

- [Podgląd certyfikatów szyfrowania](inspect-encryption-certificates.md): odczyt i sprawdzenie publicznych certyfikatów szyfrowania KSeF.
- [Konfiguracja klienta](client-setup.md): klient główny, transport, zamykanie zasobów i moduły uwierzytelnione.
- [Szyfrowanie](../concepts/encryption.md): jak publiczne certyfikaty chronią klucze tokenów, sesji i eksportów.
