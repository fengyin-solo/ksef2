---
title: Konfiguracja uprawnień
description: Nadawaj, wyszukuj, odbieraj i śledź uprawnienia KSeF w ksef2.
---

Użyj `auth.permissions`, gdy uwierzytelniony kontekst logowania ma nadawać, sprawdzać albo cofać uprawnienia KSeF. Zmiany uprawnień są asynchroniczne: metody nadania i cofnięcia najpierw zwracają numer referencyjny operacji.

Podaj 11-cyfrowy PESEL z poprawną sumą kontrolną albo NIP zgodny z 10-cyfrowym wzorcem OpenAPI. Nadawanie uprawnień nie sprawdza sumy kontrolnej NIP. Identyfikator musi odpowiadać `subject_type`. SDK sprawdza te wartości przed wysłaniem nadania. Puste listy uprawnień oraz puste identyfikatory w `revoke()` i `revoke_authorization()` zgłaszają wyjątek `KSeFArgumentError` z podpowiedzią `hint` przed wysłaniem żądania.

W `grant_person()` i `grant_entity()` podawaj uprawnienia w zapisie `snake_case` albo jako odpowiednie elementy wyliczenia, tak jak w `tokens.generate()`. Możesz użyć `"invoice_read"`, `PersonPermissionTypeEnum.INVOICE_READ` albo `EntityPermissionTypeEnum.INVOICE_READ`. Aby pozwolić przekazać uprawnienie dalej, użyj `EntityPermission(type="invoice_read", can_delegate=True)`. Wartość `"InvoiceRead"` zgłasza błąd z sugestią `"invoice_read"`.

## Nadaj uprawnienia

Wybierz metodę nadania pasującą do podmiotu, który ma dostać uprawnienie. Zakres trzymaj tak mały, jak pozwala na to przepływ.

### Osoba

```python
operation = auth.permissions.grant_person(
    subject_type="pesel",
    subject_value="44051401458",
    permissions=["invoice_read"],
    description="Read invoices",
    first_name="Jan",
    last_name="Kowalski",
)

# GrantPermissionsResponse
# {
#   "reference_number": "20260625-PERM-..."
# }
```

### Podmiot

```python
from ksef2.models import EntityPermission

operation = auth.permissions.grant_entity(
    subject_value="5261040828",
    permissions=[
        EntityPermission(type="invoice_read", can_delegate=False),
    ],
    description="Accounting office read access",
    entity_name="Accounting Sp. z o.o.",
)
```

### Podmiot uprawniony

```python
operation = auth.permissions.grant_authorization(
    subject_type="nip",
    subject_value="5261040828",
    permission="self_invoicing",
    description="Self-invoicing agreement",
    entity_name="Partner Sp. z o.o.",
)
```

## Poczekaj na operację

Każde wywołanie `grant_*()` i `revoke*()` zwraca obiekt `PermissionOperation`. Czekaj na niego, aż KSeF poda wynik operacji na uprawnieniach.

```python
status = operation.wait(timeout=60.0, poll_interval=1.0)
```

`wait()` zgłasza wyjątek `KSeFPermissionOperationFailedError`, gdy KSeF zakończy operację bez zastosowania uprawnienia, oraz `KSeFPermissionOperationTimeoutError`, gdy nie zakończy się na czas. Aby sprawdzić raz, bez czekania, wywołaj `operation.get_status()` albo `get_operation_status()`, gdy zapisałeś tylko numer referencyjny:

```python
status = auth.permissions.get_operation_status(
    reference_number=operation.reference_number,
)

# PermissionOperationStatusResponse
# {
#   "status": {
#     "code": 200,
#     "description": "Completed"
#   }
# }
```

:::caution[Nie pokazuj uprawnienia przed zakończeniem statusu]
Odpowiedź nadania oznacza, że KSeF przyjął żądanie operacji. Poczekaj na operację, zanim potraktujesz uprawnienie jako aktywne w aplikacji.
:::

### Wznów operację po restarcie

`operation.resume_state()` zwraca `PermissionOperationResumeState` z numerem referencyjnym operacji. Zapisz go przez `to_json()` i przekaż do `auth.permissions.operation()`, gdy późniejszy proces przejmuje pracę:

```python
zapisany_stan = operation.resume_state().to_json()

# Później, w tym samym lub innym procesie:
operation = auth.permissions.operation(zapisany_stan)
status = operation.wait(timeout=60.0, poll_interval=1.0)
```

`operation()` przyjmuje obiekt stanu albo jego JSON i zwraca obiekt, który sprawdza ten sam numer referencyjny. Numer referencyjny to wszystko, co KSeF zwrócił dla tej operacji, więc wznowiony obiekt jest pełną kopią oryginalnego.

## Wyszukaj uprawnienia

Metody `list_*()` mają osobne struktury zapytań, bo KSeF rozróżnia rekordy uprawnień osobistych, osób, podmiotów, podmiotów uprawnionych, podmiotów unijnych, podmiotów podrzędnych i jednostek podrzędnych. Każda zwraca `Pager`. Iteruj po nim, żeby dostać każdy rekord, wywołaj `.pages()` dla list wielkości strony albo `.first_page()`, żeby wykonać jedno żądanie.

### Moje uprawnienia

```python
from ksef2.models import PersonalPermissionsQuery

permissions = auth.permissions.list_personal(
    PersonalPermissionsQuery(
        permission_types=["invoice_read"],
        permission_state="active",
    ),
)

for permission in permissions:
    print(permission.id, permission.permission_type, permission.permission_state)
```

### Nadania dla podmiotu

```python
from ksef2.models import EntityPermissionsQuery

permissions = auth.permissions.list_entities(
    EntityPermissionsQuery(context_type="nip", context_value="5261040828"),
)

for permission in permissions:
    print(permission.id, permission.permission_type, permission.can_delegate)
```

### Uprawnienia podmiotu uprawnionego

```python
from ksef2.models import AuthorizationPermissionsQuery

grants = auth.permissions.list_authorizations(
    AuthorizationPermissionsQuery(
        query_type="granted",
        permission_types=["self_invoicing"],
    ),
)

for grant in grants:
    print(grant.id, grant.authorization_scope, grant.authorized_entity_value)
```

## Cofnij uprawnienia

Użyj rekordu `permission` wybranego z listy powyżej. Cofnięcie też zwraca obiekt `PermissionOperation`.

```python
operation = auth.permissions.revoke(permission_id=permission.id)
status = operation.wait()
print(status.status.code, status.status.description)
```

Dla rekordu `grant` wybranego z listy uprawnień podmiotu uprawnionego użyj metody cofania tego rodzaju uprawnienia:

```python
operation = auth.permissions.revoke_authorization(
    permission_id=grant.id,
)
```

## Sprawdź uprawnienie do załączników

```python
status = auth.permissions.get_attachment_permission_status()

# AttachmentPermissionStatus
# {
#   "is_attachment_allowed": true,
#   "revoked_date": null
# }
```

## Zalecany przebieg

1. Nadaj najmniejszy zestaw uprawnień wymagany przez podmiot, który ma je dostać.

2. Zapisz `reference_number` operacji.

3. Poczekaj na operację, zanim pokażesz uprawnienie jako aktywne.

4. Wyszukaj uprawnienia, żeby zebrać identyfikatory do audytu albo cofnięcia.

5. Cofnij po identyfikatorze uprawnienia, gdy dostęp ma się skończyć, a potem poczekaj na operację cofnięcia.

## Następne strony

- [Tokeny i uprawnienia](../concepts/permissions.md): rodziny uprawnień KSeF i powód różnych zapytań.
- [Zarządzanie tokenami](manage-tokens.md): tokeny automatyzacji z ograniczonym zakresem uprawnień.
- [Dane testowe](use-test-data.md): podmioty i nadania w środowisku testowym, do testów integracyjnych.
