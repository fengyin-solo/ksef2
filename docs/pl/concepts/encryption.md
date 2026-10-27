---
title: Szyfrowanie
description: Jak ksef2 używa publicznych certyfikatów KSeF do szyfrowania tokenów, sesji i eksportów.
---

KSeF wymaga, aby część danych była zaszyfrowana, zanim trafi do API. SDK ukrywa tę mechanikę w zwykłych przepływach, ale warto wiedzieć, który klucz jest chroniony i co trzeba zachować, żeby móc wrócić do przepływu.

Publiczne certyfikaty używane do tego szyfrowania publikuje KSeF. Aplikacja pobiera certyfikat, szyfruje lokalne sekrety dla KSeF i wysyła `public_key_id`, który wskazuje użyty klucz publiczny.

## Gdzie pojawia się szyfrowanie

| Przepływ | Lokalny sekret | Co otrzymuje KSeF |
| --- | --- | --- |
| Uwierzytelnianie tokenem KSeF | Token KSeF razem ze znacznikiem czasu wyzwania. | Zaszyfrowane dane uwierzytelniania i odpowiadający im `public_key_id`. |
| Sesja interaktywna | Klucz AES i IV wygenerowane dla XML faktury. | Zaszyfrowany klucz sesji, IV i zaszyfrowane faktury. |
| Sesja wsadowa | Klucz AES i IV dla paczki faktur. | Zaszyfrowany klucz paczki i informacje o częściach do przesłania. |
| Eksport faktur | Klucz AES i IV dla paczki eksportu. | Zaszyfrowany klucz eksportu. SDK później używa lokalnego materiału, żeby odszyfrować pobrane części. |

:::tip[Zostań przy ścieżce wysokiego poziomu]
Sesje interaktywne, sesje wsadowe, eksporty i uwierzytelnianie tokenem KSeF same pobierają publiczne certyfikaty i z nich korzystają. `client.encryption` jest do diagnostyki, kontroli przy starcie albo własnej pamięci podręcznej certyfikatów.
:::

## Publiczny certyfikat

KSeF publikuje publiczne certyfikaty klucza razem z metadanymi. Z nich wynika, do czego służy klucz i jak długo jest ważny.

| Pole SDK | Znaczenie |
| --- | --- |
| `certificate` | Certyfikat w Base64, używany przez warstwę kryptograficzną SDK. |
| `certificate_id` | Identyfikator obiektu certyfikatu. |
| `public_key_id` | Identyfikator klucza publicznego. Po szyfrowaniu wraca do KSeF. |
| `valid_from` / `valid_to` | Okres ważności, używany przy decyzjach o pamięci podręcznej i odświeżeniu. |
| `usage` | `ksef_token_encryption` albo `symmetric_key_encryption`. |

```python
certificates = client.encryption.get_certificates(
    usage=["symmetric_key_encryption"],
)

for certificate in certificates:
    print(certificate.public_key_id, certificate.valid_to, certificate.usage)
```

## Rotacja i pamięć podręczna

Publiczne certyfikaty szyfrowania traktuj jak infrastrukturę, która się zmienia. KSeF może opublikować nowy certyfikat dla tego samego klucza albo przejść na nowy klucz. Nowy certyfikat może zmienić `certificate_id`. Nowy klucz zmienia `public_key_id`.

Pamięć podręczna certyfikatów pomaga, jeśli skraca start aplikacji. Odśwież ją, zanim długo działające procesy otworzą sesje, zaplanują eksporty albo zaczną uwierzytelnianie tokenem KSeF. Nie zapisuj treści certyfikatów na stałe w kodzie aplikacji.

## Co zapisywać

Przy zwykłej wysyłce faktur zapisuj identyfikatory biznesowe, numery referencyjne KSeF, UPO (Urzędowe Poświadczenie Odbioru) i końcowe pliki. Szczegółów szyfrowania nie zapisuj, chyba że inny proces ma wznowić sesję.

Przy eksporcie trzymaj obiekt eksportu (`ExportHandle`), aż paczka zostanie pobrana. Jest w nim lokalny materiał do odszyfrowania części. Przy wznawianiu sesji interaktywnej albo wsadowej zapisuj stan sesji zwrócony przez SDK, zamiast składać klucze ręcznie.

## Powiązane strony

- [Podgląd certyfikatów szyfrowania](../how-to-guides/inspect-encryption-certificates.md): pobranie i obejrzenie publicznych certyfikatów KSeF z klienta głównego.
- [Wysyłanie faktur](../how-to-guides/send-invoices.md): szyfrowane sesje interaktywne i wsadowe bez ręcznego zarządzania kluczami.
- [Pobieranie faktur](../how-to-guides/download-invoices.md): pojedyncze faktury i zaszyfrowane paczki eksportu.
- [Certyfikaty](certificates.md): różnica między publicznymi certyfikatami szyfrowania a certyfikatami uwierzytelniania i certyfikatami wydanymi przez KSeF.
