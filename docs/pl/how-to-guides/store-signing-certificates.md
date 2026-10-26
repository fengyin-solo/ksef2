---
title: Przechowywanie certyfikatów podpisu
description: Certyfikat XAdES i klucz prywatny w pamięci albo w plikach szyfrowanych hasłem.
---

Magazyn certyfikatów podpisu trzyma pary certyfikat i klucz, którymi podpisujesz żądania do KSeF. Przyjmuje rekord `SigningCertificate`, oddaje tę samą parę po wskazaniu `SigningCertificateRef` i pozwala wypisać zapisane rekordy bez odszyfrowywania klucza. Podpisuje nadal `client.authentication.with_xades()`. Magazyn decyduje tylko o tym, gdzie para czeka na kolejne wywołanie.

To nie jest magazyn przekazywany klientowi jako `certificate_store=`. Tamten, `ksef2.CertificateStore`, trzyma pobrane z KSeF publiczne certyfikaty szyfrowania. SDK otacza nimi klucze do faktur i eksportów i nigdy nie trzyma tam klucza prywatnego. Magazyny z tej strony są w `ksef2.certificate_stores` i przechowują Twoje klucze podpisu.

Klucz, którego urządzenie nie pozwala wyeksportować, na przykład z HSM albo KMS, jest poza tym zakresem. Te magazyny wymieniają pary, których klucz prywatny proces może trzymać w pamięci.

## Złóż parę w rekord

`SigningCertificate` łączy wczytane `XAdESCredentials` ze środowiskiem, w którym podpisujesz, i wyprowadza metadane rekordu z samego certyfikatu.

```python
from pathlib import Path

from ksef2 import Environment
from ksef2.certificate_stores import SigningCertificate
from ksef2.xades import XAdESCredentials

credentials = XAdESCredentials.from_pem(
    Path("company.pem").read_bytes(),
    Path("company.key").read_bytes(),
    key_password=b"haslo-pliku-klucza",
)

record = SigningCertificate(
    credentials,
    environment=Environment.DEMO,
    certificate_type="authentication",
)

print(record.info.reference)
print(record.info.valid_to)
```

`certificate_type` i `ksef_serial_number` są opcjonalne. Pomiń je dla certyfikatu, o którym KSeF nic nie wie, albo dla certyfikatu wygenerowanego samodzielnie. Rekord ukrywa dane pary w `repr()`, nie daje się zapisać przez pickle ani skopiować i nie ma zapisu do JSON. Jedyną obsługiwaną postacią zapisu jest `save()`.

## Trzymaj rekordy w pamięci

`InMemorySigningCertificateStore` i `AsyncInMemorySigningCertificateStore` trzymają rekordy tak długo, jak żyje proces. Nic nie zostaje po restarcie. W testach zwykle o to chodzi, na produkcji rzadziej.

```python
from ksef2 import Environment
from ksef2.certificate_stores import (
    AsyncInMemorySigningCertificateStore,
    InMemorySigningCertificateStore,
)

store = InMemorySigningCertificateStore()
store.save(record)

held = store.list(environment=Environment.DEMO)
loaded = store.load(held[0].reference)
```

## Trzymaj rekordy na dysku

`FilesystemSigningCertificateStore` zapisuje jeden plik JSON na certyfikat, w `<root>/<environment>/<fingerprint>.json`. W rekordzie są certyfikat i klucz prywatny jako PKCS#8 zaszyfrowany podanym hasłem. Zapisu bez szyfrowania nie ma.

Dostawca hasła to zwykła funkcja: ze wskazania rekordu zwraca bajty hasła. Magazyn woła ją przy każdym `load()` i przy każdym `save()`, które zapisuje nowy rekord. Hasła ani rekordu nie trzyma.

```python
import os
from pathlib import Path

from ksef2 import Environment
from ksef2.certificate_stores import FilesystemSigningCertificateStore

store = FilesystemSigningCertificateStore(
    Path("~/.local/share/myapp/ksef-signing").expanduser(),
    password_provider=lambda ref: os.environ["MYAPP_KSEF_STORE_PASSWORD"].encode(),
)

info = store.save(record)

for held in store.list(environment=Environment.DEMO):
    print(held.reference.fingerprint_sha256, held.valid_to)

record = store.load(info.reference)
```

`list()` czyta wyłącznie certyfikat, więc nigdy nie prosi o hasło. Sprawdzenie przy starcie albo ekran administracyjny może pokazać, co trzymasz, zanim cokolwiek zostanie odszyfrowane.

Usunięcie rekordu zabiera tylko lokalny plik:

```python
removed = store.delete(info.reference)
```

Adapter asynchroniczny ma te same cztery operacje z `await`. Praca na plikach i kluczach, razem z Twoją funkcją hasła, idzie w wątku:

```python
from ksef2.certificate_stores import AsyncFilesystemSigningCertificateStore

store = AsyncFilesystemSigningCertificateStore(
    Path("~/.local/share/myapp/ksef-signing").expanduser(),
    password_provider=lambda ref: os.environ["MYAPP_KSEF_STORE_PASSWORD"].encode(),
)

info = await store.save(record)
held = await store.list(environment=Environment.DEMO)
record = await store.load(info.reference)
```

Anulowane `await store.save(...)` mogło mimo to zapisać rekord. Zapis albo trafia na dysk w całości, albo nie ma go wcale. Powtórzenie tego samego `save()` jest bezpieczne i zwraca zapisane metadane.

## Wskazuj certyfikat przez SigningCertificateRef

Magazyn nigdy nie wybiera certyfikatu „najnowszego” albo „najlepszego”. `load()` zwraca dokładnie wskazany rekord, także gdy wygasł. To celowe. Cicha wymiana klucza podpisu to usterka, którą najtrudniej złapać w nocy.

Zapisz więc wskazanie we własnej konfiguracji, obok NIP-u i środowiska, które i tak już tam trzymasz:

```python
from ksef2 import Client, Environment
from ksef2.certificate_stores import SigningCertificateRef

reference = SigningCertificateRef(
    environment=Environment.PRODUCTION,
    fingerprint_sha256="8f14e45fceea167a5a36dedd4bea2543a9012d45ded2b8f0b13c8e0a5c0b23c1",
)

with Client(Environment.PRODUCTION) as client:
    record = store.load(reference)
    auth = client.authentication.with_xades(
        nip=os.environ["KSEF2_NIP"],
        credentials=record.credentials,
    )
```

`info.reference` to dwa krótkie napisy bez materiału klucza. Można je logować, wpisać do pliku konfiguracyjnego i porównywać. Odnowienie certyfikatu daje nowy odcisk palca certyfikatu, czyli nowe wskazanie. Sprawdź nową parę, a potem przełącz konfigurację. Oba rekordy mogą leżeć w magazynie jednocześnie. Tak zostawia się stary klucz dostępny do momentu przełączenia.

## Zapisz wygenerowany certyfikat testowy

`generate_test_certificate()` buduje samopodpisaną parę RSA dla środowiska testowego. Zwraca obiekty cryptography i nic nie zapisuje, więc para znika razem z procesem, chyba że włożysz ją do magazynu:

```python
from ksef2 import Environment
from ksef2.certificate_stores import SigningCertificate
from ksef2.xades import XAdESCredentials, generate_test_certificate

certificate, private_key = generate_test_certificate(nip="5261040828")

store.save(
    SigningCertificate(
        XAdESCredentials(certificate, private_key),
        environment=Environment.TEST,
    )
)
```

Rekord jest wtedy dostępny po restarcie, a `list(environment=Environment.TEST)` pokazuje go bez hasła.

## Uwagi o bezpieczeństwie

- Na POSIX nowe rekordy mają tryb `0600`, a katalogi `0700`. Istniejący `root` zachowuje uprawnienia, które mu nadałeś. Na Windows plik dziedziczy listę ACL katalogu, więc ogranicz `root`, zanim cokolwiek do niego zapiszesz.
- Hasło jest pytane przy każdym `load()` i przy każdym `save()`, które zapisuje nowy rekord. Nie jest trzymane na magazynie, w `repr` ani między wywołaniami. `list()` hasła nie potrzebuje.
- Wczytany klucz prywatny to zwykły obiekt w pamięci. Magazyn nic nie buforuje i nie obiecuje wyzerowania pamięci, którą klucz zajmował. Traktuj zwrócony `SigningCertificate` jak sekret i pozbądź się go po użyciu.
- Magazyn nie przechodzi za dowiązanie symboliczne stojące w miejscu rekordu i nie przepisuje rekordu, którego nie może odczytać. Rekord w nieobsługiwanej wersji zostaje na dysku bez zmian.
- Usunięcie rekordu nie unieważnia niczego w KSeF. Certyfikat pozostaje tam ważny, dopóki go nie unieważnisz, a para już wczytana do pamięci nadal podpisuje.

## Błędy

Każda awaria to `KSeFCertificateStoreError`. Mówi, która operacja się nie udała i którego rekordu dotyczyła. Całą hierarchię opisuje [Obsługa błędów](../reference/errors.md).

| Błąd | Kiedy zgłasza go magazyn w plikach |
| --- | --- |
| `KSeFArgumentError` | `root` nie był `Path`, dostawca hasła nie był wywoływalny albo wartość przekazana metodzie miała zły typ. |
| `KSeFCertificateStoreNotFoundError` | `load()` dostał wskazanie, pod którym nic nie leży. |
| `KSeFCertificateStoreConflictError` | `save()` dostał rekord o metadanych innych niż już zapisane pod tym wskazaniem. |
| `KSeFCertificateStoreAccessError` | Pliki nie są do odczytu dla tego procesu, w drodze stoi dowiązanie symboliczne albo dostawca hasła zwrócił puste hasło. |
| `KSeFCertificateStoreMaterialError` | Rekord jest uszkodzony, ma nieobsługiwaną postać, nie da się go odszyfrować albo nie zgadza się ze wskazaniem, pod którym leży. |
| `KSeFCertificateStoreUnavailableError` | Magazyn nie mógł przyjąć zapisu ani odczytu, na przykład przez pełny dysk. |

Cokolwiek zgłosi Twoja funkcja hasła, wraca bez zmian. Dostawca, który nie sięga po sekret, to usterka wdrożenia, a nie uszkodzony rekord.
