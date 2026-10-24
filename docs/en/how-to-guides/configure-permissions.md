---
title: Configure Permissions
description: Grant, query, revoke, and monitor KSeF permissions with ksef2.
---

Use `auth.permissions` when the authenticated context needs to grant, inspect,
or revoke KSeF permissions. Permission changes are asynchronous: grant and
revoke methods return an operation reference first.

Use an 11-digit PESEL or 10-digit NIP with a valid checksum. The identifier
must match `subject_type`. The SDK checks these values before sending a grant,
and rejects empty permission lists and empty IDs passed to `revoke()` or
`revoke_authorization()` with `KSeFArgumentError` and a corrective `hint`.

Pass snake_case permission strings or the matching enum members to
`grant_person()` and `grant_entity()`, just as for `tokens.generate()`.
For example, use `"invoice_read"`, `PersonPermissionTypeEnum.INVOICE_READ`, or
`EntityPermissionTypeEnum.INVOICE_READ`. To allow delegation, keep using
`EntityPermission(type="invoice_read", can_delegate=True)` for an entity grant.
`"InvoiceRead"` raises an error suggesting `"invoice_read"`.

## Grant permissions

Pick the grant method that matches the target subject. Keep the permission set
as small as the workflow allows.

### Person

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

### Entity

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

### Authorization

```python
operation = auth.permissions.grant_authorization(
    subject_type="nip",
    subject_value="5261040828",
    permission="self_invoicing",
    description="Self-invoicing agreement",
    entity_name="Partner Sp. z o.o.",
)
```

## Wait for the operation

Every `grant_*()` and `revoke*()` call returns a `PermissionOperation` handle.
Wait on it until KSeF reports the permission operation result.

```python
status = operation.wait(timeout=60.0, poll_interval=1.0)
```

`wait()` raises `KSeFPermissionOperationFailedError` when KSeF finishes the
operation without applying it and `KSeFPermissionOperationTimeoutError` when it
does not finish in time. To check once without waiting, call
`operation.get_status()`, or `get_operation_status()` when you only stored the
reference number:

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

:::caution[Do not expose the permission before status settles]
A grant response means KSeF accepted an operation request. Wait for the
operation before treating the permission as active in your application.
:::

### Resume the operation after a restart

`operation.resume_state()` returns a `PermissionOperationResumeState` holding the
operation's reference number. Persist it with `to_json()` and pass it to
`auth.permissions.operation()` when a later process picks the work up:

```python
saved_state = operation.resume_state().to_json()

# Later, in the same or another process:
operation = auth.permissions.operation(saved_state)
status = operation.wait(timeout=60.0, poll_interval=1.0)
```

`operation()` takes the state object or its JSON string and returns a handle that
polls the same reference number. The reference number is all KSeF returned for
the operation, so a resumed handle is a full copy of the original.

## Query permissions

The `list_*()` methods have separate shapes because KSeF distinguishes personal,
person, entity, authorization, EU entity, subordinate entity, and subunit
permission records. Each returns a `Pager`: iterate it for every record, call
`.pages()` for page-sized lists, or `.first_page()` for a single request.

### My permissions

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

### Entity grants

```python
from ksef2.models import EntityPermissionsQuery

permissions = auth.permissions.list_entities(
    EntityPermissionsQuery(context_type="nip", context_value="5261040828"),
)

for permission in permissions:
    print(permission.id, permission.permission_type, permission.can_delegate)
```

### Authorizations

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

## Revoke permissions

Use the permission id returned by a listing. Revocation also returns a
`PermissionOperation` handle.

```python
operation = auth.permissions.revoke(permission_id="permission-id")
status = operation.wait()
print(status.status.code, status.status.description)
```

For authorization grants, use the authorization-specific revocation method:

```python
operation = auth.permissions.revoke_authorization(
    permission_id="authorization-id",
)
```

## Check attachment permission

```python
status = auth.permissions.get_attachment_permission_status()

# AttachmentPermissionStatus
# {
#   "is_attachment_allowed": true,
#   "revoked_date": null
# }
```

## Recommended flow

1. Grant the smallest permission set required by the target subject.

2. Persist the operation `reference_number`.

3. Wait for the operation before exposing the permission as active.

4. List permissions to collect ids for audits or revocation.

5. Revoke by permission id when access should end, then wait for the revoke
   operation.

## Next workflows

- [Permissions](../concepts/permissions.md): Understand KSeF permission families and why their query shapes differ.
- [Manage tokens](manage-tokens.md): Generate and revoke automation tokens with scoped permissions.
- [Use TEST data](use-test-data.md): Create sandbox subjects and grants for integration tests.
