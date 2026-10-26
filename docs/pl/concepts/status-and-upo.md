---
title: Status i UPO
description: Statusy, sprawdzanie wyniku, dokumenty UPO i lokalne limity czasu w przepływach ksef2.
---

Przepływy KSeF są asynchroniczne. Wiele wywołań SDK zaczyna pracę i zwraca numer referencyjny. Dopiero inne wywołanie mówi, co stało się później.

Nie sprowadzaj tego do jednej flagi `done`. Każdy status odpowiada na inne pytanie i ma inny numer referencyjny.

## Którego statusu potrzebujesz?

| Pytanie | Moduł SDK | Typowy identyfikator |
| --- | --- | --- |
| Czy uwierzytelnianie się zakończyło? | `client.authentication` | numer referencyjny operacji uwierzytelniania |
| Czy sesja interaktywna albo wsadowa nadal się przetwarza? | klient sesji albo `auth.batch` | numer referencyjny sesji |
| Czy jedna wysłana faktura się udała, czy nie? | status faktury w sesji | numer referencyjny faktury |
| Czy przetworzone faktury widać w wyszukiwaniu? | zapytania o metadane `auth.invoices` | filtry, stronicowanie, numer KSeF |
| Czy paczka eksportu jest gotowa? | status eksportu `auth.invoices` | numer referencyjny eksportu |
| Czy token jest aktywny, czy unieważniony? | `auth.tokens` | numer referencyjny tokena |
| Czy operacja na uprawnieniach się zakończyła? | `auth.permissions` | numer referencyjny operacji |

Używaj modułu, który pasuje do pytania. Sesja może być zakończona, a jedna faktura w niej błędna. Eksport może nadal się przygotowywać, choć metadane faktur są już widoczne. Operacja na tokenie kończy się niezależnie od sesji wysyłki faktur.

## Status sesji

Status sesji jest podsumowaniem sesji interaktywnej albo wsadowej po stronie KSeF. Po przetworzeniu może zawierać liczniki i numery referencyjne stron UPO (Urzędowego Poświadczenia Odbioru).

```python
status = session.get_status()
print(
    status.status.code,
    status.invoice_count,
    status.successful_invoice_count,
    status.failed_invoice_count,
)
```

Kod statusu dotyczy sesji, a niekoniecznie każdej faktury w środku. Podsumowanie może mówić, że przetwarzanie się zakończyło, i jednocześnie podawać błędne faktury w `failed_invoice_count`. Gdy potrzebujesz szczegółów jednej faktury, sprawdź faktury sesji.

```python
failed = session.list_failed_invoices()
for invoice in failed.invoices:
    print(invoice.reference_number, invoice.status.code, invoice.status.details)
```

## Status faktury

Status faktury dotyczy jednej faktury w jednej sesji. Przy wysyłce interaktywnej numer referencyjny faktury zwykle dostajesz od razu z `send_invoice()`. Przy wysyłce wsadowej statusy poszczególnych faktur stają się widoczne, gdy KSeF przetworzy przesłaną paczkę.

Status po nadaniu numeru ma `ksef_number`. Status błędu niesie kod KSeF, opis i opcjonalne szczegóły.

```python
invoice_status = session.get_invoice_status(
    invoice_reference_number=sent.reference_number,
)
print(invoice_status.ksef_number, invoice_status.status.description)
```

## Dokumenty UPO

UPO (Urzędowe Poświadczenie Odbioru) to XML podpisany przez Ministerstwo Finansów. Zwrócone bajty traktuj jak materiał do audytu i zapisuj je trwale.

UPO nie jest dostępne w momencie wysyłki:

1. Wyślij albo prześlij dane faktury.

2. Poczekaj, aż KSeF przetworzy fakturę albo sesję.

3. Odczytaj numer referencyjny UPO albo użyj numeru referencyjnego faktury albo numeru KSeF.

4. Pobierz i zapisz bajty XML UPO.

SDK udostępnia typowe ścieżki UPO przez klientów sesji:

```python
invoice_upo = submission.download_upo()

session_upo_pages = session.download_upo()  # wszystkie strony, referencje rozwiązuje SDK
```

`download_upo()` nigdy nie czeka. Najpierw wywołaj `submission.wait()` dla UPO faktury albo `session.wait()` (po zamknięciu sesji) dla stron UPO sesji. Wywołane za wcześnie, `submission.download_upo()` zgłasza wyjątek `KSeFNotReadyError`. Warianty sesji zgłaszają go, dopóki KSeF przetwarza zamkniętą sesję. Sesja, która nadal jest otwarta, zgłasza `KSeFSessionError`. Oba wyjątki niosą `hint` wskazujący `wait()`.

`submission.download_upo()` wykonuje dokładnie jedno zapytanie. Warianty sesji raz odczytują status sesji, a potem pobierają kolejne strony UPO.

Odpowiedzi ze statusem mogą też podawać dane stron UPO, takie jak `download_url_expiration_date`. Do wywołań SDK używaj numerów referencyjnych i zapisuj pobrany XML, gdy już go masz.

## Sprawdzanie statusu i limit czasu

Metody oczekujące sprawdzają KSeF, aż stanie się jedna z trzech rzeczy:

- pojawi się oczekiwany stan;
- KSeF zgłosi błąd końcowy, który SDK tak klasyfikuje;
- minie lokalny limit czasu.

Lokalny limit czasu nie dowodzi, że operacja po stronie KSeF się nie udała. Oznacza tylko, że oczekiwany stan nie pojawił się przed ustawionym terminem.

:::note[Limit czasu jest lokalny]
Po upływie limitu wróć do sprawdzania po zapisanym numerze referencyjnym, zamiast ponownie wysyłać tę samą fakturę w ciemno. Pierwotna praca po stronie KSeF może nadal się zakończyć.
:::

Dobierz oczekiwanie do przepływu:

| Przepływ | Typowa metoda |
| --- | --- |
| Nadanie numeru KSeF w sesji interaktywnej | `submission.wait()` |
| Przetwarzanie sesji wsadowej | `session.wait()` |
| Gotowość paczki eksportu | `auth.invoices.export(...).wait()` |
| Aktywacja albo sprawdzenie tokena | `auth.tokens.generate(...).wait()` albo `auth.tokens.get_status()` |
| Nadanie albo cofnięcie uprawnienia | `operation.wait()` albo `auth.permissions.get_operation_status()` |
| Wydanie certyfikatu | `enrollment.wait()` albo `auth.certificates.get_enrollment_status()` |

## Co zapisywać

Zapisz tyle, żeby później sprawdzić status bez pierwotnego obiektu Pythona:

- numer referencyjny sesji;
- numer referencyjny faktury;
- numer KSeF po jego nadaniu;
- numer referencyjny UPO albo bajty XML UPO;
- numer referencyjny eksportu albo operacji dla przepływów poza sesją;
- ostatnią zaobserwowaną odpowiedź ze statusem, do audytu.

## Powiązane strony

- [Pobieranie statusu i UPO](../how-to-guides/get-status-and-upo.md): sesje interaktywne i wsadowe, a potem XML UPO.
- [Sesje](sessions.md): zdalne sesje, które wystawiają status.
- [Faktura w KSeF](invoice-lifecycle.md): faktura od wysyłki do numeru KSeF, metadanych, pobrania i UPO.
- [Obsługa błędów](../reference/errors.md): operacje odrzucone, nieudane, wygasłe i takie, które można ponowić.
