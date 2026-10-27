---
title: Wyszukiwanie dostawców PEPPOL
description: Wyszukuj dostawców usług PEPPOL zarejestrowanych w KSeF.
---

Użyj `client.peppol`, gdy potrzebujesz publicznej listy dostawców usług PEPPOL zarejestrowanych w KSeF. To moduł klienta głównego i nie wymaga uwierzytelniania.

## Wyszukaj dostawców

`list()` zwraca `Pager`. Iteruj po nim, żeby dostać każdego dostawcę, wywołaj `.pages()` dla list wielkości strony albo `.first_page()`, żeby wykonać jedno żądanie.

### Wszyscy dostawcy

```python
for provider in client.peppol.list():
    print(provider.id, provider.name, provider.date_created)

# PeppolProvider
# {
#   "id": "PPL123456",
#   "name": "Example PEPPOL Provider",
#   "date_created": "2026-06-25T10:00:00Z"
# }
```

### Jedna strona

```python
first = client.peppol.list().first_page()
```

## Zapisz wybory dostawców

Rekordy dostawców są danymi słownikowymi. Pobierz je z KSeF, a potem zapisz identyfikator i nazwę wyświetlaną do wyboru użytkownika albo do sprawdzenia w produkcie.

```python
providers_by_id = {
    provider.id: provider.name
    for provider in client.peppol.list()
}
```

## Zalecany przebieg

1. Wyszukaj dostawców z klienta głównego.

2. Zapisz identyfikatory i nazwy w pamięci podręcznej danych słownikowych aplikacji.

3. Używaj identyfikatorów przy sprawdzaniu wyborów użytkownika albo danych związanych z PEPPOL.

4. Odświeżaj tę kopię zgodnie z tym, jak świeże dane są potrzebne w produkcie.

## Następne strony

- [Konfiguracja klienta](client-setup.md): klient główny używany do publicznych zapytań o dostawców PEPPOL.
- [PEPPOL](../concepts/peppol.md): gdzie dane dostawców PEPPOL mieszczą się w SDK.
