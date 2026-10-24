---
title: Skonfiguruj uprawnienia
description: Nadawaj, wyszukuj, odbieraj i monitoruj uprawnienia KSeF z ksef2.
---

Użyj `auth.permissions`, gdy uwierzytelniony kontekst ma nadawać, sprawdzać albo
cofać uprawnienia KSeF. Zmiany uprawnień są asynchroniczne: metody grant i
revoke najpierw zwracają referencję operacji.

Podaj 11-cyfrowy PESEL z poprawną sumą kontrolną lub NIP zgodny z 10-cyfrowym
wzorcem OpenAPI. Nadawanie uprawnień nie sprawdza sumy kontrolnej NIP.
Identyfikator musi odpowiadać `subject_type`. SDK sprawdza te wartości przed
wysłaniem nadania uprawnień. Puste listy uprawnień oraz puste identyfikatory
w `revoke()` i `revoke_authorization()` zgłaszają `KSeFArgumentError` z podpowiedzią
`hint` przed wysłaniem żądania.

W `grant_person()` i `grant_entity()` podawaj uprawnienia w snake_case lub jako
odpowiednie elementy enum, tak jak w `tokens.generate()`. Możesz użyć
`"invoice_read"`, `PersonPermissionTypeEnum.INVOICE_READ` lub
`EntityPermissionTypeEnum.INVOICE_READ`. Aby umożliwić delegowanie uprawnienia
podmiotowi, użyj `EntityPermission(type="invoice_read", can_delegate=True)`.
Wartość `"InvoiceRead"` zgłasza błąd z sugestią `"invoice_read"`.

## Nadaj uprawnienia

Wybierz metodę nadania pasującą do docelowego podmiotu. Utrzymuj zakres
uprawnień tak mały, jak pozwala na to przepływ.

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

### Autoryzacja

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

Każde wywołanie `grant_*()` i `revoke*()` zwraca uchwyt `PermissionOperation`.
Czekaj na niego, aż KSeF zgłosi wynik operacji uprawnień.

```python
status = operation.wait(timeout=60.0, poll_interval=1.0)
```

`wait()` zgłasza `KSeFPermissionOperationFailedError`, gdy KSeF zakończy
operację bez zastosowania uprawnienia, oraz `KSeFPermissionOperationTimeoutError`,
gdy nie zakończy się na czas. Aby sprawdzić jednorazowo bez czekania, wywołaj
`operation.get_status()` albo `get_operation_status()`, gdy zapisałeś tylko
numer referencyjny:

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
Odpowiedź grant oznacza, że KSeF przyjął żądanie operacji. Poczekaj na
operację, zanim potraktujesz uprawnienie jako aktywne w aplikacji.
:::

### Wznów operację po restarcie

`operation.resume_state()` zwraca `PermissionOperationResumeState` z numerem
referencyjnym operacji. Zapisz go przez `to_json()` i przekaż do
`auth.permissions.operation()`, gdy późniejszy proces przejmuje pracę:

```python
zapisany_stan = operation.resume_state().to_json()

# Później, w tym samym lub innym procesie:
operation = auth.permissions.operation(zapisany_stan)
status = operation.wait(timeout=60.0, poll_interval=1.0)
```

`operation()` przyjmuje obiekt stanu albo jego JSON i zwraca uchwyt odpytujący
ten sam numer referencyjny. Numer referencyjny to wszystko, co KSeF zwrócił dla
tej operacji, więc wznowiony uchwyt jest pełną kopią oryginalnego.

## Wyszukaj uprawnienia

Metody `list_*()` mają osobne kształty, ponieważ KSeF rozróżnia rekordy personal,
person, entity, authorization, EU entity, subordinate entity i subunit. Każda
zwraca `Pager`: iteruj po nim, by dostać każdy rekord, wywołaj `.pages()` dla
list wielkości strony albo `.first_page()`, by wykonać jedno żądanie.

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

### Nadania entity

```python
from ksef2.models import EntityPermissionsQuery

permissions = auth.permissions.list_entities(
    EntityPermissionsQuery(context_type="nip", context_value="5261040828"),
)

for permission in permissions:
    print(permission.id, permission.permission_type, permission.can_delegate)
```

### Autoryzacje

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

Użyj identyfikatora uprawnienia zwróconego przez listę. Cofnięcie też zwraca
uchwyt `PermissionOperation`.

```python
operation = auth.permissions.revoke(permission_id="permission-id")
status = operation.wait()
print(status.status.code, status.status.description)
```

Dla nadań autoryzacji użyj metody cofania autoryzacji:

```python
operation = auth.permissions.revoke_authorization(
    permission_id="authorization-id",
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

## Zalecany przepływ

1. Nadaj najmniejszy zestaw uprawnień wymagany przez docelowy podmiot.

2. Zapisz `reference_number` operacji.

3. Poczekaj na operację przed pokazaniem uprawnienia jako aktywnego.

4. Wyszukaj uprawnienia, aby zebrać identyfikatory do audytu albo cofnięcia.

5. Cofnij po identyfikatorze uprawnienia, gdy dostęp ma się zakończyć, a potem
   poczekaj na operację cofnięcia.

## Następne przepływy

- [Uprawnienia](../concepts/permissions.md): Zrozum rodziny uprawnień KSeF i powód różnych kształtów zapytań.
- [Zarządzaj tokenami](manage-tokens.md): Generuj i cofaj tokeny automatyzacji z ograniczonym zakresem uprawnień.
- [Użyj danych TEST](use-test-data.md): Twórz sandboxowe podmioty i nadania dla testów integracyjnych.
