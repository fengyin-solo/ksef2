---
title: ksef2 1.0.0 Release Notes
description: Stability boundary and the documented public surface of the first stable ksef2 SDK release.
---

:::caution[Draft until the 1.0.0 tag]
These notes describe the intended 1.0.0 public contract. Treat the package
changelog and the final GitHub release as authoritative once `v1.0.0` is
tagged.
:::

ksef2 1.0.0 is the first release that treats documented application-facing
imports as a compatibility contract for the 1.x line.
The SDK currently targets KSeF OpenAPI version `2.8.1`.

> **Unofficial SDK.** ksef2 is community-maintained. It is not published,
> endorsed, or supported by Poland's Ministry of Finance. The official KSeF
> documentation remains the source of truth for API behavior.

[Official KSeF API v2 documentation](https://api-test.ksef.mf.gov.pl/docs/v2/) — Use the Ministry of Finance documentation as the authority for API behavior.

## Stable in 1.0

The stable contract is the documented public SDK surface, not every importable
module in the repository.

| Surface | 1.0 contract |
| --- | --- |
| `ksef2` | Root clients, environments, transport config, `FormSchema`, `__version__`, and public exceptions. |
| `ksef2.clients` | Concrete sync and async client classes for type annotations and advanced construction. |
| `ksef2.models` | Public SDK request, response, filter, pagination, token, permission, session, batch, and invoice models. |
| High-level client branches | `client.authentication`, `client.encryption`, `client.peppol`, `client.testdata`, and authenticated branches such as `auth.invoices`, `auth.tokens`, `auth.permissions`, `auth.certificates`, `auth.collective_identifiers`, and `auth.limits`. |
| Collective identifier workflows | `auth.collective_identifiers` generates a collective identifier for supplied invoices, queries identifiers page by page, resolves the identifiers attached to one KSeF number, and lists the invoices inside selected collective identifiers. |
| Session helpers | Online and batch session workflows for sending, polling, UPO, and resumable KSeF references. |
| Paging | Every `Pager` answers `.page(cursor)` with a `Page` (`items`, `next_cursor`), where the cursor is SDK-issued state you can store and replay after a restart, alongside `.pages()`, `.first_page()` and `.wait()`. |
| `ksef2.xades` | Certificate loading, TEST certificate generation, local XAdES signing helpers, and `LocalSigner`. |
| `ksef2.profiles` | Local `ksef2-cli` compatible profile config helpers. |
| `ksef2.fa3` | Public FA(3) invoice builder, draft snapshots, and public FA(3) domain models used by builder workflows. |
| `ksef2.renderers` | Optional local XSLT/PDF invoice rendering helpers when installed with the `pdf` extra. |

For the exact compatibility boundary, use the public API contract page.

## Breaking in 1.0

Transport failures are SDK errors. A public method no longer lets an `httpx`
exception escape: a request that produces no usable response raises
`KSeFTransportError` (`code = "TRANSPORT_ERROR"`) with `method`, `path` and
`outcome_ambiguous`, and the original `httpx` exception as `__cause__`. It covers
every `httpx.RequestError`: connection and timeout failures, a response the HTTP
client could not decode, and an abandoned redirect chain. It does not subclass
`httpx.HTTPError`, so handlers that caught `httpx.HTTPError` must name the SDK
class; `KSeFException` already covers every SDK failure. Retries, API error
classes and `KSeFAuthError` on a 401 or 403 are unchanged.
`KSeFExternalTransferError`, `KSeFBatchUploadError` and
`KSeFAuthTokenRedemptionError` now derive from `KSeFTransportError` and keep their
own codes and recovery behaviour.
See the [migration guide](migration-1-0.md#transport-failures) and the
[error reference](errors.md#transport-failure-attributes).

## Public but lower level

`ksef2.raw` and `ksef2.raw.mappers` are public advanced APIs. Their import paths
are part of the 1.x contract, but their schema-native model shapes follow the
checked Ministry of Finance OpenAPI version.

Use `ksef2.raw` when you need endpoint-level control, exact OpenAPI-shaped
payloads, caller-owned encryption custody, or protocol debugging. Most
application code should use the high-level client branches.

## Not part of the 1.x contract

Do not build application code on these paths:

- any module path with an underscore-prefixed component, such as
  `ksef2._core` or `ksef2._clients.base` (a module path with no underscore is
  public; anything with an underscore is private);
- repository `scripts/*`;
- generated schema internals outside `ksef2.raw.spec` and `ksef2.raw.supp`.

The former paths `ksef2.core`, `ksef2.domain`, `ksef2.infra` and
`ksef2.services`, including their submodules, remain as deprecated aliases.
They emit `DeprecationWarning` once per package family, naming replacements. Existing method aliases
also remain available throughout 1.x, with removal no earlier than 2.0.0.
The private-module rename does not remove these legacy imports in 1.0.

See the [migration guide](migration-1-0.md) for imports, send/wait/UPO and search
examples. Python normally hides these warnings, so enable them in your tests.

## Related pages

- [Public API contract](public-api.md): Review stable imports and internal boundaries for application code.
- [Low-level API](low-level/overview.md): Understand the supported raw endpoint surface and its schema-following model contract.
- [Operations reference](operations.md): Review retries, timeouts, rate limits, logging boundaries, and resumable references.
