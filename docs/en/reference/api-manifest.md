---
title: API Manifest
description: Machine-readable description of the public sync API for binding generators.
---

`ksef2.bridge.manifest()` describes the public synchronous API as plain
JSON-compatible data. A binding generator reads that description instead of
re-deriving the API with `inspect`: it does not have to decide which members are
public, which are deprecated, or how a pydantic model and a `Literal` alias
become a type in another language.

The same document is printed by the command line:

```bash
python -m ksef2.bridge manifest > ksef2-manifest.json
```

```python
from ksef2.bridge import FORMAT_VERSION, manifest

document = manifest()
assert document["format_version"] == FORMAT_VERSION
print(len(document["operations"]))
```

Building the manifest is deterministic: the same public API always produces the
same bytes, so you can commit the output and diff it in review.

## What the document holds

| Section | Content |
| --- | --- |
| `format_version` | Version of this layout, read it before parsing anything else. |
| `ksef2_version` | Version of the SDK that produced the document. |
| `json_schema_dialect` | Every schema in the document is JSON Schema 2020-12. |
| `conventions` | How the document encodes `bytes`, defaults, state and live objects. |
| `states` | The state an operation runs on: unauthenticated client, authenticated client, online session, batch session, handle, pager or result. |
| `units` | One entry per public sync class: how to reach it, which state carries it, which operations create it. |
| `operations` | One entry per non-deprecated public sync method. |
| `attributes` | Properties the public classes expose, either a value with a schema or a branch to another unit. |
| `excluded` | Public members that are not operations, each with a reason. |
| `$defs` | One JSON Schema per named type, referenced with a local `$ref`. |

## Operations

An operation names the unit and the state it runs on, and carries a one-line
summary taken from the docstring. Its parameters keep the Python order. Each
parameter gives its schema, whether it is required, its default as JSON, and the
description from the docstring:

```python
from ksef2.bridge import manifest

tokens_list = next(
    operation
    for operation in manifest()["operations"]
    if operation["id"] == "tokens.list"
)
print(tokens_list["state"])
print(tokens_list["returns"]["item"])
```

The result of an operation is described by `returns.kind`:

| `kind` | Meaning |
| --- | --- |
| `value` | Plain data, described by `returns.schema`. |
| `none` | Nothing comes back; the schema is `{"type": "null"}`. |
| `paged` | A collection read one page at a time. `returns.item` is the item type and `returns.schema` is the `Page` that carries the items and the `next_cursor` that resumes the collection. |
| `handle`, `session`, `client` | A live object the SDK builds for you. `returns.unit` names it and `returns.schema` is the resume-state model that carries it, so a caller can save the state and rebuild the object later. |
| `data` | An object described by a data model, such as the decrypted archive behind `ExportedInvoices`. |

Handles and sessions are stateful in Python and stateless in the manifest. A
unit with `receiver_state` adds that state as a parameter named `state` with
`origin: "unit_state"`, because a generated binding has no client holding the
reference number for it. Operations that produce the state, such as
`generated_token.resume_state`, do not take it.

## Types

Every named type is written once in `$defs` and pointed at with a local `$ref`,
so a generator emits one type per definition. That covers pydantic models and the
`Literal` aliases of the SDK, which become named enumerations rather than inline
unions: `auth.with_token` takes `context_type`, and its schema points at
`$defs.ContextIdentifierType` with its accepted values.

Two Python types need a rule because JSON has no counterpart:

- `bytes` travels as a base64 encoded string. Its schema carries
  `contentEncoding: "base64"` and never `format: "binary"`.
- `pathlib.Path` is a string with `format: "path"`. It names a file on the
  machine that runs the SDK, so a remote binding cannot use it.

## Excluded members

Nothing disappears silently. Every public member that is not an operation is
listed in `excluded` with a machine-readable `reason` and a sentence that names
what to use instead:

| `reason` | Why the member is left out |
| --- | --- |
| `deprecated` | PEP 702 marks it; the detail quotes the deprecation message with its replacement. |
| `python_only` | It takes or returns a type with no JSON Schema, such as the `cryptography` objects of `auth.with_xades` or a live session passed to `batch.upload_parts`. |
| `python_iterator` | It yields Python objects, such as `pager.pages()`. Read `page(cursor)` and its cursor instead. |
| `lifecycle` | It manages the local object, such as `client.close()`. |
| `local_filesystem` | It writes files, such as `exported_invoices.save()`. Write them from `archive`. |
| `sensitive` | It is a second path to a secret, such as `generated_token.to_sensitive_dict()`. |
| `abstract` | It is a hook of a base class with unresolved type parameters. |
| `branch_accessor` | It only returns another unit, such as `testdata.temporal()`. |

## Reading the manifest from another language

The document is data, so any JSON parser reads it. `python -m ksef2.bridge
manifest` writes it to standard output; `--indent 0` writes one compact line.
Calling the API itself is not part of this document: it describes the API, and
does not execute it.

## Related

- [Public API contract](public-api.md): Which import paths stay stable.
- [Client lifecycle](client-lifecycle.md): The clients, sessions and handles the units describe.
- [Operations](operations.md): Timeouts, retries and polling behaviour behind the operations.
