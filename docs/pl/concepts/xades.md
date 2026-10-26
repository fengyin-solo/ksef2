---
title: XAdES
description: Podpis XML używany przy uwierzytelnianiu w KSeF certyfikatem.
---

XAdES to format podpisu XML używany, gdy uwierzytelnianie w KSeF opiera się na certyfikacie. W SDK XAdES należy do uwierzytelniania: podpisuje `AuthTokenRequest` zbudowany z wyzwania KSeF i kontekstu logowania.

Nie jest strukturą XML faktury, szyfrowaniem sesji ani formatem paczki eksportu.

## Co potwierdza XAdES

Przy uwierzytelnianiu XAdES KSeF sprawdza podpisany dokument XML i certyfikat osadzony w podpisie. Kontekstem logowania jest NIP przekazany do metody SDK. Podmiot uwierzytelniający jest odczytywany z certyfikatu, którym podpisano dokument, na przykład:

- kwalifikowany certyfikat osoby fizycznej zawierający PESEL albo NIP;
- kwalifikowana pieczęć organizacji zawierająca NIP;
- certyfikat KSeF typu Authentication;
- certyfikat rozpoznawany przez uprawnienia nadane na odcisk palca certyfikatu (`fingerprint`);
- certyfikat samopodpisany, wyłącznie w środowisku testowym.

Następnie KSeF sprawdza, czy ten podmiot może działać we wskazanym kontekście logowania.

## Warstwy SDK

Większość aplikacji powinna używać `with_xades()` albo profilu, który wybiera tę metodę:

```python
auth = client.authentication.with_xades(
    nip="5261040828",
    cert=cert,
    private_key=private_key,
)
```

Metoda wykonuje zwykłą sekwencję:

1. Pobiera wyzwanie uwierzytelniania.
2. Buduje XML `AuthTokenRequest` dla kontekstu logowania.
3. Podpisuje XML w formacie XAdES.
4. Wysyła podpisany XML do KSeF.
5. Sprawdza status operacji uwierzytelniania.
6. Odbiera token dostępu (`accessToken`) i token odświeżający (`refreshToken`).

Z `ksef2.xades` korzystaj bezpośrednio, gdy sam ładujesz materiał certyfikatu, chcesz obejrzeć podpisany XML albo sprawdzasz integrację na poziomie operacji API.

:::tip[Podpis poza Pythonem]
Jeśli inny system podpisuje XML, a Python ma tylko wysłać wynik albo odebrać tokeny, użyj operacji uwierzytelniania niskiego poziomu i powiąż pobrane tokeny przez `client.authentication.resume(AuthenticationResumeState.from_tokens(auth_tokens))`.
:::

## Certyfikaty testowe

SDK potrafi wygenerować certyfikat samopodpisany tylko dla środowiska testowego, przez `with_test_certificate()` albo metody pomocnicze w `ksef2.xades`. To skrót do pracy w `Environment.TEST`. Nie działa w środowisku przedprodukcyjnym (Demo) ani produkcyjnym.

## Powiązane strony

- [Metody uwierzytelniania](authentication-methods.md): XAdES obok tokena KSeF, certyfikatu testowego i profilu.
- [Podpisy XAdES](../how-to-guides/use-xades-helpers.md): wczytanie certyfikatu i podpis XML uwierzytelniania w kodzie.
- [Certyfikaty](certificates.md): tożsamość certyfikatu, rejestracja i typy certyfikatów wydanych przez KSeF.
- [Uwierzytelnianie niskiego poziomu](../reference/low-level/authentication.md): uwierzytelnianie ręczne, gdy podpis powstaje poza metodą wysokiego poziomu.
