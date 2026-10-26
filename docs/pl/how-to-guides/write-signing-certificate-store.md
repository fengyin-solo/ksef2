---
title: Własny magazyn certyfikatów podpisu
description: Zaimplementuj protokół magazynu certyfikatów podpisu na keychainie, managerze sekretów, bazie danych albo innym backendzie trzymającym Twój certyfikat i klucz prywatny.
---

Magazyn certyfikatów podpisu trzyma Twój własny certyfikat podpisu XAdES razem z
jego kluczem prywatnym i oddaje parę jako jeden zwalidowany rekord. SDK ma
adaptery pamięciowe; napisz własny, gdy para musi przetrwać poza proces.

To nie jest `CertificateStoreProtocol`, czyli cache publicznych certyfikatów
szyfrowania KSeF, który klient główny trzyma jako `certificate_store=`. Te dwie
rzeczy nie mają ze sobą wspólnego: ten magazyn trzyma klucz prywatny, tamten
tylko materiał publiczny. Różnicę opisuje strona
[Certyfikaty](../concepts/certificates.md).

## Kiedy pisać własny

Napisz adapter, gdy Twój klucz faktycznie żyje w jednym z tych miejsc:

- wpisie w keychainie albo keyringu systemu operacyjnego,
- managerze sekretów, na przykład Vault albo chmurowym magazynie sekretów,
- wierszu w bazie danych, najlepiej z kluczem zaszyfrowanym kluczem, którego ten
  wiersz nie potrafi odczytać,
- blobie zaszyfrowanym przez KMS — o ile klucz KMS da się zaimportować do
  procesu.

Klucze, których urządzenie odmawia wyeksportować, są poza tym protokołem. Klucz
HSM albo KMS, który nigdy nie opuszcza sprzętu, nie może trafić do rekordu
`SigningCertificate`, bo rekord to certyfikat i klucz prywatny trzymane przez
proces. Podpisuj takimi kluczami poza SDK.

## Cztery metody

Zaimplementuj `SigningCertificateStoreProtocol` albo
`AsyncSigningCertificateStoreProtocol` dla klientów asynchronicznych i przekaż
obiekt do `client.authentication.with_stored_certificate()`. Adapter spełnia
protokół strukturalnie — nie dziedzicz po nim.

| Metoda | Kontrakt |
| --- | --- |
| `save(certificate)` | Zapisz parę atomowo, tak żeby rekord był kompletny albo nie było go wcale. Zapis rekordu o takich samych metadanych jak zapisany nic nie zmienia i zwraca metadane zapisane. Rekord o innych metadanych pod zapisaną referencją to konflikt. |
| `load(reference)` | Zwróć dokładnie rekord zapisany pod `reference`. Nigdy nie wybieraj „najnowszego” ani „najlepszego” certyfikatu, a przedawniony zwracaj tak, jak został zapisany. |
| `list(*, environment, certificate_type=None)` | Zwróć metadane każdego rekordu jednego środowiska, posortowane po `valid_from`, a następnie po `fingerprint_sha256`. Odczyt metadanych nigdy nie odsłania klucza prywatnego ani nie kontaktuje się z KSeF; przedawnione rekordy są w wyniku. |
| `delete(reference)` | Usuń lokalny rekord i zwróć, czy jakiś był. Certyfikat pozostaje ważny w KSeF, dopóki nie zostanie tam unieważniony. |

## Odbuduj rekord przy load()

Nie próbuj zapisywać obiektu `SigningCertificate`. Zapisz to, co potrzebne do jego
odbudowy — klucz, certyfikat i zapisane metadane — i odbudowuj rekord przy każdym
`load()`:

1. Przeczytaj i odszyfruj zapisany materiał klucza.
2. Zbuduj `XAdESCredentials(certificate, private_key)`. To sprawdza, że klucz
   prywatny należy do certyfikatu, więc rekord zapisany w złej parze psuje się
   przy odczycie, a nie przy uwierzytelnianiu.
3. Zbuduj `SigningCertificate(credentials, environment=..., certificate_type=...,
   ksef_serial_number=...)`. Rekord wyprowadza własną referencję, numer seryjny
   X.509, odcisk klucza publicznego i okres ważności z certyfikatu.
4. Porównaj `info` odbudowanego rekordu z metadanymi, które zapisałeś. Jeśli się
   różnią, backend zwrócił cudzy materiał: podnieś
   `KSeFCertificateStoreMaterialError` dla tej `reference` zamiast oddawać rekord.

## Który błąd podnieść

Podnoś błędy opisane w protokole, żeby odbiorca mógł sobie poradzić bez czytania
Twojego adaptera:

| Błąd | Podnieś go, gdy |
| --- | --- |
| `KSeFCertificateStoreNotFoundError` | Pod tą referencją nic nie jest zapisane. |
| `KSeFCertificateStoreConflictError` | `save()` znalazło pod tą referencją inny rekord, o innych metadanych. |
| `KSeFCertificateStoreAccessError` | Backend odrzucił poświadczenia albo uprawnienia wołającego. |
| `KSeFCertificateStoreUnavailableError` | Backend był nieosiągalny albo nie przyjął rekordu. |
| `KSeFCertificateStoreMaterialError` | Zapisany rekord jest uszkodzony, używa formatu, którego nie umiesz odczytać, nie da się odszyfrować albo nie pasuje do swojej referencji. |

Przekaż `operation=` metodę, która nie wyszła, oraz `reference=` rekord, którego
dotyczyła, żeby komunikat nazywał jedno i drugie. Ustaw `outcome_ambiguous=True`,
gdy zapis mógł wejść i wołający nie pozna tego po błędzie — to normalna sytuacja
przy zapisie, którego odpowiedź przepadła: wołający odczytuje wtedy rekord przed
powtórzeniem zapisu.

Sam błąd trzymaj bez sekretów. Komunikat nie może zawierać materiału klucza,
hasła, odpowiedzi backendu ani URL-a połączenia z poświadczeniami. Jeśli błąd
backendu mógł zawierać któreś z nich, podnieś własny błąd z `from None` zamiast
łączyć go z oryginalnym wyjątkiem.

Nie zamieniaj błędu w kodzie na `KSeFCertificateStoreUnavailableError`. Zły
argument, zapytanie zbudowane ze złego schematu albo brakująca metoda mają wyjść
jako zwykłe wyjątki Pythona, żeby nikt nie pomylił ich z backendem, w który
warto ponowić.

## Reprezentacja

`SigningCertificate` jest sekretem, dopóki żyje w pamięci: ukrywa poświadczenia w
`repr()`, odmawia picklowania i kopiowania oraz nie ma API serializacji. Twój
adapter dziedziczy tę dyscyplinę:

- `repr()` magazynu i wszystkiego, co zwraca, pokazuje wyłącznie liczby albo
  metadane — nigdy certyfikatu, odcisku, klucza ani wiersza, który je zawiera.
- Nie serializuj rekordu samodzielnie. Żadnego `pickle`, żadnego `model_dump`,
  żadnego JSON-a z `SigningCertificate` i żadnej linii logu z nim w środku.
- Pobieraj hasła kluczy, gdy ich potrzebujesz, i usuwaj je zaraz po użyciu. Nie
  trzymaj hasła na adapterze.

## Własność zasobów

Aplikacja tworzy połączenie z backendem i je zamyka. Klient SDK nigdy nie zamyka
magazynu: zamknięcie klienta zostawia magazyn używalny, a ten sam magazyn może
obsłużyć kilku klientów. Jeśli adapter potrzebuje połączenia na wywołanie,
otwieraj i zamykaj je w środku wywołania; jeśli potrzebuje puli, niech aplikacja
będzie właścicielem puli.

Opcjonalne biblioteki zewnętrzne importuj wewnątrz adaptera — w `__init__` albo w
metodzie, która ich potrzebuje — a nie przy imporcie modułu. Magazyn
potrzebujący klienta keychaina nie może przez to obciążać SDK dla wszystkich
innych.

## Testy adaptera

Przepuść każdy adapter, synchroniczny i asynchroniczny, przez ten sam kontrakt:

1. `save()` a potem `load()` zwraca tę samą parę. Podpisz coś załadowanym kluczem
   i zweryfikuj załadowanym certyfikatem: rundka porównująca tylko metadane może
   przejść, choć materiał klucza jest zepsuty.
2. Dwukrotny zapis takiego samego rekordu zostawia jeden rekord i zwraca te same
   metadane.
3. Zapis innego rekordu pod zapisaną referencją podnosi
   `KSeFCertificateStoreConflictError` i zostawia zapisany rekord czytalny.
4. Odczyt referencji, której nigdy nie zapisano, podnosi
   `KSeFCertificateStoreNotFoundError`.
5. `list()` zwraca tylko rekordy żądanego środowiska, filtruje po
   `certificate_type`, gdy podano ten typ, sortuje po `valid_from`, a następnie po
   `fingerprint_sha256`, i zawiera rekord przedawniony.
6. `delete()` zwraca `True` dla rekordu, który był, i `False` dla takiego, którego
   nie było, a rekord potem znika.
7. Jeden certyfikat zapisany w dwóch środowiskach to dwa niezależne rekordy.

## Minimalny szkic

Poniższy kształt to najmniej, co spełnia protokół synchroniczny. Backend to dict
bajtów, więc ciekawa jest część, którą `load()` musi odbudować.

```python
from ksef2 import Environment
from ksef2.certificate_stores import (
    SigningCertificate,
    SigningCertificateInfo,
    SigningCertificateRef,
)
from ksef2.models import CertificateTypeValue
from ksef2.xades import XAdESCredentials

class BytesStore:
    """Trzyma certyfikaty podpisu w mapie referencja na zapisane bajty."""

    def __init__(self, rows: dict[bytes, bytes]) -> None:
        self._rows = rows

    def save(self, certificate: SigningCertificate) -> SigningCertificateInfo:
        """Zapisz parę pod jej własną referencją i zwróć jej metadane."""
        ...  # Zakoduj certyfikat i klucz, zapisz je atomowo, zwróć metadane i
        # podnieś KSeFCertificateStoreConflictError, gdy referencja trzyma już
        # rekord o innych metadanych.

    def load(self, reference: SigningCertificateRef) -> SigningCertificate:
        """Odbuduj rekord zapisany pod ``reference``."""
        ...  # Przeczytaj zapisane bajty, podnosząc
        # KSeFCertificateStoreNotFoundError gdy ich nie ma, a potem odszyfruj
        # klucz i odbuduj rekord:
        # record = SigningCertificate(
        #     XAdESCredentials(certificate, private_key),
        #     environment=reference.environment,
        #     certificate_type=stored_certificate_type,
        #     ksef_serial_number=stored_ksef_serial_number,
        # )
        # if record.info.reference != reference:
        #     raise KSeFCertificateStoreMaterialError(
        #         "The stored record does not match its reference.",
        #         operation="load",
        #         reference=reference,
        #     )
        # return record

    def list(
        self,
        *,
        environment: Environment,
        certificate_type: CertificateTypeValue | None = None,
    ) -> tuple[SigningCertificateInfo, ...]:
        """Zwróć metadane każdego rekordu tego środowiska."""
        ...  # Filtruj po środowisku i, gdy podano, po certificate_type, a potem
        # sortuj po valid_from i odcisku. Nigdy nie odszyfruj tu klucza.

    def delete(self, reference: SigningCertificateRef) -> bool:
        """Usuń lokalny rekord i powiedz, czy jakiś był."""
        ...  # Zwróć True, gdy rekord usunięto, i False, gdy go nie było. Błędy
        # innych backendów to KSeFCertificateStoreError.
```

Dla klienta asynchronicznego uczyń każdą z czterech metod funkcją korutynową.
Podanie magazynu synchronicznego klientowi asynchronicznemu albo odwrotnie
podnosi `KSeFArgumentError`, zanim klient go dotknie.

## Powiązane strony

- [Uwierzytelnij się](authenticate.md): Uwierzytelnij się certyfikatem z magazynu.
- [Zarządzaj certyfikatami](manage-certificates.md): Zapisz certyfikat wydany przez KSeF obok jego klucza.
- [Certyfikaty](../concepts/certificates.md): Nie myl magazynu certyfikatów podpisu z cache'em certyfikatów szyfrowania.
- [Skonfiguruj magazyn certyfikatów](configure-certificate-store.md): Skonfiguruj cache publicznych certyfikatów szyfrowania KSeF.
