---
title: Zarządzaj tokenami
description: Generuj, listuj, sprawdzaj i cofaj tokeny KSeF przez ksef2.
---

Użyj `auth.tokens`, gdy uwierzytelniony kontekst ma tworzyć albo wycofywać
tokeny KSeF dla automatyzacji. Przykłady zakładają, że masz już
uwierzytelnionego klienta `auth`.

Przekaż co najmniej jedno uprawnienie do `generate()`. Wartości tekstowe
używają snake_case, np. `"invoice_read"`. Możesz też podać
`TokenPermissionEnum.INVOICE_READ`. Wartość API, np. `"InvoiceRead"`, zgłasza
`KSeFArgumentError` z sugestią `did you mean "invoice_read"?`. Puste listy
uprawnień, puste numery referencyjne w `revoke()` i puste wartości `ksef_token`
w `with_token()` zgłaszają lokalnie `KSeFArgumentError` przed żądaniem HTTP.

## Wygeneruj token

Wybierz najmniejszy zestaw uprawnień wymagany przez automatyzację, która będzie
używać tokena.

```python
token = auth.tokens.generate(
    permissions=["invoice_read"],
    description="nightly invoice export",
)

token_reference = token.reference_number
token_secret = token.token
```

`generate()` zwraca uchwyt `GeneratedToken`, gdy tylko KSeF udostępni
jednorazową wartość credentiala. Jego pole `token` jest sekretem, którego
automatyzacja użyje później do uwierzytelniania tokenem; uchwyt udostępnia
każde pole odpowiedzi generowania.

Domyślny `repr` i ogólne zrzuty Pydantic pomijają sekret. Odczytuj `.token`
tylko na granicy chronionego magazynu albo użyj `to_sensitive_dict()`, gdy
potrzebujesz jawnej mapy zawierającej sekret.

:::caution[Wartość tokena jest pokazana raz]
Zapisz zwróconą wartość tokena od razu w magazynie sekretów. Późniejsze
wywołania statusu i listowania identyfikują token po `reference_number`, ale
nie odzyskują sekretnej wartości tokena.
:::

Po zapisaniu credentiala poczekaj jawnie, gdy następna operacja wymaga już
aktywnego tokena:

```python
status = auth.tokens.generate(...).wait(timeout=60.0, poll_interval=1.0)
# albo na uchwycie, który już masz:
status = token.wait(timeout=60.0, poll_interval=1.0)
```

Timeout albo błąd transportu z `wait()` nie odrzuca zapisanego wcześniej
credentiala. Wznów sprawdzanie później przez
`auth.tokens.get_status(reference_number=...)`.

### Wznów uchwyt po restarcie

`token.resume_state()` zwraca `GeneratedTokenResumeState`: numer referencyjny
tokena i nic więcej. Zapisz go przez `to_json()` i przekaż do
`auth.tokens.generation()`, gdy pracownik kolejki albo restartowany proces
przejmuje zadanie ponownie.

```python
zapisany_stan = token.resume_state().to_json()

# Później, w tym samym lub innym procesie:
token = auth.tokens.generation(zapisany_stan)
status = token.wait(timeout=60.0, poll_interval=1.0)
```

`generation()` przyjmuje obiekt stanu albo jego JSON i zwraca uchwyt odpytujący
ten sam numer referencyjny. Token jednorazowy nigdy nie trafia do stanu: ani w
`to_json()`, ani w `to_dict()`, `model_dump()` czy `repr()`, dlatego wznowiony
uchwyt nie ma `token` ani `response`. To poświadczenie zapisuj osobno sam.

## Listuj tokeny

`list()` zwraca `Pager`: iteruj po nim, by dostać każdy token, wywołaj
`.pages()` dla list wielkości strony albo `.first_page()`, by wykonać jedno
żądanie. Nic nie jest pobierane, dopóki go nie zużyjesz.

### Wszystkie tokeny

```python
for item in auth.tokens.list():
    print(item.reference_number, item.status, item.description)

# TokenInfo
# {
#   "reference_number": "20260625-TOKEN-...",
#   "description": "nightly invoice export",
#   "requested_permissions": ["invoice_read"],
#   "status": "active"
# }
```

### Jedna strona

```python
first = auth.tokens.list().first_page()
```

### Strona po stronie

```python
for page in auth.tokens.list().pages():
    print(len(page), "tokens on this page")
```

### Wznów od kursora

`.page()` zwraca jedną stronę `Page`: jej `items` oraz `next_cursor`, czyli
napis wskazujący stronę następną. Zapisz ten napis i przekaż go później do
`.page()`, w tym albo w nowym procesie, aby kontynuować bez ponownego pobierania
tokenów już odczytanych.

```python
first = auth.tokens.list().page()
cursor = first.next_cursor

# Later, after a restart.
if cursor is not None:
    second = auth.tokens.list().page(cursor)
```

Odtwórz pager z tymi samymi parametrami: ten kursor zawiera stan kontynuacji
KSeF dla tej kolekcji, a nie filtry. `.pages()` oraz zwykła iteracja korzystają
z tego samego łańcucha kursorów, a `next_cursor` ma wartość `None` dopiero po
ostatniej stronie. Sama pusta strona nie kończy przechodzenia po kolekcji. W kodzie
async to samo odczytanie to `second = await auth.tokens.list().page(cursor)`.

## Sprawdź albo cofnij jeden token

Do późniejszych operacji cyklu życia użyj numeru referencyjnego tokena.

```python
status = auth.tokens.get_status(reference_number="20260625-TOKEN-...")

# TokenStatusResponse
# {
#   "reference_number": "20260625-TOKEN-...",
#   "status": "active"
# }
```

```python
auth.tokens.revoke(reference_number="20260625-TOKEN-...")
```

:::tip[Oddziel referencję od sekretu]
Sekret tokena trzymaj w managerze sekretów. `reference_number` zapisz w
metadanych operacyjnych, żeby później sprawdzić albo cofnąć token bez
ujawniania sekretu.
:::

## Zalecany przepływ

1. Wybierz najmniejszy zestaw uprawnień wymagany przez automatyzację.

2. Wygeneruj token w uwierzytelnionym kontekście, który ma być jego właścicielem.

3. Zapisz wartość tokena w magazynie sekretów, a numer referencyjny w metadanych.

4. Poczekaj na aktywację, gdy token musi być od razu gotowy do użycia.

5. Listuj albo sprawdzaj referencje tokenów podczas audytów.

6. Cofaj tokeny nieużywane, wygasłe albo naruszone.

## Następne przepływy

- [Uwierzytelnianie](authenticate.md): Użyj wygenerowanego tokena KSeF jako jednej z metod uwierzytelniania SDK.
- [Metody uwierzytelniania](../concepts/authentication-methods.md): Zrozum uwierzytelnianie tokenem KSeF, XAdES, certyfikatem TEST i profilami.
- [Konfiguracja klienta](client-setup.md): Utwórz klienta sync albo async przed użyciem gałęzi uwierzytelnionych.
