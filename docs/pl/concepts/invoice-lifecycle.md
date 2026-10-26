---
title: Faktura w KSeF
description: Droga faktury od wysłania XML do numeru KSeF, metadanych, pobrania i UPO.
---

W KSeF wysłanie faktury zaczyna przetwarzanie, ale nie jest jeszcze wynikiem. API najpierw przyjmuje zaszyfrowane dane faktury do sesji. Dopiero potem KSeF asynchronicznie sprawdza fakturę i ją przetwarza.

SDK odzwierciedla ten model. Wysyłka najpierw zwraca obiekt przetwarzania. Numer KSeF, widoczność w metadanych, pobranie faktury i UPO (Urzędowe Poświadczenie Odbioru) pojawiają się później.

```text
XML FA(3)
  -> sesja online albo batch
    -> numer referencyjny faktury
      -> przetwarzanie KSeF
        -> numer KSeF
          -> metadane, pobranie, UPO
        -> status niepowodzenia faktury
```

## Etapy

1. Przygotuj poprawny XML faktury.

   SDK może wysłać bajty z pliku albo bajty wygenerowane przez builder FA(3).

2. Wyślij XML przez sesję interaktywną albo wsadową.

   Sesja interaktywna wysyła faktury pojedynczo. Sesja wsadowa przesyła przygotowaną paczkę ZIP i pokazuje wynik każdej faktury po przetworzeniu paczki.

3. Zapisz zwrócone numery.

   Numer referencyjny faktury jest pierwszym trwałym identyfikatorem wysłanej faktury. Numer referencyjny sesji mówi KSeF, w której sesji ta faktura została wysłana.

4. Sprawdzaj status sesji albo faktury.

   Poprawna odpowiedź HTTP nie oznacza jeszcze, że faktura ma numer KSeF.

5. Końcowych identyfikatorów używaj do pobierania i audytu.

   Po poprawnym przetworzeniu numer KSeF jest stabilnym identyfikatorem do bezpośredniego pobierania, uzgodnień, metadanych i wielu spraw wsparcia.

## Wysłanie nie oznacza nadania numeru KSeF

`send_invoice()` szyfruje XML i wysyła go do otwartej sesji interaktywnej. Zwraca `reference_number` faktury.

`send_invoice()` zwraca obiekt `InvoiceSubmission`. Jego `wait()` sprawdza status faktury, aż KSeF nada `ksef_number`, zgłosi błąd końcowy albo minie lokalny limit czasu.

```python
submission = session.send_invoice(xml_bytes)
print(submission.reference_number)

status = session.get_invoice_status(
    invoice_reference_number=sent.reference_number,
)
print(status.status.code, status.ksef_number)
```

:::caution[Sukces połączenia nie jest sukcesem biznesowym]
Udane wywołanie wysyłki oznacza, że KSeF przyjął żądanie do sesji. Faktura może nadal być przetwarzana albo później nie przejść sprawdzenia.
:::

## Identyfikatory, których nie warto mieszać

| Identyfikator | Gdzie się pojawia | Do czego służy |
| --- | --- | --- |
| Lokalny numer faktury | W XML faktury i w lokalnym systemie. | Powiązanie biznesowe przed przetworzeniem przez KSeF i po nim. |
| Numer referencyjny sesji | Po otwarciu sesji interaktywnej albo wsadowej. | Odnalezienie zdalnej wysyłki. |
| Numer referencyjny faktury | Odpowiedź z wysyłki i status faktury w sesji. | Sprawdzenie jednej faktury i pobranie jej UPO. |
| Skrót faktury | Status faktury w sesji i przygotowanie paczki. | Powiązanie wyników sesji wsadowej z lokalnymi plikami. |
| Numer KSeF | Poprawny status faktury i metadane. | Stabilny identyfikator KSeF do pobierania, uzgodnień i wsparcia. |
| Numer referencyjny UPO | Status sesji, gdy dostępne jest zbiorcze UPO. | Pobranie UPO sesji albo paczki. |

Przy wysyłce wsadowej numer referencyjny faktury może nie być widoczny, dopóki KSeF nie przetworzy przesłanej paczki. Zachowaj metadane przygotowanej paczki, żeby `invoice_hash` i `invoice_file_name` łączyły wyniki KSeF z lokalnymi plikami.

## Metadane i pobieranie są późniejszym odczytem

Status sesji mówi, co stało się z wysyłką. Metadane i pobieranie faktury służą do odczytu, gdy KSeF już przetworzy fakturę i zapisze ją u siebie.

| Sposób odczytu | Najlepsze pytanie |
| --- | --- |
| Status faktury w sesji | Czy ta wysłana faktura dostała numer KSeF, czy nie przeszła przetwarzania? |
| Zapytanie o metadane | Które przetworzone faktury pasują do filtrów, ról i dat? |
| Bezpośrednie pobranie faktury | Daj XML dla znanego numeru KSeF. |
| Paczka eksportu | Daj większy, przefiltrowany zestaw plików XML. |
| UPO | Daj urzędowe poświadczenie dla przyjętej faktury albo sesji. |

```python
invoice_xml = auth.invoices.download(status.ksef_number)
print(len(invoice_xml))
```

## Daty nie są zamienne

Metadane KSeF podają kilka dat. Wybieraj datę według przepływu, a nie według etykiety, która wygląda najwygodniej.

| Data | Znaczenie |
| --- | --- |
| `issue_date` | Data wystawienia zapisana na fakturze. |
| `invoicing_date` | Data przyjęcia faktury w KSeF do dalszego przetwarzania. |
| `acquisition_date` | Data nadania numeru KSeF. |
| `permanent_storage_date` | Data trwałego zapisu faktury w repozytorium KSeF. |

Do synchronizacji przyrostowej lepiej pasuje model trwałego zapisu opisany na stronach o zapytaniach i eksporcie. Jest pomyślany tak, żeby nie pomijać faktur mimo asynchronicznego przetwarzania w KSeF.

## Powiązane strony

- [Budowanie faktur FA(3)](../how-to-guides/build-fa3-invoices.md): poprawny XML faktury przed wysyłką.
- [Wysyłanie faktur](../how-to-guides/send-invoices.md): sesja interaktywna albo wsadowa.
- [Pobieranie statusu i UPO](../how-to-guides/get-status-and-upo.md): status sesji i faktury, a potem UPO.
- [Wyszukiwanie i eksport paczek](querying-and-exports.md): zapytania o metadane, paczki eksportu i pobieranie przyrostowe.
- [Pobieranie faktur](../how-to-guides/download-invoices.md): XML faktury bezpośrednio albo z paczki eksportu.
