---
title: Podgląd certyfikatów szyfrowania
description: Odczytuj publiczne certyfikaty szyfrowania KSeF używane przez zaszyfrowane przepływy faktur i eksportów.
---

Użyj `client.encryption`, gdy potrzebujesz kontroli przy starcie, diagnostyki albo własnej pamięci podręcznej certyfikatów. Większość przepływów faktur pobiera publiczne certyfikaty szyfrowania sama.

## Pobierz certyfikaty

`client.encryption` jest modułem klienta głównego, więc nie wymaga klienta uwierzytelnionego.

### Wszystkie zastosowania

```python
certificates = client.encryption.get_certificates()

# PublicKeyCertificate
# {
#   "public_key_id": "12345",
#   "certificate_id": "abcde",
#   "valid_from": "2026-06-01T00:00:00Z",
#   "valid_to": "2026-12-01T00:00:00Z",
#   "usage": ["ksef_token_encryption", "symmetric_key_encryption"]
# }

for certificate in certificates:
    print(certificate.public_key_id, certificate.usage, certificate.valid_to)
```

### Klucze sesji i eksportu

```python
certificates = client.encryption.get_certificates(
    usage=["symmetric_key_encryption"],
)

for certificate in certificates:
    print(certificate.public_key_id, certificate.valid_to)
```

### Szyfrowanie tokena

```python
certificates = client.encryption.get_certificates(
    usage=["ksef_token_encryption"],
)

for certificate in certificates:
    print(certificate.public_key_id, certificate.valid_to)
```

## Pobierz certyfikaty przed szyfrowanymi przepływami

Metody wysokiego poziomu dla sesji interaktywnej, sesji wsadowej, uwierzytelniania tokenem i eksportu używają tych publicznych certyfikatów, gdy szyfrują lokalny klucz dla KSeF. Wcześniejsze pobranie przydaje się, gdy chcesz sprawdzić start, zanim proces roboczy zacznie przyjmować zadania.

```python
required_usage = "symmetric_key_encryption"
certificates = client.encryption.get_certificates(usage=[required_usage])

if not certificates:
    raise RuntimeError(f"No KSeF certificate supports {required_usage}.")
```

:::tip[Nie zapisuj treści certyfikatu w kodzie]
Pobieraj aktualne certyfikaty KSeF i trzymaj je w pamięci podręcznej zgodnie z potrzebami operacyjnymi. Dane wpisane na stałe kiedyś wygasną.
:::

## Zalecany przebieg

1. Domyślnie pozwól przepływom faktur pobierać certyfikaty dopiero wtedy, gdy będą potrzebne.

2. Dodaj kontrolę przy starcie tylko wtedy, gdy brak certyfikatu ma zatrzymać proces, zanim przyjmie pracę.

3. Sprawdź zastosowanie wymagane przez przepływ: szyfrowanie tokenów albo szyfrowanie kluczy symetrycznych.

4. Zgłoś alarm i spróbuj później, jeśli nie ma ważnego certyfikatu.

## Następne strony

- [Szyfrowanie](../concepts/encryption.md): gdzie publiczne certyfikaty KSeF pojawiają się w przepływach SDK.
- [Konfiguracja magazynu certyfikatów](configure-certificate-store.md): odświeżanie pamięci certyfikatów albo podłączenie magazynu aplikacji.
- [Wysyłanie faktur](send-invoices.md): certyfikaty szyfrowania przez sesje interaktywne i wsadowe wysokiego poziomu.
- [Pobieranie faktur](download-invoices.md): metody eksportu, które szyfrują i odszyfrowują materiał paczek.
