---
title: Certyfikaty szyfrowania
description: Odczytuj publiczne certyfikaty szyfrowania KSeF używane przez zaszyfrowane przepływy faktur i eksportów.
---

KSeF publikuje certyfikaty publiczne używane do szyfrowania kluczy sesji i materiału eksportów. Metody wysokiego poziomu dla faktur i sesji wsadowej pobierają te certyfikaty same. Użyj `client.encryption` bezpośrednio, gdy chcesz je sprawdzić, zapisać w pamięci podręcznej albo pobrać z wyprzedzeniem.

Domyślnie klienci główni używają `CertificateStore`, czyli pamięci w procesie odświeżanej po 24 godzinach. Przekaż `refresh_after=None`, żeby krótkotrwały klient pobrał certyfikaty raz, albo przekaż własny obiekt implementujący `CertificateStoreProtocol`, żeby podłączyć magazyn aplikacji.

## Pobierz certyfikaty

```python
certificates = client.encryption.get_certificates()

for certificate in certificates:
    print(certificate.public_key_id, certificate.usage)
```

Filtruj po zastosowaniu, gdy potrzebujesz tylko jednej rodziny certyfikatów:

```python
certificates = client.encryption.get_certificates(
    usage=["symmetric_key_encryption"],
)
```

Skonfiguruj domyślny magazyn przy tworzeniu klienta głównego:

```python
from datetime import timedelta

from ksef2 import CertificateStore, Client, Environment

client = Client(
    Environment.PRODUCTION,
    certificate_store=CertificateStore(refresh_after=timedelta(hours=6)),
)
```

Własne magazyny implementują `load()`, `get_valid()` i `needs_refresh()`. SDK nadal pobiera certyfikaty z KSeF. Magazyn odpowiada za trwałość kopii i za to, czy dane są jeszcze świeże.

## Jak SDK ich używa

Uwierzytelnione sesje faktur i eksporty sięgają po certyfikaty szyfrowania, zanim zaszyfrują klucze przesyłanych danych:

```python
with auth.online_session(form_code=FormSchema.FA3) as session:
    ...

package = auth.invoices.export(filters).wait()
```

:::tip[Zostań przy przepływach wysokiego poziomu]
Większość aplikacji nie musi wywoływać `client.encryption` bezpośrednio. Użyj go do kontroli przy starcie, własnej pamięci podręcznej albo sprawdzenia, czy certyfikaty szyfrowania są dostępne.
:::

## Zalecany przebieg

1. Domyślnie pozwól przepływom faktur pobierać certyfikaty dopiero wtedy, gdy będą potrzebne.

2. Opcjonalnie pobierz certyfikaty publiczne przy starcie aplikacji.

3. Zgłoś alarm, gdy żaden certyfikat nie obsługuje zastosowania wymaganego przez przepływ.

4. Spróbuj później, zamiast wpisywać dane certyfikatów na stałe w aplikacji.

## Opis API

- [Wysyłanie faktur](sending-invoices.md)
- [Pobieranie faktur](downloading-invoices.md)
- [API certyfikatów klucza publicznego](../reference/api/public-key-certificates.md)
