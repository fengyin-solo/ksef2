---
title: Podpisy XAdES
description: Wczytywanie certyfikatów i kluczy, certyfikaty testowe oraz podpis XML do uwierzytelniania w KSeF.
---

Sięgnij po funkcje XAdES, gdy uwierzytelniasz się certyfikatem albo sprawdzasz podpisany XML uwierzytelniania. W zwykłej aplikacji wywołuj `client.authentication.with_xades()`, zamiast podpisywać XML ręcznie.

Przekaż `Path`, żeby odczytać plik PEM albo PKCS#12. Napis i bajty oznaczają treść, nie ścieżkę. Tekstowa ścieżka do istniejącego pliku działa przez całą serię 1.x z ostrzeżeniem o wycofaniu. Usunięcie tej zgodności może nastąpić najwcześniej w 2.0.0. Krótki napis, który wygląda jak ścieżka do brakującego pliku, zgłasza wyjątek `KSeFArgumentError` ze wskazówką `Path(...)`. Komunikat błędu nie zawiera treści wejścia.

## Załaduj materiał certyfikatu

### Z PEM

```python
import os
from pathlib import Path

from ksef2.xades import load_certificate_from_pem, load_private_key_from_pem

password = os.environ.get("KSEF2_KEY_PASSWORD")

cert = load_certificate_from_pem(Path("company.pem"))
private_key = load_private_key_from_pem(
    Path("company.key"),
    password=password.encode() if password else None,
)
```

### Z DER

`XAdESCredentials.from_der` czyta bajty certyfikatu i klucza w formacie DER i trzyma je w jednym obiekcie jako załadowane obiekty cryptography.

```python
import os
from pathlib import Path

from ksef2.xades import XAdESCredentials

password = os.environ.get("KSEF2_KEY_PASSWORD")

credentials = XAdESCredentials.from_der(
    Path("company.cer").read_bytes(),
    Path("company.key").read_bytes(),
    key_password=password.encode() if password else None,
)
```

### Z PKCS#12

```python
import os
from pathlib import Path

from ksef2.xades import load_certificate_and_key_from_p12

password = os.environ.get("KSEF2_P12_PASSWORD")

cert, private_key = load_certificate_and_key_from_p12(
    Path("company.p12"),
    password=password.encode() if password else None,
)
```

To samo archiwum możesz przekazać jako gotowe bajty:

```python
import os
from pathlib import Path

from ksef2.xades import XAdESCredentials

credentials = XAdESCredentials.from_pkcs12(
    Path("company.p12").read_bytes(),
    password=os.environ["KSEF2_P12_PASSWORD"].encode(),
)
```

## Uwierzytelnij przez XAdES

Przekaż załadowany certyfikat i klucz prywatny do uwierzytelniania:

```python
auth = client.authentication.with_xades(
    nip="5261040828",
    cert=cert,
    private_key=private_key,
)
```

Możesz też przekazać obiekt z certyfikatem i kluczem. W wersji asynchronicznej użyj `await` wewnątrz `async def main()`:

```python
import asyncio

from ksef2 import AsyncClient, Environment

async def main() -> None:
    async with AsyncClient(Environment.DEMO) as client:
        auth = await client.authentication.with_xades(
            nip="5261040828",
            credentials=credentials,
        )

asyncio.run(main())
```

## Wygeneruj certyfikat testowy

Wygenerowanego certyfikatu używaj tylko w środowisku testowym.

### Firma

```python
from ksef2.xades import generate_test_certificate

cert, private_key = generate_test_certificate(nip="5261040828")
```

### Osoba

```python
from ksef2.xades import generate_personal_test_certificate

cert, private_key = generate_personal_test_certificate(
    pesel="90010112345",
    nip="5261040828",
)
```

## Podpisz XML bezpośrednio

Bezpośredniego podpisu używaj do diagnostyki albo do niższych testów integracyjnych. Do zwykłego uwierzytelniania wybierz `with_xades()`.

```python
from ksef2.xades import build_auth_token_request_xml, sign_xades

xml = build_auth_token_request_xml(
    challenge="challenge-from-ksef",
    nip="5261040828",
)

signed_xml = sign_xades(xml, cert, private_key)
```

## Podpisz certyfikatem z magazynu

Magazyn certyfikatów podpisu oddaje załadowany rekord, więc jego certyfikat i klucz trafiają wprost do `LocalSigner`. Klucz prywatny to obiekt zwrócony przez magazyn. Podpis korzysta z niego bez eksportu, ponownego odszyfrowania i ponownego parsowania. Przykłady zakładają, że `store` trzyma rekord, a `reference` to wskazanie tego rekordu.

```python
from ksef2.xades import LocalSigner

record = store.load(reference)
signer = LocalSigner(
    cert=record.credentials.certificate,
    private_key=record.credentials.private_key,
)

signed_xml = signer.sign(xml)
```

Traktuj `record` jak sekret, dopóki istnieje w pamięci: trzyma klucz prywatny. Gdy podpis ma tylko uwierzytelnić, użyj `with_stored_certificate()`.

:::caution[Chroń klucze prywatne]
Pliki kluczy prywatnych i hasła trzymaj poza kontrolą wersji. Hasła bierz ze zmiennych środowiskowych albo z menedżera sekretów. `XAdESCredentials` trzyma w pamięci załadowany certyfikat i odszyfrowany klucz prywatny, bez hasła i bez bajtów wejściowych. `repr()` ukrywa oba obiekty. Obiekt nie ma schematu Pydantic ani zapisu do JSON. Traktuj go jak sekret, dopóki żyje. Konstruktor sprawdza typ klucza i zgodność certyfikatu z kluczem tylko raz. Uwierzytelnianie i podpisywanie używają załadowanych obiektów, bez serializacji i bez ponownego parsowania klucza prywatnego.
:::

## Zalecany przepływ

1. Wczytaj certyfikat z PEM, DER albo PKCS#12, jako osobne obiekty albo jako jedno `XAdESCredentials`.

2. Hasła kluczy prywatnych trzymaj w zmiennych środowiskowych albo w menedżerze sekretów.

3. Uwierzytelniaj się przez `with_xades()`, gdy to możliwe.

4. Certyfikat samopodpisany generuj tylko dla środowiska testowego.

5. Bezpośredniego podpisu używaj tylko do diagnostyki albo do niskopoziomowych testów integracyjnych.

## Następne kroki

- [Uwierzytelnianie](authenticate.md): Użyj wczytanego certyfikatu XAdES w uwierzytelnianiu SDK.
- [Zarządzanie certyfikatami](manage-certificates.md): Rejestruj, pobieraj i unieważniaj certyfikaty KSeF.
- [XAdES](../concepts/xades.md): Gdzie XAdES wchodzi w uwierzytelnianie KSeF.
