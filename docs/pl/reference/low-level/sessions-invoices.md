---
title: Sesje i faktury niskiego poziomu
description: Kontrakty raw sesji, faktur, UPO, eksportu i danych szyfrowania.
---

Użyj sesji i faktur niskiego poziomu, gdy integracja sama trzyma materiał szyfrowania, otwiera sesję, wysyła fakturę, szyfruje eksport albo sama ustala kolejność sprawdzania statusu.

## Co trzyma wywołujący

| Wartość | Źródło | Potrzebna do |
| --- | --- | --- |
| `aes_key` | `generate_session_key()` albo własne przechowywanie klucza | Szyfrowanie faktury, sesji i eksportu oraz późniejsze odszyfrowanie. |
| `iv` | `generate_session_key()` albo własne przechowywanie klucza | Metadane szyfrowania wysyłane do KSeF i lokalne operacje kryptograficzne. |
| `encrypted_key` | `encrypt_symmetric_key(aes_key, cert.certificate)` | `encryptedSymmetricKey` w żądaniach sesji albo eksportu. |
| `public_key_id` | Metadane publicznego certyfikatu KSeF | `publicKeyId` w żądaniach sesji albo eksportu. |
| `referenceNumber` | Odpowiedź KSeF na otwarcie sesji albo eksport | Późniejsza wysyłka, status, zamknięcie, UPO (Urzędowe Poświadczenie Odbioru) albo status eksportu. |

Jeżeli ten materiał utworzyła metoda wysokiego poziomu, wróć do pasującej metody wznowienia albo pobrania wysokiego poziomu. Nie odtwarzaj stanu szyfrowania z logów.

## Metody sesji

| Metoda | Zwraca | Do czego służy |
| --- | --- | --- |
| `auth.raw.session.open_online(body)` | `spec.OpenOnlineSessionResponse` | Otwarcie sesji interaktywnej żądaniem `OpenOnlineSessionRequest`. |
| `auth.raw.session.terminate_online(reference_number)` | `None` | Zamknięcie sesji interaktywnej po numerze referencyjnym. |
| `auth.raw.session.open_batch(body)` | `spec.OpenBatchSessionResponse` | Otwarcie sesji wsadowej żądaniem `OpenBatchSessionRequest`. |
| `auth.raw.session.close_batch(reference_number)` | `None` | Zamknięcie sesji wsadowej po przesłaniu wszystkich części. |
| `auth.raw.session.get_session_upo(reference_number, upo_reference_number)` | `bytes` | Pobranie bajtów UPO sesji. |
| `auth.raw.session.list_sessions(...)` | `spec.SessionsQueryResponse` | Historia sesji, z filtrami i opcjonalnym tokenem kontynuacji. |

## Metody faktur

| Metoda | Zwraca | Do czego służy |
| --- | --- | --- |
| `auth.raw.invoices.query_metadata(body, **params)` | `spec.QueryInvoicesMetadataResponse` | Jedna strona metadanych z `spec.InvoiceQueryFilters`. |
| `auth.raw.invoices.export(body)` | `spec.ExportInvoicesResponse` | Start eksportu faktur żądaniem `InvoiceExportRequest`. |
| `auth.raw.invoices.get_export_status(reference_number)` | `spec.InvoiceExportStatusResponse` | Sprawdzenie, czy paczka eksportu jest gotowa. |
| `auth.raw.invoices.download(ksef_number)` | `bytes` | Pobranie przetworzonego XML faktury po numerze KSeF. |
| `auth.raw.invoices.send(reference_number, body)` | `spec.SendInvoiceResponse` | Wysłanie jednej zaszyfrowanej faktury do otwartej sesji interaktywnej. |
| `auth.raw.invoices.get_session_status(reference_number)` | `spec.SessionStatusResponse` | Status sesji interaktywnej albo wsadowej. |
| `auth.raw.invoices.list_session_invoices(reference_number, ...)` | `spec.SessionInvoicesResponse` | Lista faktur sesji, które zostały przyjęte. |
| `auth.raw.invoices.list_failed_session_invoices(reference_number, ...)` | `spec.SessionInvoicesResponse` | Lista faktur sesji, które się nie udały. |
| `auth.raw.invoices.get_session_invoice_status(reference_number, invoice_reference_number)` | `spec.SessionInvoiceStatusResponse` | Status jednej faktury w sesji. |
| `auth.raw.invoices.get_invoice_upo_by_ksef(reference_number, ksef_number)` | `bytes` | UPO faktury po numerze KSeF. |
| `auth.raw.invoices.get_invoice_upo_by_reference(reference_number, invoice_reference_number)` | `bytes` | UPO faktury po numerze referencyjnym faktury w sesji. |

Metody z `continuation_token` wysyłają go jako `x-continuation-token`.

## Treść `OpenOnlineSessionRequest`

| Pole | Źródło |
| --- | --- |
| `formCode` | `spec.FormCode(...)` pasujący do struktury faktury. |
| `encryption.encryptedSymmetricKey` | `encrypted_key` zakodowany w Base64. |
| `encryption.initializationVector` | `iv` zakodowany w Base64. |
| `encryption.publicKeyId` | Identyfikator publicznego klucza KSeF użytego do szyfrowania. |

Zachowaj zwrócone `referenceNumber` razem z `aes_key` i `iv`.

## Treść `SendInvoiceRequest`

| Pole | Źródło |
| --- | --- |
| `invoiceHash` | `sha256_b64(invoice_xml)` |
| `invoiceSize` | `len(invoice_xml)` |
| `encryptedInvoiceHash` | `sha256_b64(encrypted_invoice)` |
| `encryptedInvoiceSize` | `len(encrypted_invoice)` |
| `encryptedInvoiceContent` | Zaszyfrowane bajty faktury zakodowane w Base64. |

`encrypt_invoice(xml_bytes=invoice_xml, key=aes_key, iv=iv)` tworzy zaszyfrowane bajty faktury. Wysyłka niskiego poziomu nie sprawdza statusu sama. Użyj `get_session_invoice_status()`, aż faktura osiągnie status końcowy.

## Treść eksportu

`auth.raw.invoices.export()` przyjmuje `InvoiceExportRequest`. Wywołujący podaje te same pola szyfrowania co przy sesjach:

| Grupa pól | Źródło |
| --- | --- |
| `encryption` | Zaszyfrowany materiał AES i `publicKeyId`. |
| `filters` | `spec.InvoiceQueryFilters`. |
| `compressionType` | `spec.CompressionType`, zwykle ZIP. |

Używaj wysokopoziomowego `auth.invoices.export(...).wait()`, chyba że sam odszyfrowujesz części paczki kluczem AES i IV, które wygenerowałeś.

## Przekazanie paczki wsadowej

`prepare_batch_package` jest eksportowane z `ksef2.raw` dla sesji wsadowej niskiego poziomu. Przygotowuje metadane zaszyfrowanej paczki ZIP i jej części. Wynikowe metadane pliku paczki można przekazać do:

| Punkt wejścia | Kiedy używać |
| --- | --- |
| `auth.raw.session.open_batch(body)` | Gdy chcesz sam złożyć żądanie otwarcia sesji wsadowej zgodne ze schematem. |
| `auth.open_batch_session(...)` | Gdy chcesz powiązać sesję SDK krok po kroku, a materiał szyfrowania zostaje u wywołującego. |

## Powiązane strony

- [API niskiego poziomu](overview.md): własność niskiego poziomu, przestrzenie nazw modeli i eksportowane narzędzia.
- [Mapa operacji API](endpoint-map.md): każdy moduł `raw`.
- [Wysyłanie faktur](../../how-to-guides/send-invoices.md): przepływy interaktywne i wsadowe wysokiego poziomu, gdy kontrola operacji `raw` nie jest potrzebna.
