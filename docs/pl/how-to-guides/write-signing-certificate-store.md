---
title: Własny magazyn certyfikatów podpisu
description: Własna implementacja magazynu certyfikatów podpisu na pęku kluczy, w menedżerze sekretów, w bazie danych albo w innym miejscu, które trzyma certyfikat i klucz prywatny.
---

Magazyn certyfikatów podpisu trzyma Twój certyfikat podpisu XAdES razem z kluczem prywatnym i oddaje parę jako jeden sprawdzony rekord. SDK ma adaptery pamięciowe. Napisz własny, gdy para ma przetrwać poza procesem.

To nie jest `CertificateStoreProtocol`, czyli pamięć podręczna publicznych certyfikatów szyfrowania KSeF, którą klient główny trzyma jako `certificate_store=`. Te dwa magazyny nie mają ze sobą nic wspólnego. Ten trzyma klucz prywatny, tamten tylko materiał publiczny. Różnicę opisuje strona [Certyfikaty](../concepts/certificates.md).

## Kiedy pisać własny

Napisz adapter, gdy klucz naprawdę leży w jednym z tych miejsc:

- we wpisie pęku kluczy albo keyringu systemu operacyjnego,
- w menedżerze sekretów, na przykład w Vault albo w chmurowym magazynie sekretów,
- w wierszu bazy danych, najlepiej z kluczem zaszyfrowanym kluczem, którego ten wiersz nie potrafi odczytać,
- w zaszyfrowanym obiekcie binarnym z KMS, o ile klucz KMS da się wczytać do procesu.

Klucz, którego urządzenie nie pozwala wyeksportować, jest poza tym protokołem. Klucz HSM albo KMS, który nigdy nie opuszcza sprzętu, nie może trafić do rekordu `SigningCertificate`, bo rekord to certyfikat i klucz prywatny trzymane przez proces. Takim kluczem podpisuj poza SDK.

## Cztery metody

Zaimplementuj `SigningCertificateStoreProtocol` albo `AsyncSigningCertificateStoreProtocol` dla klientów asynchronicznych i przekaż obiekt do `client.authentication.with_stored_certificate()`. Adapter spełnia protokół strukturalnie. Nie dziedzicz po nim.

| Metoda | Kontrakt |
| --- | --- |
| `save(certificate)` | Zapisz parę atomowo, tak żeby rekord był kompletny albo nie było go wcale. Zapis rekordu o takich samych metadanych jak zapisany nic nie zmienia i zwraca metadane już zapisane. Rekord o innych metadanych pod zapisanym wskazaniem to konflikt. |
| `load(reference)` | Zwróć dokładnie rekord zapisany pod `reference`. Nigdy nie wybieraj „najnowszego” ani „najlepszego” certyfikatu. Rekord po terminie ważności zwróć taki, jaki został zapisany. |
| `list(*, environment, certificate_type=None)` | Zwróć metadane każdego rekordu jednego środowiska, posortowane po `valid_from`, a potem po `fingerprint_sha256`. Odczyt metadanych nigdy nie odsłania klucza prywatnego i nie kontaktuje się z KSeF. Rekordy po terminie ważności są w wyniku. |
| `delete(reference)` | Usuń lokalny rekord i zwróć, czy jakiś był. Certyfikat pozostaje ważny w KSeF, dopóki nie zostanie tam unieważniony. |

## Odbuduj rekord przy load()

Nie próbuj zapisywać obiektu `SigningCertificate`. Zapisz to, co potrzebne do jego odbudowy: klucz, certyfikat i zapisane metadane. Rekord składaj przy każdym `load()`:

1. Przeczytaj i odszyfruj zapisany materiał klucza.
2. Zbuduj `XAdESCredentials(certificate, private_key)`. To sprawdza, że klucz prywatny należy do certyfikatu, więc zła para psuje się przy odczycie, a nie przy uwierzytelnianiu.
3. Zbuduj `SigningCertificate(credentials, environment=..., certificate_type=..., ksef_serial_number=...)`. Rekord sam wyprowadza wskazanie (środowisko i odcisk palca certyfikatu), numer seryjny X.509, odcisk palca klucza publicznego i okres ważności z certyfikatu.
4. Porównaj `info` odbudowanego rekordu z metadanymi, które zapisałeś. Jeśli się różnią, backend zwrócił cudzy materiał. Zgłoś `KSeFCertificateStoreMaterialError` dla tego `reference`, zamiast oddawać rekord.

## Który błąd zgłosić

Zgłaszaj błędy opisane w protokole, żeby odbiorca mógł sobie poradzić bez czytania Twojego adaptera:

| Błąd | Zgłoś go, gdy |
| --- | --- |
| `KSeFCertificateStoreNotFoundError` | Pod tym wskazaniem nic nie jest zapisane. |
| `KSeFCertificateStoreConflictError` | `save()` znalazło pod tym wskazaniem inny rekord, o innych metadanych. |
| `KSeFCertificateStoreAccessError` | Backend odrzucił dane uwierzytelniające albo uprawnienia wywołującego. |
| `KSeFCertificateStoreUnavailableError` | Backend był nieosiągalny albo nie przyjął rekordu. |
| `KSeFCertificateStoreMaterialError` | Zapisany rekord jest uszkodzony, używa formatu, którego nie umiesz odczytać, nie da się go odszyfrować albo nie pasuje do swojego wskazania. |

Przekaż `operation=` jako metodę, która nie wyszła, oraz `reference=` jako rekord, którego dotyczyła, żeby komunikat nazywał jedno i drugie. Ustaw `outcome_ambiguous=True`, gdy zapis mógł wejść, a wywołujący nie pozna tego po błędzie. To zwykła sytuacja przy zapisie, którego odpowiedź przepadła. Wywołujący odczytuje wtedy rekord przed powtórzeniem zapisu.

Sam błąd trzymaj bez sekretów. Komunikat nie może zawierać materiału klucza, hasła, odpowiedzi backendu ani adresu URL połączenia z danymi uwierzytelniającymi. Jeśli błąd backendu mógł zawierać któreś z nich, zgłoś własny błąd z `from None`, zamiast łączyć go z oryginalnym wyjątkiem.

Nie zamieniaj błędu w kodzie na `KSeFCertificateStoreUnavailableError`. Zły argument, zapytanie zbudowane ze złego schematu albo brakująca metoda mają wyjść jako zwykłe wyjątki Pythona, żeby nikt nie pomylił ich z backendem, w który warto ponowić żądanie.

## Reprezentacja

`SigningCertificate` jest sekretem, dopóki żyje w pamięci. Ukrywa parę w `repr()`, nie daje się zapisać przez pickle ani skopiować i nie ma API serializacji. Twój adapter trzyma tę samą zasadę:

- `repr()` magazynu i wszystkiego, co zwraca, pokazuje wyłącznie liczby albo metadane. Nigdy certyfikatu, odcisku palca, klucza ani wiersza, który je zawiera.
- Nie serializuj rekordu samodzielnie. Żadnego `pickle`, żadnego `model_dump`, żadnego JSON-a z `SigningCertificate` i żadnej linii logu z nim w środku.
- Pobieraj hasła kluczy, gdy ich potrzebujesz, i usuwaj je zaraz po użyciu. Nie trzymaj hasła na adapterze.

## Własność zasobów

Aplikacja tworzy połączenie z backendem i je zamyka. Klient SDK nigdy nie zamyka magazynu. Zamknięcie klienta zostawia magazyn używalny, a ten sam magazyn może obsłużyć kilku klientów. Jeśli adapter potrzebuje połączenia na wywołanie, otwieraj i zamykaj je wewnątrz wywołania. Jeśli potrzebuje puli, właścicielem puli jest aplikacja.

Opcjonalne biblioteki zewnętrzne importuj wewnątrz adaptera, w `__init__` albo w metodzie, która ich potrzebuje, a nie przy imporcie modułu. Magazyn, który potrzebuje klienta pęku kluczy, nie może przez to obciążać SDK dla wszystkich innych.

## Testy adaptera

Przepuść każdy adapter, synchroniczny i asynchroniczny, przez ten sam kontrakt:

1. `save()`, a potem `load()`, zwraca tę samą parę. Podpisz coś załadowanym kluczem i zweryfikuj załadowanym certyfikatem. Test, który porównuje tylko metadane, może przejść, choć materiał klucza jest zepsuty.
2. Dwukrotny zapis takiego samego rekordu zostawia jeden rekord i zwraca te same metadane.
3. Zapis innego rekordu pod zapisanym wskazaniem zgłasza `KSeFCertificateStoreConflictError` i zostawia zapisany rekord do odczytu.
4. Odczyt wskazania, którego nigdy nie zapisano, zgłasza `KSeFCertificateStoreNotFoundError`.
5. `list()` zwraca tylko rekordy żądanego środowiska, filtruje po `certificate_type`, gdy podano ten typ, sortuje po `valid_from`, a następnie po `fingerprint_sha256`, i zawiera rekord po terminie ważności.
6. `delete()` zwraca `True` dla rekordu, który był, i `False` dla takiego, którego nie było. Potem rekord znika.
7. Jeden certyfikat zapisany w dwóch środowiskach to dwa niezależne rekordy.

## Minimalny szkic

Poniżej jest najmniej, co spełnia protokół synchroniczny. Backend to słownik bajtów, więc istotna jest część, którą `load()` musi odbudować.

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

Dla klienta asynchronicznego zrób z każdej z czterech metod funkcję korutynową. Podanie magazynu synchronicznego klientowi asynchronicznemu albo odwrotnie zgłasza `KSeFArgumentError`, zanim klient go dotknie.

## Powiązane strony

- [Uwierzytelnianie](authenticate.md): Uwierzytelnij się certyfikatem z magazynu.
- [Zarządzanie certyfikatami](manage-certificates.md): Zapisz certyfikat wydany przez KSeF obok jego klucza.
- [Certyfikaty](../concepts/certificates.md): Nie myl magazynu certyfikatów podpisu z pamięcią podręczną certyfikatów szyfrowania.
- [Konfiguracja magazynu certyfikatów](configure-certificate-store.md): Skonfiguruj pamięć podręczną publicznych certyfikatów szyfrowania KSeF.
