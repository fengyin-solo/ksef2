---
title: API niskiego poziomu
description: Wywołania operacji API zgodne ze schematem, przestrzenie nazw modeli raw i narzędzia niskiego poziomu.
---

API niskiego poziomu to zestaw metod SDK do kontroli na poziomie pojedynczych operacji API, bez wychodzenia poza transport biblioteki. Jest dostępne przez `client.raw` przed uwierzytelnieniem i `auth.raw` po uwierzytelnieniu.

Użyj go, gdy integracja wymaga własnego podpisu, własnego szyfrowania, dokładnej treści żądania z OpenAPI albo diagnostyki operacji. Większość aplikacji nadal powinna zaczynać od klientów wysokiego poziomu.

## Kontrakt

| Właściwość | Zachowanie niskiego poziomu |
| --- | --- |
| Transport | Ten sam stos middleware, ponowień, sprawdzeń cyklu życia i mapowania wyjątków co klient główny. |
| Uwierzytelnienie | `client.raw` jest nieuwierzytelnione. `auth.raw` używa transportu z tokenem Bearer tam, gdzie wymaga tego KSeF. |
| Modele | Żądania i odpowiedzi używają nazw ze schematu KSeF i OpenAPI, na przykład `referenceNumber`, `publicKeyId`, `authenticationToken`. |
| Parsowanie | Poprawne odpowiedzi JSON trafiają do wygenerowanych modeli `spec` albo uzupełniających `supp`. |
| Odpowiedzi binarne | XML faktur i UPO (Urzędowe Poświadczenie Odbioru) zwracane jako `bytes`. |
| Wersja asynchroniczna | Klient asynchroniczny ma te same moduły i nazwy metod. Wywołania sieciowe używają `await`. |

## Przestrzenie nazw modeli

Modele niskiego poziomu importuj ze wspieranego `ksef2.raw`, nie z wewnętrznych pakietów wygenerowanych:

```python
from ksef2.raw import spec, supp
```

| Przestrzeń | Do czego służy |
| --- | --- |
| `spec` | Wygenerowane modele żądań i odpowiedzi OpenAPI. |
| `supp` | Modele uzupełniające, używane tam, gdzie wygenerowany model OpenAPI wymaga wsparcia SDK. |
| `ksef2.raw.mappers` | Jawne przejścia z modeli zgodnych ze schematem do publicznych modeli SDK. |

## Eksportowane narzędzia

| Eksport | Do czego służy |
| --- | --- |
| `encrypt_token` | Szyfrowanie danych uwierzytelniania tokenem KSeF. |
| `generate_session_key` | Generowanie klucza AES i IV do szyfrowania sesji, faktury albo eksportu. |
| `encrypt_symmetric_key` | Szyfrowanie lokalnego materiału AES publicznym certyfikatem KSeF. |
| `encrypt_invoice` | Szyfrowanie bajtów XML faktury do wysyłki interaktywnej niskiego poziomu. |
| `sha256_b64` | Obliczanie SHA-256 w Base64 dla metadanych żądań niskiego poziomu. |
| `prepare_batch_package` | Budowanie zaszyfrowanej paczki faktur, gdy wywołujący sam prowadzi sesję wsadową niskiego poziomu. |

## Poziomy kontroli

| Poziom | Co ma SDK | Co ma wywołujący | Typowe wejście |
| --- | --- | --- | --- |
| Przepływ | Kolejność operacji, szyfrowanie, sprawdzanie statusu i mapowanie modeli. | Dane biznesowe i trwały zapis. | `auth.invoices`, `auth.batch`, klienci sesji. |
| Krok | Szczegóły protokołu jednego kroku przepływu SDK. | Kolejność i zapis stanu między krokami. | `session.send_invoice()`, `submission.wait()`. |
| Niski poziom | Transport, parsowanie odpowiedzi, mapowanie wyjątków. | Kolejność operacji, treść żądań ze schematu, szyfrowanie, sprawdzanie statusu. | `client.raw`, `auth.raw`. |

Zasada dotyczy właściciela sesji. Jeśli kod niskiego poziomu otwiera sesję, ten sam poziom zwykle powinien ją zamknąć i sprawdzać jej status. Jeśli sesję otwiera poziom wysoki, używaj zwróconego klienta sesji.

## Dalszy opis

- [Uwierzytelnianie niskiego poziomu](authentication.md): operacje uwierzytelniania `raw` oraz sekwencja tokena KSeF i XAdES.
- [Sesje i faktury niskiego poziomu](sessions-invoices.md): metody sesji, faktur, UPO i eksportu.
- [Mapa operacji API](endpoint-map.md): moduł `raw` i grupa metod dla danego obszaru KSeF.
