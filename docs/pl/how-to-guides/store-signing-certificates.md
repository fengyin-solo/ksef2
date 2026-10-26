---
title: Przechowywanie certyfikatów podpisu
description: Trzymanie certyfikatów XAdES i ich kluczy prywatnych w magazynie certyfikatów podpisu w pamięci albo w plikach szyfrowanych hasłem.
---

Magazyn certyfikatów podpisu przechowuje pary certyfikat i klucz, którymi
podpisujesz żądania do KSeF. Przyjmuje rekord `SigningCertificate`, oddaje tę
samą parę, gdy poprosisz o nią po wskazaniu referencji, i pozwala wypisać to, co
przechowujesz, bez odszyfrowywania żadnego klucza. Podpisuje nadal
`client.authentication.with_xades()` — magazyn decyduje tylko o tym, gdzie para
czeka na kolejne wywołanie.

To **nie jest** magazyn przekazywany klientowi jako `certificate_store=`. Ten,
`ksef2.CertificateStore`, trzyma pobrane od KSeF publiczne certyfikaty
*szyfrujące*, którymi SDK otacza danymi klucze do faktur i eksportów, i nigdy
nie trzyma klucza prywatnego. Magazyny z tej strony mieszkają w
`ksef2.certificate_stores` i przechowują Twoje własne klucze podpisu.

Klucze, których urządzenie nie pozwala wyeksportować, na przykład z HSM albo KMS,
są poza zakresem: te magazyny wymieniają pary, których klucz prywatny proces może
trzymać w pamięci.

## Owij parę w rekord

`SigningCertificate` wiąże wczytane `XAdESCredentials` ze środowiskiem, w którym
podpisujesz, i wywodzi metadane rekordu z samego certyfikatu.

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

`certificate_type` i `ksef_serial_number` są opcjonalne: pomiń je dla
certyfikatu, o którym KSeF nic nie wie, albo dla wygenerowanego samodzielnie.
Rekord ukrywa poświadczenia w `repr()`, odmawia pickle'owania i kopiowania oraz
nie ma serializacji do JSON-u, więc jedyną obsługiwaną postacią zapisu jest
`save()`.

## Trzymaj rekordy w pamięci

`InMemorySigningCertificateStore` i `AsyncInMemorySigningCertificateStore`
przechowują rekordy tak długo, jak żyje proces. Nic nie przeżywa restartu, co
w testach jest dokładnie tym, czego chcesz, a na produkcji znacznie rzadziej.

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

`FilesystemSigningCertificateStore` zapisuje jeden rekord JSON na certyfikat w
`<root>/<environment>/<fingerprint>.json`. Rekord zawiera certyfikat i jego
klucz prywatny jako PKCS#8 zaszyfrowany podanym hasłem. Tryb jawny nie istnieje.

Dostarczyciel hasła to zwykła funkcja od referencji do bajtów hasła. Jest
wywoływany przy każdym `save()` i `load()`, a magazyn nie trzyma ani hasła, ani
rekordu.

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

`list()` czyta wyłącznie certyfikat, więc nigdy nie prosi o hasło. Dlatego
sprawdzenie startowe albo ekran administracyjny jest tani: możesz pokazać, co
trzymasz, i zostawić operatorowi decyzję, zanim cokolwiek zostanie odszyfrowane.

Usunięcie rekordu zabiera tylko lokalny plik:

```python
removed = store.delete(info.reference)
```

Adapter asynchroniczny ma te same cztery operacje z `await`; pracę na plikach i
kluczach, razem z Twoją funkcją hasła, wykonuje w wątku roboczym:

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

Anulowane `await store.save(...)` mogło mimo to zapisać rekord: zapis albo trafia
na dysk w całości, albo nie ma go wcale, a powtórzenie tego samego `save()` jest
bezpieczne i zwraca zapisane metadane.

## Wskazuj certyfikat referencją

Magazyn nigdy nie wybiera certyfikatu „najnowszego” albo „najlepszego”: `load()`
zwraca dokładnie wskazaną referencję, także gdy rekord wygasł. To celowe —
cicha wymiana klucza podpisu to usterka, którą najgorzej diagnozuje się o 2 w
nocy.

Zapisz więc referencję we własnej konfiguracji, obok NIP-u i środowiska, które i
tak już tam trzymasz:

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

`info.reference` to dwa krótkie napisy bez materiału kluczowego, więc można go
logować, wpisać do pliku konfiguracyjnego i porównywać. Odnowienie certyfikatu
daje nowy odcisk, czyli nową referencję: sprawdź nową parę, a potem przełącz
konfigurację. Oba rekordy mogą leżeć w magazynie jednocześnie — tak właśnie
zostawia się stary klucz dostępny do momentu przełączenia.

## Zapisz wygenerowany certyfikat TEST

`generate_test_certificate()` buduje samopodpisaną parę RSA dla środowiska TEST.
Zwraca obiekty cryptography i nic nie przechowuje, więc wygenerowana para znika
razem z procesem, chyba że włożysz ją do magazynu:

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

Rekord jest teraz dostępny po restarcie, a `list(environment=Environment.TEST)`
pokazuje go bez hasła.

## Uwagi o bezpieczeństwie

- Na POSIX rekordy są tworzone jako `0600`, a katalogi jako `0700`; istniejący
  `root` zachowuje uprawnienia, które mu nadałeś. Na Windows plik dziedziczy
  listę ACL katalogu, więc ogranicz `root` sam, zanim cokolwiek do niego
  zapiszesz.
- Hasło jest pytane przy każdym `save()` i `load()` i nigdy nie jest
  przetrzymywane: ani na magazynie, ani w repr, ani między wywołaniami. `list()`
  nie potrzebuje hasła w ogóle.
- Wczytany klucz prywatny to zwykły obiekt w pamięci. Magazyn nic nie
  buforuje, ale też nie obiecuje wyzerowania pamięci, którą klucz zajmował.
  Traktuj zwrócony `SigningCertificate` jak sekret i pozbywaj się go po
  wykorzystaniu.
- Magazyn odmawia przejścia za dowiązanie symboliczne stojące w miejscu rekordu
  albo katalogu środowiska i nie przepisuje rekordu, którego nie może odczytać,
  więc rekord w nieobsługiwanej wersji zostaje na dysku nietknięty.
- Usunięcie rekordu nie unieważnia niczego w KSeF. Certyfikat pozostaje tam
  ważny, dopóki go nie odwołasz, a para już wczytana do pamięci podpisuje dalej.

## Błędy

Każda awaria jest `KSeFCertificateStoreError` i mówi, która operacja się nie
udała oraz którego rekordu dotyczyła. Całą hierarchię opisuje
[Error Reference](../reference/errors.md).

| Błąd | Kiedy zgłasza go magazyn w plikach |
| --- | --- |
| `KSeFArgumentError` | `root` nie był `Path`, dostarczyciel hasła nie był wywoływalny albo wartość potrzebna metodzie miała zły typ. |
| `KSeFCertificateStoreNotFoundError` | `load()` poproszono o referencję, pod którą nic nie leży. |
| `KSeFCertificateStoreConflictError` | `save()` dostał rekord o metadanych innych niż już zapisane pod tą referencją. |
| `KSeFCertificateStoreAccessError` | Pliki nie są do odczytu dla tego procesu, w drodze stoi dowiązanie symboliczne albo dostarczyciel hasła zwrócił puste hasło. |
| `KSeFCertificateStoreMaterialError` | Rekord jest uszkodzony, ma nieobsługiwaną postać, nie da się go odszyfrować albo nie zgadza się z referencją, pod którą leży. |
| `KSeFCertificateStoreUnavailableError` | Magazyn nie mógł przyjąć zapisu ani odczytu, na przykład przez pełny dysk. `outcome_ambiguous` ma wartość `True`, gdy magazyn nie potrafi powiedzieć, czy rekord trafił na dysk. |

Cokolwiek zgłosi Twoja własna funkcja hasła, wraca bez zmian: dostarczyciel,
który nie sięga po sekret, to usterka wdrożenia, a nie uszkodzony rekord.
