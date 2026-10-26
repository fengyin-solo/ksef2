---
title: Sesje
description: Stan sesji interaktywnej, wsadowej, uwierzytelniania i historii sesji w ksef2.
---

Sesja KSeF grupuje powiązane operacje po stronie systemu. Kilka wywołań API dostaje jeden numer referencyjny, żeby KSeF mógł przetworzyć zaszyfrowane faktury, udostępnić status i wystawić UPO (Urzędowe Poświadczenie Odbioru) po zakończeniu pracy.

W SDK obiekt sesji wskazuje tę zdalną pracę. Sam obiekt niczego nie rozstrzyga. Wiarygodną informację o stanie sesji daje tylko KSeF: jej numer referencyjny i zwracany status.

```text
klient uwierzytelniony
  -> otwarcie sesji online albo batch
    -> numer referencyjny sesji
      -> wysyłka/upload zaszyfrowanych danych faktury
        -> status, wyniki faktur, UPO
```

## Rodzaje sesji

W KSeF występuje kilka rodzajów sesji. Odpowiadają na różne pytania i są dostępne przez różne moduły SDK.

| Rodzaj sesji | Moduł SDK | Co reprezentuje |
| --- | --- | --- |
| Sesja interaktywna | `auth.online_session()` | Krótki przepływ do wysyłki jednej albo kilku faktur. |
| Sesja wsadowa | `auth.batch_session()` albo `auth.batch` | Przesłanie zaszyfrowanej paczki ZIP podzielonej na części. |
| Sesja uwierzytelniania | `auth.sessions` | Aktywne sesje utworzone przy uwierzytelnianiu, oparte na tokenie dostępu. |
| Historia sesji faktur | `auth.invoice_sessions` | Zakończone sesje interaktywne i wsadowe, które można odpytać po zamknięciu pierwotnego procesu. |

Pierwsze dwa rodzaje służą do wysyłki faktur. Sesje uwierzytelniania i historia sesji faktur służą do podglądu albo administracji.

## Sesja interaktywna

Sesja interaktywna służy do wysyłki na bieżąco. Otwierasz ją dla struktury faktury, na przykład `FormSchema.FA3`, a potem wysyłasz faktury pojedynczo. W formacie JSON (zrzuty modeli, zapisany stan i kursory stronicowania) `FormSchema` jest zapisywany jako nazwa elementu, na przykład `"FA3"`.

Otwarcie sesji jest lekkie. SDK pobiera publiczny certyfikat szyfrowania KSeF, tworzy materiał szyfrowania sesji, otwiera sesję po stronie KSeF i zwraca `OnlineSessionClient` przypisany do zwróconego `reference_number`.

```python
from ksef2 import FormSchema

with auth.online_session(form_code=FormSchema.FA3) as session:
    state = session.resume_state()
    print(state.reference_number, state.valid_until)
```

Klienta sesji interaktywnej używaj do wywołań związanych z fakturami wysłanymi w tej sesji: wysyłki, listy faktur sesji, sprawdzenia jednej faktury i pobrania UPO po numerze referencyjnym faktury albo numerze KSeF.

Menedżer kontekstu (`with`) wywołuje `close()` przy wyjściu z bloku. Zamknięcie sesji mówi KSeF, że kolejnych faktur nie będzie, i pozwala wygenerować zbiorcze UPO dla sesji.

:::tip[Zapisz numery, zanim przerwiesz proces]
Zanim zaczniesz długo czekać na status, przekażesz zadanie do kolejki albo zakończysz proces, zapisz numery referencyjne sesji i faktur. Obiekt Pythona można odtworzyć. Numery KSeF pozwalają innemu procesowi roboczemu wrócić do sprawdzenia statusu.
:::

## Wznawianie sesji

`online_session()` i `batch_session()` tą samą metodą otwierają sesję albo ją wznawiają. Podaj dokładnie jedną formę: `form_code=` (albo `prepared_batch=` / `batch_file=`), żeby otworzyć, lub `state=`, żeby wznowić. `state=` przyjmuje obiekt stanu albo jego JSON. Ze stanu pochodzi wszystko: kod formularza, klucze, ważność i żądania przesłania.

Aby wznowić przesyłanie paczki, przekaż też oryginalne `prepared_batch`.

```python
with auth.online_session(form_code=FormSchema.FA3) as session:
    saved = session.resume_state().to_json()      # przechowuj jak poświadczenie
    reference = session.send_invoice(xml).reference_number

# później, możliwe że w innym procesie
with auth.online_session(state=saved) as session:
    status = session.submission(reference).wait()  # uchwyt wcześniej wysłanej faktury
```

Wyjście z bloku `with` zamyka sesję w obu przypadkach. Zamknięcie sesji, która już jest zamknięta, nic nie robi: wznowiony klient najpierw pyta KSeF, więc nie wysyła drugiego żądania zamknięcia. Sesje wsadowe działają tak samo z `auth.batch_session(state=saved)`, a potem `session.wait()` i `session.download_upo()`. `resume_online_session()` i `resume_batch_session()` są wycofanymi aliasami. Stan sesji zawiera klucze szyfrowania. Nigdy go nie loguj.

Wznowione sesje, zadania eksportu `invoices.export(state=...)` i pozostałe obiekty klienta uwierzytelnionego współdzielą jeden transport. Wszystkie używają bieżącego tokena dostępu (`accessToken`) i odświeżają go, gdy trzeba (zobacz [Token dostępu odświeża się sam](authentication-methods.md#token-dostępu-odświeża-się-sam)). Wznowiony klient z wygasłym tokenem dostępu działa, dopóki token odświeżający (`refreshToken`) jest ważny. Jeśli wygasł także token odświeżający, wywołanie zgłasza wyjątek `KSeFAuthenticationExpiredError`. Uwierzytelnij się ponownie, a potem wznów sesję z zapisanego stanu.

## Sesja wsadowa

Sesja wsadowa służy do wysyłki wielu faktur naraz. Do KSeF nie idzie pojedynczy plik XML. Idzie przygotowana paczka ZIP z plikami XML faktur, podzielona na części i zaszyfrowana przed przesłaniem.

Zwykły przepływ obsługuje moduł wysokiego poziomu `auth.batch`:

1. Zbuduj paczkę ZIP z plików XML faktur albo z bajtów faktur trzymanych w pamięci.

2. Podziel paczkę na części przed szyfrowaniem.

3. Zaszyfruj każdą część i policz metadane paczki oraz części.

4. Otwórz sesję wsadową i odbierz instrukcje przesłania.

5. Prześlij wszystkie części, zamknij sesję i sprawdzaj status przetwarzania.

```python
prepared = auth.batch.prepare([Path("invoice-1.xml"), Path("invoice-2.xml")])

session = auth.batch.submit(prepared)
print(session.reference_number)
```

Przy sesji wsadowej zachowaj mapowanie między lokalnymi plikami źródłowymi a metadanymi przygotowanych faktur. KSeF podaje wynik każdej faktury w polach statusu faktury w sesji, takich jak `invoice_hash`, `invoice_file_name`, `reference_number` i późniejszy `ksef_number`.

Po błędzie przesłania wznów pierwotną sesję z jej oryginalną przygotowaną paczką. Wyjątek zachowuje paczkę również wtedy, gdy `submit(invoices)` przygotowuje ją wewnętrznie. Możesz też przekazać zachowane `prepared` jako `prepared_batch`. Wznowienie odrzuca zmiany danych, materiału szyfrowania i metadanych paczki przed przesłaniem. Nie przygotowuj ponownie faktur dla tej samej sesji.

```python
from ksef2 import KSeFBatchUploadError

try:
    session = auth.batch.submit([xml_bytes])
except KSeFBatchUploadError as error:
    with auth.batch_session(
        state=error.recovery_state(),
        prepared_batch=error.recovery_prepared_batch(),
    ) as session:
        session.upload_parts()
```

Oba obiekty odzyskiwania zawierają dane wrażliwe. Trzymaj je w pamięci albo w chronionym magazynie aplikacji. Ogólne `repr` i `model_dump` pomijają bajty paczki i klucze. JSON stanu celowo zawiera sekrety i adresy przesłania, ale nie bajty przygotowanej paczki. Starsze stany bez skrótu paczki nadal pozwalają pobrać status i UPO, ale nie pozwalają dołączyć paczki do przesłania.

Aby zachować przygotowaną paczkę po restarcie procesu, zapisz `prepared.to_sensitive_json()` w chronionym magazynie. Odtwórz ją przez `PreparedBatch.from_sensitive_json(saved)` i przekaż jako `prepared_batch=` razem z zapisanym stanem sesji. Taki zapis jest materiałem uwierzytelniającym: zawiera klucz AES i zaszyfrowane faktury. Ogólne zrzuty modeli i `repr` nigdy ich nie zawierają.

```python
from ksef2.models import PreparedBatch

# Zapisz oba ciągi w chronionym magazynie przed restartem.
saved = prepared.to_sensitive_json()
saved_state = session.resume_state().to_json()

# Po restarcie odczytaj oba ciągi z chronionego magazynu.
restored = PreparedBatch.from_sensitive_json(saved)
with auth.batch_session(state=saved_state, prepared_batch=restored) as session:
    session.upload_parts()
```

Format zapisu to `{"version": "1", "payload": {...}}`. Obie metody eksportu sekretów zwracają tę samą strukturę zgodną z JSON. Zaszyfrowane części są w Base64 bezpiecznym dla adresów URL, z dopełnieniem. Dla słownika użyj `from_sensitive_dict()`.

Wersje to łańcuchy liczb rozdzielonych kropkami, na przykład `"1"` albo `"1.2"`. Czytniki przyjmują wersję główną 1 oraz liczbę `1`. Odrzucają brak wersji, błędne wersje, wyższe wersje główne i nieznane pola przez `ValueError`, bez ujawniania zapisanych wartości. Czytniki nie obsługują zapisów bez wersji, pochodzących z wersji rozwojowej. Czytniki w serii 1.x nadal czytają wydane wersje zapisu. Niezgodny format wymaga nowej wersji i opisanej migracji. Zwykła walidacja Pydantic nie odczytuje tego formatu. Stany wznowienia sesji zachowują dotychczasowy format.

## Stan, status i historia

Te trzy pojęcia łatwo pomylić:

| Pojęcie | Znaczenie | Postać w SDK |
| --- | --- | --- |
| Stan | Lokalne dane potrzebne do odtworzenia sesji. Zawiera wrażliwy materiał szyfrowania sesji, a dla sesji wsadowej także adresy przesłania. | `OnlineSessionResumeState`, `BatchSessionResumeState` |
| Status | Aktualny obraz pracy po stronie KSeF. Mówi, czy przetwarzanie się udało, nie udało albo nadal trwa. | `SessionStatusResponse`, `SessionInvoiceStatusResponse` |
| Historia | Lista poprzednich sesji interaktywnych albo wsadowych. Użyj jej, gdy nie masz już pierwotnego obiektu lokalnego. | `auth.invoice_sessions` |

Stan sesji przydaje się do wznowienia operacji SDK, ale jest wrażliwy. Nie wypisuj go i nie zapisuj w logach. Do audytu i wsparcia zapisuj odpowiedzi ze statusem oraz historię sesji.

```python
status = session.get_status()
print(
    status.status.code,
    status.invoice_count,
    status.successful_invoice_count,
    status.failed_invoice_count,
)
```

## Co zapisywać

Zapisz co najmniej:

- numer referencyjny sesji;
- numer referencyjny faktury zwrócony po wysyłce;
- numer KSeF po przetworzeniu;
- skrót faktury albo nazwę pliku, żeby powiązać wynik sesji wsadowej z lokalnym plikiem;
- numer referencyjny UPO albo pobrane bajty UPO, gdy są dostępne;
- lokalny identyfikator korelacji z własnego systemu.

Sesja KSeF może żyć dłużej niż proces Pythona, który ją otworzył. Trwały zapis tych identyfikatorów pozwala ponowić pracę, później pobrać UPO i przeanalizować zgłoszenie.

## Powiązane strony

- [Wysyłanie faktur](../how-to-guides/send-invoices.md): otwarcie sesji interaktywnej albo wsadowej i wysyłka XML faktury.
- [Pobieranie statusu i UPO](../how-to-guides/get-status-and-upo.md): sprawdzanie statusu sesji i faktury, a potem pobranie UPO.
- [Faktura w KSeF](invoice-lifecycle.md): faktura od wysyłki XML do numeru KSeF, metadanych, pobrania i UPO.
- [Sesje i faktury niskiego poziomu](../reference/low-level/sessions-invoices.md): operacje API sesji i faktur.
