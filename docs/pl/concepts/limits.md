---
title: Limity i ponawianie żądań
description: Limity kontekstu logowania, limity podmiotu, limity liczby żądań oraz terminy sprawdzania statusu i ponowień.
---

Limity KSeF są częścią projektu integracji. Od nich zależy, ile faktur zmieści się w sesji, jak często proces roboczy może sprawdzać status, czy lepiej pobrać paczkę eksportu niż pojedyncze faktury i jak ostrożnie ponawiać żądania po ograniczeniu liczby wywołań.

SDK pozwala odczytać limity i administracyjnie je nadpisać przez `auth.limits`. Większość aplikacji powinna traktować limity jako dane do harmonogramu, a nie jako wartości zmieniane w zwykłym przepływie biznesowym.

## Rodzaje limitów

| Rodzaj | Model SDK | Na co wpływa |
| --- | --- | --- |
| Limity kontekstu logowania | `ContextLimits` | Liczba faktur i rozmiar danych w sesji interaktywnej oraz wsadowej. |
| Limity podmiotu | `SubjectLimits` | Rejestracja i wydawanie certyfikatów dla uwierzytelnionego podmiotu. |
| Limity liczby żądań | `ApiRateLimits` | Liczba żądań na sekundę, minutę i godzinę dla grup operacji API. |

```python
context = auth.limits.get_context_limits()
print(context.online_session.max_invoices)
print(context.batch_session.max_invoice_size_mb)

rate = auth.limits.get_api_rate_limits()
print(rate.invoice_send.per_minute)
```

## Jak limity wpływają na przepływ

Sesji interaktywnej używaj przy małej liczbie faktur albo gdy faktura ma wyjść od razu. Sesji wsadowej używaj, gdy faktury można zebrać w paczkę. Eksportu używaj, gdy potrzebujesz większego zestawu do pobrania. Powtarzane pobieranie pojedynczych faktur i bardzo częste zapytania przyrostowe zwykle źle się sprawdzają w produkcyjnej synchronizacji.

W aplikacji produkcyjnej traktuj KSeF jak zdalny zapis, z którego synchronizujesz dane w kontrolowanych odstępach. Metadane i treść faktur trzymaj lokalnie, a ekrany użytkownika obsługuj z lokalnego magazynu.

:::caution[Limity są danymi wejściowymi integracji]
Rozmiar paczki, decyzja o eksporcie, rytm sprawdzania statusu i sposób ponawiania żądań powinny wynikać z limitów KSeF oraz z wymagań operacyjnych. Nie ukrywaj nadpisań limitów w zwykłym kodzie przetwarzania faktur.
:::

## Limit czasu sprawdzania statusu

Wiele przepływów KSeF jest asynchronicznych. SDK ma metody takie jak `.wait()` na wysyłce faktury, sesji i zadaniu eksportu, a także `download(..., timeout=...)` i oczekiwanie na aktywację tokena.

Limit czasu tych metod dotyczy całego przepływu. To nie jest limit czasu pojedynczego połączenia HTTP. Jeśli limit minie, oczekiwany stan KSeF nie pojawił się na czas. Nie zawsze oznacza to, że operacja po stronie KSeF się nie udała.

## Kiedy ponawiać żądanie

Transport klienta głównego może ponowić błędy połączenia i te odpowiedzi KSeF, które nadają się do ponowienia. Nie każdą operację można jednak bezpiecznie powtórzyć w ciemno. Wysyłkę faktury, nadanie uprawnienia, rejestrację certyfikatu, wygenerowanie tokena i otwarcie sesji ponawiaj w kodzie aplikacji, z zapisanym numerem referencyjnym i zasadami właściwymi dla tego przepływu.

Gdy KSeF ogranicza liczbę żądań, uwzględnij zwróconą wskazówkę i zwolnij harmonogram procesu roboczego. Jeśli przepływ ma już numer referencyjny, sprawdź status albo wznów pracę od tego numeru, zamiast zakładać operację od nowa.

## Powiązane strony

- [Zarządzanie limitami](../how-to-guides/manage-limits.md): odczyt limitów kontekstu logowania, podmiotu i liczby żądań.
- [Operacje](../reference/operations.md): limity czasu, ponowienia, sprawdzanie statusu i bezpieczne powtórzenie.
- [Faktura w KSeF](invoice-lifecycle.md): wybór sesji interaktywnej albo wsadowej według przepływu i liczby faktur.
- [Wyszukiwanie i eksport paczek](querying-and-exports.md): eksport i pobieranie przyrostowe z uwzględnieniem limitów KSeF.
