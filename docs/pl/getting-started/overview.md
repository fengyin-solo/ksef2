---
title: Wprowadzenie
description: Punkt startowy dokumentacji ksef2, biblioteki Pythona z pełnym typowaniem do integracji z KSeF 2.0.
---

![ksef2](../../../sdk/assets/logo-dark.png)

**ksef2** to biblioteka (SDK) dla Pythona z pełnym typowaniem, która ułatwia integrację z API KSeF 2.0.

> **Nieoficjalne SDK.** ksef2 jest projektem o otwartym kodzie źródłowym, utrzymywanym przez społeczność.
> Nie publikuje go, nie zatwierdza i nie wspiera Ministerstwo Finansów.
> O tym, jak działa KSeF i jakie obowiązują zasady, rozstrzyga oficjalna dokumentacja systemu.

[Oficjalna dokumentacja API KSeF v2](https://api-test.ksef.mf.gov.pl/docs/v2/) opisuje API KSeF 2.0, na którym opiera się ksef2.

Biblioteka jest dla osób, które budują własne integracje, automatyzacje i narzędzia back-office wokół KSeF i nie chcą samodzielnie pisać obsługi HTTP, cyklicznego sprawdzania statusu ani szyfrowania.

Z KSeF pracujesz przez wygodny interfejs zgodny z dobrymi praktykami Pythona. Dzięki temu możesz zająć się logiką biznesową, a nie szczegółami API. Biblioteka ukrywa wiele szczegółów komunikacji, ale nie zamyka drogi do niższego poziomu. Gdy potrzebujesz pełnej kontroli nad żądaniami i odpowiedziami, korzystaj bezpośrednio z metod odpowiadających operacjom API.

## Następne kroki

- [Szybki start](../getting-started/quickstart.md): działający przykład uwierzytelniania, wysyłania, wyszukiwania i pobierania faktur.
- [Działanie SDK](../concepts/overview.md): model klientów, uwierzytelnianie i przepływy faktur w bibliotece.
- [Spis poradników](../how-to-guides/overview.md): wysyłka faktur w sesji interaktywnej albo wsadowej, wyszukiwanie z filtrami i stronicowaniem oraz pobieranie pojedynczej faktury albo paczki eksportu.
- [API niskiego poziomu](../reference/low-level/overview.md): bezpośrednie wywołania operacji API, gdy potrzebujesz pełnej kontroli.
