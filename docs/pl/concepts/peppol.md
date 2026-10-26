---
title: PEPPOL
description: Wyszukiwanie dostawców PEPPOL i jego miejsce w SDK.
---

Wyszukiwanie dostawców PEPPOL jest publicznym przepływem klienta głównego. Nie wymaga uwierzytelnionego kontekstu logowania i nie bierze udziału w przetwarzaniu sesji faktur.

Traktuj je jako dane słownikowe: do listy dostawców, sprawdzenia identyfikatora albo odświeżenia lokalnej kopii. Trzymaj je osobno od wysyłki faktur, zapytań o metadane KSeF, eksportów i UPO (Urzędowego Poświadczenia Odbioru).

:::note[Tylko publiczne wyszukiwanie]
Wyszukiwanie PEPPOL nie potwierdza doręczenia, przyjęcia faktury przez KSeF ani stanu sesji. Odczytuje tylko dane dostawców zapisane w KSeF.
:::

## Gdzie jest w SDK

PEPPOL jest na kliencie głównym, obok innych publicznych modułów do odczytu:

```python
for provider in client.peppol.list():
    print(provider.id, provider.name)
```

`list()` zwraca `Pager` po stronicowanej odpowiedzi. Iteracja sama przechodzi po stronach, `.pages()` zwraca po jednej liście na stronę, a `.first_page()` wykonuje pojedyncze żądanie.

```python
providers_by_id = {
    provider.id: provider.name
    for provider in client.peppol.list()
}
```

## Granica produktu

Rekordy dostawców to dane słownikowe. Zapisuj identyfikatory i nazwy zgodnie z tym, jak świeże dane są Ci potrzebne, i odświeżaj tę kopię niezależnie od procesów roboczych, które wysyłają faktury.

Łącz to wyszukiwanie z fakturami tylko wtedy, gdy Twój produkt ma własny krok PEPPOL, na przykład wybór identyfikatora dostawcy przed zbudowaniem danych właściwych dla integracji.

## Powiązane strony

- [Wyszukiwanie dostawców PEPPOL](../how-to-guides/query-peppol-providers.md): jedna strona albo przejście przez wszystkich dostawców w kodzie SDK.
- [Działanie SDK](overview.md): PEPPOL wśród modułów klienta głównego.
- [Konfiguracja klienta](../how-to-guides/client-setup.md): klient główny używany do publicznego wyszukiwania dostawców.
